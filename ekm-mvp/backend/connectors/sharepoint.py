"""
SharePoint Connector — NTLM Direct Auth
─────────────────────────────────────────
The auth probe confirmed:
  ✓ Python requests reach SharePoint (401 is from SP itself, not Zscaler)
  ✓ /_vti_bin/Authentication.asmx → 200 (IIS NTLM negotiation live)
  ✓ /_api/v2.1 → 200 (REST API fully accessible)
  ✗ login.microsoftonline.com → blocked
  ✗ All ADFS endpoints → blocked

Solution: requests_ntlm with explicit domain credentials.
NTLM handshake is negotiated directly between Python and SharePoint's IIS.
No external auth server required — everything stays on the corporate network.

Config (.env):
  SHAREPOINT_USERNAME=firstname.lastname@citi.com   (or DOMAIN\\username)
  SHAREPOINT_PASSWORD=your-windows-password

Sites (sharepoint_sites.txt — one URL per line):
  https://citi.sharepoint.com/sites/cc-ee
  https://citi.sharepoint.com/teams/AutoCon
"""

import re
import logging
import requests
import urllib3
from datetime import datetime, timezone
from pathlib import Path
from config import get_settings
from models import Document, SourceType
from utils.file_extractor import extract_text, SUPPORTED_EXTENSIONS, MAX_FILE_SIZE_MB

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger   = logging.getLogger(__name__)
settings = get_settings()

REQUEST_TIMEOUT    = 60
MAX_PAGES_PER_SITE = 300
MAX_FILES_PER_LIB  = 500


# ── Site list ─────────────────────────────────────────────────────────────────

def _load_site_urls() -> list[str]:
    for candidate in [
        Path(__file__).parent.parent.parent / "sharepoint_sites.txt",
        Path(__file__).parent.parent / "sharepoint_sites.txt",
    ]:
        if candidate.exists():
            lines = candidate.read_text(encoding="utf-8").splitlines()
            urls  = [l.strip() for l in lines
                     if l.strip() and not l.strip().startswith("#")]
            if urls:
                logger.info(f"SharePoint: loaded {len(urls)} sites from sharepoint_sites.txt")
                return urls
    return settings.sharepoint_site_url_list


# ── Auth session ──────────────────────────────────────────────────────────────

def _make_session() -> requests.Session | None:
    """
    Build a requests session using NTLM auth.
    NTLM is negotiated directly with SharePoint's IIS — no external server.
    """
    username = settings.sharepoint_username
    password = settings.sharepoint_password

    if not username or not password:
        logger.error(
            "SharePoint: SHAREPOINT_USERNAME and SHAREPOINT_PASSWORD required in .env\n"
            "  Format: firstname.lastname@citi.com + Windows password"
        )
        return None

    try:
        from requests_ntlm import HttpNtlmAuth
    except ImportError:
        logger.error(
            "SharePoint: requests-ntlm not installed.\n"
            "  Run: pip install requests-ntlm"
        )
        return None

    session         = requests.Session()
    session.auth    = HttpNtlmAuth(username, password)
    session.verify  = False   # corporate SSL cert
    session.headers.update({
        "Accept":       "application/json;odata=verbose",
        "Content-Type": "application/json;odata=verbose",
    })

    logger.info(f"SharePoint: NTLM session created for '{username}'")
    return session


# ── REST helpers ──────────────────────────────────────────────────────────────

def _get(session: requests.Session, url: str) -> dict | None:
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception:
                return {"d": {"value": resp.text.strip()}}
        elif resp.status_code == 401:
            logger.error(
                f"SharePoint 401 — NTLM auth failed.\n"
                f"  Check SHAREPOINT_USERNAME and SHAREPOINT_PASSWORD in .env\n"
                f"  Try format: DOMAIN\\username if email format fails\n"
                f"  URL: {url}"
            )
        elif resp.status_code == 403:
            logger.warning(f"SharePoint 403 — no permission: {url}")
        else:
            logger.warning(f"SharePoint {resp.status_code}: {url}")
        return None
    except Exception as e:
        logger.warning(f"SharePoint request error '{url}': {e}")
        return None


def _check_connection(session: requests.Session, site_url: str) -> str | None:
    """Returns site title on success, None on failure."""
    data = _get(session, f"{site_url}/_api/web/Title")
    if data:
        return data.get("d", {}).get("value", site_url.split("/")[-1])
    return None


# ── HTML → text ───────────────────────────────────────────────────────────────

def _html_to_text(html: str) -> str:
    for tag in ["script", "style", "nav", "header", "footer", "aside", "noscript"]:
        html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", " ", html,
                      flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<td[^>]*>", " | ", html, flags=re.IGNORECASE)
    html = re.sub(r"<tr[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<li[^>]*>", "\n• ", html, flags=re.IGNORECASE)
    html = re.sub(r"<(p|div|br|h[1-6])[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    for pat, rep in [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                     ("&gt;", ">"), (r"&#\d+;", " "), (r"&[a-z]+;", " ")]:
        html = re.sub(pat, rep, html)
    lines = [l.strip() for l in html.splitlines() if len(l.strip()) > 3]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))[:50_000]


def _parse_date(s) -> datetime | None:
    if not s:
        return None
    try:
        if isinstance(s, datetime):
            return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
        s = str(s)
        if s.startswith("/Date("):
            return datetime.fromtimestamp(int(s[6:-2]) / 1000, tz=timezone.utc)
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


# ── Site pages ────────────────────────────────────────────────────────────────

def _crawl_site_pages(
    session: requests.Session,
    site_url: str,
    site_display: str,
    updated_since: datetime | None,
) -> list[Document]:
    url = (
        f"{site_url}/_api/web/lists/getbytitle('Site Pages')/items"
        f"?$select=Title,FileRef,Modified,EncodedAbsUrl,Author/Title"
        f"&$expand=Author&$orderby=Modified desc&$top=500"
    )
    data = _get(session, url)
    if not data:
        return []

    items = data.get("d", {}).get("results", [])
    logger.info(f"SharePoint '{site_display}': {len(items)} site pages found")
    documents = []

    for item in items[:MAX_PAGES_PER_SITE]:
        modified = _parse_date(item.get("Modified"))
        if updated_since and modified and modified <= updated_since:
            continue

        file_ref  = item.get("FileRef", "")
        abs_url   = item.get("EncodedAbsUrl", "")
        title     = item.get("Title") or file_ref.split("/")[-1].replace(".aspx", "")
        author    = (item.get("Author") or {}).get("Title", "")
        page_url  = abs_url or f"{site_url}{file_ref}"

        # Fetch page HTML via NTLM session
        content = ""
        try:
            resp = session.get(page_url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                content = _html_to_text(resp.text)
        except Exception as e:
            logger.warning(f"Page fetch failed '{page_url}': {e}")
        if not content:
            content = title

        doc = Document(
            external_id = file_ref or abs_url,
            source_type = SourceType.SHAREPOINT,
            source      = f"SharePoint / {site_display}",
            title       = title,
            content     = content,
            url         = page_url,
            author      = author or None,
            tags        = ["sharepoint", "page", site_display.lower()],
            metadata    = {"content_type": "page", "site": site_display},
            updated_at  = modified,
        )
        documents.append(doc)

    return documents


# ── Document libraries ────────────────────────────────────────────────────────

def _get_libraries(session: requests.Session, site_url: str) -> list[dict]:
    url  = (
        f"{site_url}/_api/web/lists"
        f"?$filter=BaseTemplate eq 101 and Hidden eq false"
        f"&$select=Title,RootFolder/ServerRelativeUrl&$expand=RootFolder"
    )
    data = _get(session, url)
    if not data:
        return []
    skip = {"style library", "site assets", "form templates",
            "site collection documents", "site pages"}
    return [l for l in data.get("d", {}).get("results", [])
            if l.get("Title", "").lower() not in skip]


def _crawl_folder(
    session: requests.Session,
    site_url: str,
    folder_url: str,
    updated_since: datetime | None,
    depth: int = 0,
) -> list[dict]:
    if depth > 8:
        return []

    files = []
    encoded = folder_url.replace("'", "''")

    # Files
    files_url = (
        f"{site_url.rstrip('/')}/_api/web"
        f"/GetFolderByServerRelativeUrl('{encoded}')/Files"
        f"?$select=Name,ServerRelativeUrl,TimeLastModified,Length,Author/Title"
        f"&$expand=Author&$top=500"
    )
    data = _get(session, files_url)
    if data:
        for f in data.get("d", {}).get("results", []):
            name = f.get("Name", "")
            ext  = name.lower().rsplit(".", 1)[-1] if "." in name else ""
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            size_mb = int(f.get("Length") or 0) / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                continue
            modified = _parse_date(f.get("TimeLastModified"))
            if updated_since and modified and modified <= updated_since:
                continue
            files.append(f)

    # Subfolders
    sub_url = (
        f"{site_url.rstrip('/')}/_api/web"
        f"/GetFolderByServerRelativeUrl('{encoded}')/Folders"
        f"?$select=Name,ServerRelativeUrl&$filter=Name ne 'Forms'"
    )
    sub_data = _get(session, sub_url)
    if sub_data:
        for sub in sub_data.get("d", {}).get("results", []):
            name = sub.get("Name", "")
            if name.startswith(("_", ".")):
                continue
            sub_rel = sub.get("ServerRelativeUrl", "")
            files.extend(_crawl_folder(
                session, site_url, sub_rel, updated_since, depth + 1
            ))

    return files


def _download_file(
    session: requests.Session,
    site_url: str,
    server_relative_url: str,
) -> bytes:
    encoded = server_relative_url.replace("'", "''")
    url = f"{site_url.rstrip('/')}/_api/web/GetFileByServerRelativeUrl('{encoded}')/$value"
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        return resp.content if resp.status_code == 200 else b""
    except Exception as e:
        logger.warning(f"File download failed '{server_relative_url}': {e}")
        return b""


# ── Main ──────────────────────────────────────────────────────────────────────

async def fetch_documents(updated_since: datetime | None = None) -> list[Document]:
    """
    Fetch all SharePoint content using NTLM auth directly against SharePoint IIS.
    No external auth servers — works fully within corporate network.
    """
    site_urls = _load_site_urls()
    if not site_urls:
        logger.warning(
            "No SharePoint URLs. Create sharepoint_sites.txt with one URL per line."
        )
        return []

    session = _make_session()
    if not session:
        return []

    mode = "incremental" if updated_since else "full"
    logger.info(f"SharePoint: {mode} sync — {len(site_urls)} site(s) via NTLM")

    all_documents: list[Document] = []

    for site_url in site_urls:
        site_url     = site_url.strip().rstrip("/")
        site_display = site_url.split("/")[-1]
        is_teams     = "/teams/" in site_url.lower()

        # Verify connection
        title = _check_connection(session, site_url)
        if not title:
            logger.error(
                f"SharePoint: cannot connect to '{site_display}'.\n"
                f"  → Verify SHAREPOINT_USERNAME / SHAREPOINT_PASSWORD in .env\n"
                f"  → Try DOMAIN\\\\username format if email doesn't work"
            )
            continue

        logger.info(f"SharePoint: connected to '{title}' ({site_display})")
        site_count = 0

        # 1. Site pages
        if not is_teams:
            try:
                pages = _crawl_site_pages(session, site_url, site_display, updated_since)
                all_documents.extend(pages)
                site_count += len(pages)
                logger.info(f"SharePoint '{site_display}': {len(pages)} pages indexed")
            except Exception as e:
                logger.error(f"SharePoint pages error '{site_display}': {e}")

        # 2. Document libraries
        try:
            libraries = _get_libraries(session, site_url)
            logger.info(f"SharePoint '{site_display}': {len(libraries)} libraries")

            for lib in libraries:
                lib_title = lib.get("Title", "Documents")
                root_url  = (lib.get("RootFolder") or {}).get("ServerRelativeUrl", "")
                if not root_url:
                    continue

                logger.info(f"SharePoint: crawling library '{lib_title}'...")
                items = _crawl_folder(session, site_url, root_url, updated_since)
                logger.info(f"SharePoint '{lib_title}': {len(items)} files")

                for item in items[:MAX_FILES_PER_LIB]:
                    name       = item.get("Name", "Untitled")
                    server_url = item.get("ServerRelativeUrl", "")
                    modified   = _parse_date(item.get("TimeLastModified"))
                    author     = (item.get("Author") or {}).get("Title", "")
                    ext        = name.lower().rsplit(".", 1)[-1] if "." in name else ""
                    folder     = "/".join(server_url.split("/")[:-1])

                    raw     = _download_file(session, site_url, server_url)
                    content = extract_text(raw, name) if raw else ""
                    if not content:
                        content = f"{name} {lib_title}"

                    doc = Document(
                        external_id = server_url or name,
                        source_type = SourceType.SHAREPOINT,
                        source      = f"SharePoint / {site_display} / {lib_title}",
                        title       = name,
                        content     = content,
                        url         = f"{site_url}{server_url}",
                        author      = author or None,
                        tags        = [
                            "sharepoint", ext,
                            lib_title.lower().replace(" ", "_"),
                            site_display.lower(),
                        ],
                        metadata    = {
                            "content_type": ext,
                            "library":      lib_title,
                            "site":         site_display,
                            "folder_path":  folder,
                            "size_bytes":   int(item.get("Length") or 0),
                        },
                        updated_at  = modified,
                    )
                    all_documents.append(doc)
                    site_count += 1

        except Exception as e:
            logger.error(f"SharePoint libraries error '{site_display}': {e}")

        logger.info(f"SharePoint '{site_display}': done — {site_count} total")

    logger.info(f"SharePoint: TOTAL {len(all_documents)} documents")
    return all_documents