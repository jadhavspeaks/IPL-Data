"""
SharePoint Connector
─────────────────────
Auth modes (tried in order):
  1. Cookie auth  — paste FedAuth + rtFa cookies from your browser (most reliable)
  2. NTLM         — Windows domain credentials for on-premise servers
  3. No auth      — for public sites

SharePoint REST API (_api/web) for all crawling.
Recursive folder crawl across all document libraries.
Extracts text from .docx .pptx .xlsx .pdf .txt .md .csv
Incremental sync via TimeLastModified.
"""

import logging
import requests
import urllib3
from datetime import datetime, timezone
from config import get_settings
from models import Document, SourceType
from utils.file_extractor import extract_text, SUPPORTED_EXTENSIONS, MAX_FILE_SIZE_MB

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)
settings = get_settings()

REQUEST_TIMEOUT    = 60
MAX_FILES_PER_LIB  = 2000


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_session(site_url: str) -> requests.Session:
    """
    Build a requests session with appropriate auth.
    Priority: cookie auth → NTLM → unauthenticated
    """
    session = requests.Session()
    session.verify = False
    session.headers.update({
        "Accept":       "application/json;odata=verbose",
        "Content-Type": "application/json;odata=verbose",
        # Browser-like UA — some SPO configs reject non-browser requests
        "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    })

    fed_auth = settings.sharepoint_fed_auth
    rt_fa    = settings.sharepoint_rt_fa

    # ── Option A: Full cookie string (all cookies from browser) ─────────────
    all_cookies = settings.sharepoint_all_cookies
    if all_cookies:
        session.headers["Cookie"] = all_cookies
        logger.info("SharePoint: using full browser cookie string")
        return session

    # ── Option B: Individual FedAuth + rtFa cookies ───────────────────────
    if fed_auth or rt_fa:
        cookie_parts = []
        if fed_auth:
            cookie_parts.append(f"FedAuth={fed_auth}")
        if rt_fa:
            cookie_parts.append(f"rtFa={rt_fa}")
        session.headers["Cookie"] = "; ".join(cookie_parts)
        logger.info("SharePoint: using FedAuth/rtFa cookie auth")
        return session

    username = settings.sharepoint_username
    password = settings.sharepoint_password

    if username and password:
        auth_type = settings.sharepoint_auth_type.lower()
        if auth_type == "ntlm":
            # ── NTLM (on-premise SharePoint Server) ──────────────────────────
            try:
                from requests_ntlm import HttpNtlmAuth
                session.auth = HttpNtlmAuth(username, password)
                logger.info("SharePoint: using NTLM auth")
            except ImportError:
                logger.warning("requests-ntlm not installed — falling back to no auth")
        else:
            # ── Basic auth fallback ───────────────────────────────────────────
            session.auth = (username, password)
            logger.info("SharePoint: using basic auth")
        return session

    logger.info("SharePoint: no credentials — trying unauthenticated (public sites only)")
    return session


# ── SharePoint REST helpers ───────────────────────────────────────────────────

def _sp_get(session: requests.Session, url: str) -> dict | None:
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception:
                return {"d": {"value": resp.text.strip()}}
        if resp.status_code == 401:
            logger.error(f"SharePoint 401 for: {url}")
            logger.error(f"401 body: {resp.text[:600]}")
            logger.error(f"401 headers: { {k:v for k,v in resp.headers.items() if k in ('WWW-Authenticate','X-Forms_Based_Auth_Required','Location')} }")
        elif resp.status_code == 403:
            logger.error(f"SharePoint 403 Forbidden: {url} — {resp.text[:300]}")
        else:
            logger.warning(f"SharePoint {resp.status_code}: {url} — {resp.text[:200]}")
        return None
    except Exception as e:
        logger.warning(f"SharePoint GET error: {e}")
        return None


def _get_libraries(session: requests.Session, site_url: str) -> list[dict]:
    """Get all document libraries (BaseTemplate=101, not hidden)."""
    url  = f"{site_url.rstrip('/')}/_api/web/lists?$filter=BaseTemplate eq 101 and Hidden eq false&$select=Title,RootFolder/ServerRelativeUrl&$expand=RootFolder"
    data = _sp_get(session, url)
    if not data:
        return []
    return data.get("d", {}).get("results", [])


def _crawl_folder(
    session: requests.Session,
    site_url: str,
    folder_server_url: str,
    updated_since: datetime | None,
    depth: int = 0,
) -> list[dict]:
    """Recursively collect all supported files under a folder."""
    if depth > 8:
        return []

    base  = site_url.rstrip("/")
    files = []

    # Encode the folder URL for the REST call
    encoded = folder_server_url.replace("'", "''")

    # ── Files in this folder ──────────────────────────────────────────────────
    files_url = (
        f"{base}/_api/web/GetFolderByServerRelativeUrl('{encoded}')/Files"
        f"?$select=Name,ServerRelativeUrl,TimeLastModified,Length,Author/Title"
        f"&$expand=Author&$top=500"
    )
    data = _sp_get(session, files_url)
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

            if updated_since:
                modified = _parse_sp_date(f.get("TimeLastModified", ""))
                if modified and modified <= updated_since:
                    continue

            files.append(f)

    # ── Subfolders ────────────────────────────────────────────────────────────
    folders_url = (
        f"{base}/_api/web/GetFolderByServerRelativeUrl('{encoded}')/Folders"
        f"?$select=Name,ServerRelativeUrl&$filter=Name ne 'Forms'"
    )
    folder_data = _sp_get(session, folders_url)
    if folder_data:
        for sub in folder_data.get("d", {}).get("results", []):
            sub_name = sub.get("Name", "")
            sub_url  = sub.get("ServerRelativeUrl", "")
            if sub_name.startswith(("_", ".")):
                continue
            sub_files = _crawl_folder(
                session, site_url, sub_url, updated_since, depth + 1
            )
            files.extend(sub_files)

    return files


def _download_file(session: requests.Session, site_url: str, server_url: str) -> bytes:
    encoded = server_url.replace("'", "''")
    url = f"{site_url.rstrip('/')}/_api/web/GetFileByServerRelativeUrl('{encoded}')/$value"
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        return resp.content if resp.status_code == 200 else b""
    except Exception as e:
        logger.warning(f"Download error '{server_url}': {e}")
        return b""


def _get_site_pages(
    session: requests.Session,
    site_url: str,
    updated_since: datetime | None,
) -> list[dict]:
    base = site_url.rstrip("/")
    url  = (
        f"{base}/_api/web/lists/getbytitle('Site Pages')/items"
        f"?$select=Title,FileRef,Modified,Author/Title,CanvasContent1"
        f"&$expand=Author&$top=500"
    )
    data = _sp_get(session, url)
    if not data:
        return []
    pages = []
    for item in data.get("d", {}).get("results", []):
        if updated_since:
            modified = _parse_sp_date(item.get("Modified", ""))
            if modified and modified <= updated_since:
                continue
        pages.append(item)
    return pages


def _parse_sp_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    try:
        if date_str.startswith("/Date("):
            ts = int(date_str[6:-2]) / 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

async def fetch_documents(updated_since: datetime | None = None) -> list[Document]:
    site_urls = settings.sharepoint_site_url_list
    if not site_urls:
        logger.warning("SHAREPOINT_SITE_URLS not configured — skipping")
        return []

    mode = "incremental" if updated_since else "full"
    logger.info(f"SharePoint: {mode} sync across {len(site_urls)} site(s)")

    all_documents: list[Document] = []

    for site_url in site_urls:
        site_url     = site_url.strip().rstrip("/")
        site_display = site_url.split("/")[-1]

        logger.info(f"SharePoint: connecting to '{site_display}'...")
        session = _get_session(site_url)

        # Quick connectivity check — /Title returns just the value, no query params needed
        test = _sp_get(session, f"{site_url}/_api/web/Title")
        if not test:
            test = _sp_get(session, f"{site_url}/_api/web")
        if not test:
            logger.error(
                f"SharePoint: cannot reach '{site_display}'. "
                f"Check site URL and that FedAuth/rtFa cookies are current. Skipping."
            )
            continue

        site_title = (
            test.get("d", {}).get("value")
            or test.get("d", {}).get("Title")
            or site_display
        )
        logger.info(f"SharePoint: connected to '{site_title}'")
        site_doc_count = 0
        site_doc_count = 0

        # ── Site Pages ────────────────────────────────────────────────────────
        try:
            pages = _get_site_pages(session, site_url, updated_since)
            for page in pages:
                file_ref = page.get("FileRef", "")
                modified = _parse_sp_date(page.get("Modified", ""))
                author   = (page.get("Author") or {}).get("Title", "")

                # Strip HTML from canvas content if present
                canvas = page.get("CanvasContent1") or ""
                import re
                content = re.sub(r"<[^>]+>", " ", canvas)
                content = re.sub(r"\s+", " ", content).strip()

                doc = Document(
                    external_id = file_ref or page.get("Title", ""),
                    source_type = SourceType.SHAREPOINT,
                    source      = f"SharePoint / {site_display}",
                    title       = page.get("Title", "Untitled Page"),
                    content     = content,
                    url         = f"{site_url}{file_ref}",
                    author      = author or None,
                    tags        = ["sharepoint", "page", site_display.lower()],
                    metadata    = {"content_type": "page", "site": site_display},
                    updated_at  = modified,
                )
                all_documents.append(doc)
                site_doc_count += 1
            logger.info(f"SharePoint '{site_display}': {len(pages)} site pages")
        except Exception as e:
            logger.warning(f"SharePoint site pages error: {e}")

        # ── Document Libraries ────────────────────────────────────────────────
        try:
            libraries = _get_libraries(session, site_url)
            logger.info(f"SharePoint '{site_display}': {len(libraries)} libraries found")

            for lib in libraries:
                lib_title   = lib.get("Title", "Documents")
                root_folder = (lib.get("RootFolder") or {}).get("ServerRelativeUrl", "")
                if not root_folder:
                    continue

                logger.info(f"SharePoint: crawling '{lib_title}'...")
                try:
                    items = _crawl_folder(session, site_url, root_folder, updated_since)
                except Exception as e:
                    logger.warning(f"Crawl failed '{lib_title}': {e}")
                    continue

                logger.info(f"SharePoint '{lib_title}': {len(items)} files to extract")

                for item in items[:MAX_FILES_PER_LIB]:
                    name       = item.get("Name", "Untitled")
                    server_url = item.get("ServerRelativeUrl", "")
                    modified   = _parse_sp_date(item.get("TimeLastModified", ""))
                    author     = (item.get("Author") or {}).get("Title", "")
                    ext        = name.lower().rsplit(".", 1)[-1] if "." in name else ""

                    try:
                        raw   = _download_file(session, site_url, server_url)
                        content = extract_text(raw, name) if raw else ""
                    except Exception as e:
                        logger.warning(f"Extraction failed '{name}': {e}")
                        content = ""

                    if not content:
                        content = f"{name} {lib_title}"

                    folder_path = "/".join(server_url.split("/")[:-1])

                    doc = Document(
                        external_id = server_url or name,
                        source_type = SourceType.SHAREPOINT,
                        source      = f"SharePoint / {site_display} / {lib_title}",
                        title       = name,
                        content     = content,
                        url         = f"{site_url}{server_url}",
                        author      = author or None,
                        tags        = ["sharepoint", ext, lib_title.lower().replace(" ", "_"), site_display.lower()],
                        metadata    = {
                            "content_type": ext,
                            "library":      lib_title,
                            "site":         site_display,
                            "folder_path":  folder_path,
                            "size_bytes":   int(item.get("Length") or 0),
                        },
                        updated_at  = modified,
                    )
                    all_documents.append(doc)
                    site_doc_count += 1

                    if site_doc_count % 50 == 0:
                        logger.info(f"SharePoint '{site_display}': {site_doc_count} docs so far...")

        except Exception as e:
            logger.error(f"SharePoint libraries error '{site_display}': {e}")

        logger.info(f"SharePoint '{site_display}': done — {site_doc_count} total")

    logger.info(f"SharePoint: TOTAL {len(all_documents)} documents")
    return all_documents
