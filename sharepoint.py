"""
SharePoint Connector — Enterprise Edition
──────────────────────────────────────────
Uses Windows SSPI (Kerberos/NTLM) for authentication.
No cookies, no Azure AD, no tokens, no browser automation.

Your laptop is domain-joined to Citi AD. SharePoint Online is federated
to that same AD via ADFS. Windows SSPI negotiates auth using your current
Windows login session automatically — the same credential that unlocks
your laptop and signs you into everything else.

This is the standard enterprise integration pattern used by tools like
curl --negotiate, PowerShell Invoke-WebRequest, and Office clients.

Library: requests-negotiate-sspi (pip install requests-negotiate-sspi)

Handles both URL types:
  /sites/xxx  — SharePoint sites (SitePages + document libraries)
  /teams/xxx  — Teams-connected sites (document libraries)

Sites config: sharepoint_sites.txt in project root (one URL per line)
"""

import os
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

REQUEST_TIMEOUT   = 60
MAX_FILES_PER_LIB = 500
MAX_PAGES_PER_SITE = 300


# ── Site list ─────────────────────────────────────────────────────────────────

def _load_site_urls() -> list[str]:
    """
    Load SharePoint URLs from sharepoint_sites.txt or .env fallback.
    sharepoint_sites.txt lives in project root — one URL per line.
    Lines starting with # are comments.
    """
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


# ── Session ───────────────────────────────────────────────────────────────────

def _make_session() -> requests.Session:
    """
    Build a requests session using Windows SSPI (Kerberos/NTLM).
    Uses current Windows login — no credentials needed in config.
    Falls back to explicit username/password if SSPI not available.
    """
    session = requests.Session()
    session.verify = False   # org Zscaler cert — skip verification
    session.headers.update({
        "Accept":       "application/json;odata=verbose",
        "Content-Type": "application/json;odata=verbose",
    })

    # ── Primary: Windows SSPI (Kerberos/NTLM negotiate) ──────────────────────
    try:
        from requests_negotiate_sspi import HttpNegotiateAuth
        session.auth = HttpNegotiateAuth()
        logger.info("SharePoint: using Windows SSPI (Kerberos/NTLM) auth")
        return session
    except ImportError:
        logger.warning(
            "requests-negotiate-sspi not installed. "
            "Run: pip install requests-negotiate-sspi"
        )
    except Exception as e:
        logger.warning(f"SSPI auth setup failed: {e}")

    # ── Fallback: explicit NTLM with credentials from .env ───────────────────
    username = settings.sharepoint_username
    password = settings.sharepoint_password
    if username and password:
        try:
            from requests_ntlm import HttpNtlmAuth
            session.auth = HttpNtlmAuth(username, password)
            logger.info("SharePoint: using explicit NTLM auth")
            return session
        except ImportError:
            pass

    logger.warning("SharePoint: no auth configured — unauthenticated requests only")
    return session


# ── REST API helpers ──────────────────────────────────────────────────────────

def _get(session: requests.Session, url: str) -> dict | None:
    """GET a SharePoint REST endpoint, return parsed JSON."""
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)

        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception:
                # Scalar endpoints (like /Title) return plain value
                return {"d": {"value": resp.text.strip()}}

        if resp.status_code == 401:
            logger.error(
                f"SharePoint 401 — SSPI auth failed. "
                f"Ensure requests-negotiate-sspi is installed and "
                f"you are logged into Windows domain. URL: {url}"
            )
        elif resp.status_code == 403:
            logger.warning(f"SharePoint 403 — no permission for: {url}")
        else:
            logger.warning(f"SharePoint {resp.status_code}: {url}")

        return None
    except Exception as e:
        logger.warning(f"SharePoint request error: {e}")
        return None


def _check_connection(session: requests.Session, site_url: str) -> str | None:
    """
    Verify we can reach the site and return its title.
    Returns site title on success, None on failure.
    """
    data = _get(session, f"{site_url}/_api/web/Title")
    if data:
        return data.get("d", {}).get("value", site_url.split("/")[-1])
    return None


# ── Site pages ────────────────────────────────────────────────────────────────

def _get_site_pages(
    session: requests.Session,
    site_url: str,
    updated_since: datetime | None,
) -> list[dict]:
    """Fetch all SitePages items with title, URL, modified date."""
    url = (
        f"{site_url}/_api/web/lists/getbytitle('Site Pages')/items"
        f"?$select=Title,FileRef,Modified,Author/Title,EncodedAbsUrl"
        f"&$expand=Author&$orderby=Modified desc&$top=500"
    )
    data = _get(session, url)
    if not data:
        return []

    pages = []
    for item in data.get("d", {}).get("results", []):
        modified = _parse_date(item.get("Modified", ""))
        if updated_since and modified and modified <= updated_since:
            continue
        pages.append(item)

    return pages[:MAX_PAGES_PER_SITE]


def _fetch_page_content(session: requests.Session, page_url: str) -> str:
    """
    Fetch the rendered HTML of a SharePoint page and extract clean text.
    Uses the page's REST endpoint to get canvas/body content.
    """
    try:
        resp = session.get(page_url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return ""
        return _html_to_text(resp.text)
    except Exception as e:
        logger.warning(f"SharePoint page fetch failed '{page_url}': {e}")
        return ""


def _html_to_text(html: str) -> str:
    """Extract readable text from SharePoint page HTML."""
    # Remove noise elements
    for tag in ["script", "style", "nav", "header", "footer", "aside", "noscript"]:
        html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", " ", html,
                      flags=re.DOTALL | re.IGNORECASE)
    # Table cells
    html = re.sub(r"<td[^>]*>", " | ", html, flags=re.IGNORECASE)
    html = re.sub(r"<tr[^>]*>", "\n", html, flags=re.IGNORECASE)
    # Lists
    html = re.sub(r"<li[^>]*>", "\n• ", html, flags=re.IGNORECASE)
    # Block elements
    html = re.sub(r"<(p|div|br|h[1-6])[^>]*>", "\n", html, flags=re.IGNORECASE)
    # Strip tags
    html = re.sub(r"<[^>]+>", " ", html)
    # Entities
    for pat, rep in [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                     ("&gt;", ">"), (r"&#\d+;", " "), (r"&[a-z]+;", " ")]:
        html = re.sub(pat, rep, html)
    # Clean whitespace
    lines = [l.strip() for l in html.splitlines() if len(l.strip()) > 3]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))[:50_000]


# ── Document libraries ────────────────────────────────────────────────────────

def _get_libraries(session: requests.Session, site_url: str) -> list[dict]:
    """Get all document libraries (BaseTemplate=101, not hidden)."""
    url  = (
        f"{site_url}/_api/web/lists"
        f"?$filter=BaseTemplate eq 101 and Hidden eq false"
        f"&$select=Title,RootFolder/ServerRelativeUrl&$expand=RootFolder"
    )
    data = _get(session, url)
    if not data:
        return []
    libs = data.get("d", {}).get("results", [])
    # Skip system libraries
    skip = {"style library", "site assets", "form templates",
            "site collection documents", "site pages"}
    return [l for l in libs if l.get("Title", "").lower() not in skip]


def _crawl_folder(
    session: requests.Session,
    site_url: str,
    folder_url: str,
    updated_since: datetime | None,
    depth: int = 0,
) -> list[dict]:
    """Recursively collect all supported files under a folder."""
    if depth > 8:
        return []

    base    = site_url.rstrip("/")
    encoded = folder_url.replace("'", "''")
    files   = []

    # Files in this folder
    files_url = (
        f"{base}/_api/web/GetFolderByServerRelativeUrl('{encoded}')/Files"
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
                logger.info(f"Skipping large file ({size_mb:.1f}MB): {name}")
                continue
            modified = _parse_date(f.get("TimeLastModified", ""))
            if updated_since and modified and modified <= updated_since:
                continue
            files.append(f)

    # Subfolders
    sub_url = (
        f"{base}/_api/web/GetFolderByServerRelativeUrl('{encoded}')/Folders"
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
    """Download file content via SharePoint REST."""
    encoded = server_relative_url.replace("'", "''")
    url = (
        f"{site_url.rstrip('/')}/_api/web"
        f"/GetFileByServerRelativeUrl('{encoded}')/$value"
    )
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        return resp.content if resp.status_code == 200 else b""
    except Exception as e:
        logger.warning(f"File download failed '{server_relative_url}': {e}")
        return b""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        if s.startswith("/Date("):
            return datetime.fromtimestamp(int(s[6:-2]) / 1000, tz=timezone.utc)
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

async def fetch_documents(updated_since: datetime | None = None) -> list[Document]:
    """
    Fetch all SharePoint content using Windows SSPI auth.
    Reads site list from sharepoint_sites.txt.
    """
    site_urls = _load_site_urls()
    if not site_urls:
        logger.warning(
            "No SharePoint URLs configured. "
            "Create sharepoint_sites.txt in project root with one URL per line."
        )
        return []

    mode = "incremental" if updated_since else "full"
    logger.info(f"SharePoint: {mode} sync — {len(site_urls)} site(s)")

    # One session for all sites — SSPI negotiates per-request
    session = _make_session()

    all_documents: list[Document] = []

    for site_url in site_urls:
        site_url     = site_url.strip().rstrip("/")
        site_display = site_url.split("/")[-1]
        is_teams     = "/teams/" in site_url.lower()

        # Connectivity check
        title = _check_connection(session, site_url)
        if not title:
            logger.error(
                f"SharePoint: cannot connect to '{site_display}'. "
                f"Check that requests-negotiate-sspi is installed and "
                f"you are on the Citi network / VPN."
            )
            continue

        logger.info(f"SharePoint: connected to '{title}' ({site_display})")
        site_count = 0

        # ── 1. Site pages (not for Teams-only sites) ──────────────────────────
        if not is_teams:
            try:
                pages = _get_site_pages(session, site_url, updated_since)
                logger.info(f"SharePoint '{site_display}': {len(pages)} site pages")

                for page in pages:
                    file_ref  = page.get("FileRef", "")
                    abs_url   = page.get("EncodedAbsUrl", "")
                    title_str = page.get("Title") or file_ref.split("/")[-1].replace(".aspx", "")
                    author    = (page.get("Author") or {}).get("Title", "")
                    modified  = _parse_date(page.get("Modified", ""))

                    # Fetch actual page text
                    page_url = abs_url or f"{site_url}{file_ref}"
                    content  = _fetch_page_content(session, page_url)

                    if not content:
                        content = title_str

                    doc = Document(
                        external_id = file_ref or abs_url,
                        source_type = SourceType.SHAREPOINT,
                        source      = f"SharePoint / {site_display}",
                        title       = title_str,
                        content     = content,
                        url         = page_url,
                        author      = author or None,
                        tags        = ["sharepoint", "page", site_display.lower()],
                        metadata    = {
                            "content_type": "page",
                            "site":         site_display,
                        },
                        updated_at  = modified,
                    )
                    all_documents.append(doc)
                    site_count += 1

            except Exception as e:
                logger.error(f"SharePoint site pages error '{site_display}': {e}")

        # ── 2. Document libraries ─────────────────────────────────────────────
        try:
            libraries = _get_libraries(session, site_url)
            logger.info(f"SharePoint '{site_display}': {len(libraries)} document libraries")

            for lib in libraries:
                lib_title  = lib.get("Title", "Documents")
                root_url   = (lib.get("RootFolder") or {}).get("ServerRelativeUrl", "")
                if not root_url:
                    continue

                logger.info(f"SharePoint: crawling '{lib_title}'...")
                items = _crawl_folder(session, site_url, root_url, updated_since)
                logger.info(f"SharePoint '{lib_title}': {len(items)} files")

                for item in items[:MAX_FILES_PER_LIB]:
                    name       = item.get("Name", "Untitled")
                    server_url = item.get("ServerRelativeUrl", "")
                    modified   = _parse_date(item.get("TimeLastModified", ""))
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

                    if site_count % 50 == 0:
                        logger.info(
                            f"SharePoint '{site_display}': {site_count} docs processed..."
                        )

        except Exception as e:
            logger.error(f"SharePoint libraries error '{site_display}': {e}")

        logger.info(f"SharePoint '{site_display}': done — {site_count} total")

    logger.info(f"SharePoint: TOTAL {len(all_documents)} documents")
    return all_documents
