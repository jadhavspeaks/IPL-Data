"""
SharePoint Connector
─────────────────────
Supports two auth modes, auto-detected from config:

  1. Office365 (shareplum) — for citi.sharepoint.com and other SPO
     Uses username + password via Office365 forms auth
     No Azure AD app registration needed

  2. NTLM — for on-premise SharePoint Server on org network
     Uses Windows domain credentials

Crawls all document libraries recursively per site.
Extracts text from .docx .pptx .xlsx .pdf .txt .md .csv
Supports incremental sync via file modified dates.
Public sites (no auth) also supported — just leave credentials blank.
"""

import logging
import requests
from datetime import datetime, timezone
from config import get_settings
from models import Document, SourceType
from utils.file_extractor import extract_text, SUPPORTED_EXTENSIONS, MAX_FILE_SIZE_MB

logger = logging.getLogger(__name__)
settings = get_settings()

REQUEST_TIMEOUT = 60
MAX_FILES_PER_LIBRARY = 2000


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _get_office365_session(site_url: str) -> requests.Session | None:
    """
    Authenticate using shareplum Office365 auth.
    Returns a requests.Session with auth cookies set.
    Works for citi.sharepoint.com style URLs.
    """
    try:
        from shareplum import Site, Office365
        from shareplum.site import Version

        username = settings.sharepoint_username
        password = settings.sharepoint_password

        if not username or not password:
            logger.warning("SharePoint credentials not set — trying unauthenticated")
            return requests.Session()

        # Extract base URL  e.g. https://citi.sharepoint.com
        parts    = site_url.split("/")
        base_url = "/".join(parts[:3])

        authcookie = Office365(base_url, username=username, password=password).GetCookies()
        session    = requests.Session()
        session.cookies.update(authcookie)
        session.headers.update({
            "Accept":       "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose",
        })
        logger.info(f"SharePoint Office365 auth successful for {base_url}")
        return session

    except Exception as e:
        logger.error(f"SharePoint Office365 auth failed: {e}")
        return None


def _get_ntlm_session() -> requests.Session | None:
    """
    NTLM auth session for on-premise SharePoint.
    Uses Windows domain credentials.
    """
    try:
        from requests_ntlm import HttpNtlmAuth

        username = settings.sharepoint_username
        password = settings.sharepoint_password

        if not username or not password:
            logger.warning("SharePoint NTLM credentials not set")
            return None

        session      = requests.Session()
        session.auth = HttpNtlmAuth(username, password)
        session.headers.update({
            "Accept":       "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose",
        })
        logger.info("SharePoint NTLM auth configured")
        return session

    except Exception as e:
        logger.error(f"SharePoint NTLM auth failed: {e}")
        return None


def _get_session(site_url: str) -> requests.Session | None:
    """Get appropriate session based on auth_type setting."""
    auth_type = settings.sharepoint_auth_type.lower()

    if auth_type == "ntlm":
        return _get_ntlm_session()
    else:
        # Default: Office365 (works for citi.sharepoint.com)
        return _get_office365_session(site_url)


# ── SharePoint REST API helpers ───────────────────────────────────────────────

def _sp_get(session: requests.Session, url: str) -> dict | None:
    """Make a SharePoint REST API GET request, return parsed JSON."""
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, verify=False)
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"SharePoint GET {url} → {resp.status_code}")
        return None
    except Exception as e:
        logger.warning(f"SharePoint GET failed: {e}")
        return None


def _get_lists(session: requests.Session, site_url: str) -> list[dict]:
    """
    Get all document libraries in a SharePoint site.
    BaseTemplate=101 means Document Library.
    """
    url  = f"{site_url.rstrip('/')}/_api/web/lists?$filter=BaseTemplate eq 101 and Hidden eq false"
    data = _sp_get(session, url)
    if not data:
        return []
    return data.get("d", {}).get("results", [])


def _get_folder_files(
    session: requests.Session,
    site_url: str,
    folder_url: str,
    updated_since: datetime | None,
    depth: int = 0,
) -> list[dict]:
    """
    Recursively get all files in a folder and its subfolders.
    folder_url is the server-relative URL of the folder.
    """
    if depth > 8:
        return []

    base = site_url.rstrip("/")
    files = []

    # ── Get files in current folder ───────────────────────────────────────────
    files_url = (
        f"{base}/_api/web/GetFolderByServerRelativeUrl('{folder_url}')"
        f"/Files?$select=Name,ServerRelativeUrl,TimeLastModified,Length,Author/Title"
        f"&$expand=Author&$top=500"
    )
    data = _sp_get(session, files_url)
    if data:
        for f in data.get("d", {}).get("results", []):
            name = f.get("Name", "")
            ext  = name.lower().rsplit(".", 1)[-1] if "." in name else ""

            if ext not in SUPPORTED_EXTENSIONS:
                continue

            size_bytes = int(f.get("Length") or 0)
            size_mb    = size_bytes / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                logger.info(f"Skipping large file ({size_mb:.1f}MB): {name}")
                continue

            # Incremental filter
            if updated_since:
                modified_str = f.get("TimeLastModified", "")
                if modified_str:
                    try:
                        # SharePoint returns dates like /Date(1234567890000)/
                        if modified_str.startswith("/Date("):
                            ts = int(modified_str[6:-2]) / 1000
                            modified = datetime.fromtimestamp(ts, tz=timezone.utc)
                        else:
                            modified = datetime.fromisoformat(
                                modified_str.replace("Z", "+00:00")
                            )
                        if modified <= updated_since:
                            continue
                    except Exception:
                        pass

            files.append(f)

    # ── Recurse into subfolders ───────────────────────────────────────────────
    folders_url = (
        f"{base}/_api/web/GetFolderByServerRelativeUrl('{folder_url}')"
        f"/Folders?$select=Name,ServerRelativeUrl&$filter=Name ne 'Forms'"
    )
    folder_data = _sp_get(session, folders_url)
    if folder_data:
        for sub in folder_data.get("d", {}).get("results", []):
            sub_url  = sub.get("ServerRelativeUrl", "")
            sub_name = sub.get("Name", "")
            # Skip system folders
            if sub_name.startswith("_") or sub_name.startswith("."):
                continue
            sub_files = _get_folder_files(
                session, site_url, sub_url, updated_since, depth + 1
            )
            files.extend(sub_files)

    return files


def _download_file(session: requests.Session, site_url: str, server_relative_url: str) -> bytes:
    """Download a file by its server-relative URL."""
    base = site_url.rstrip("/")
    url  = f"{base}/_api/web/GetFileByServerRelativeUrl('{server_relative_url}')/$value"
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, verify=False)
        if resp.status_code == 200:
            return resp.content
        logger.warning(f"File download failed: {resp.status_code} — {server_relative_url}")
        return b""
    except Exception as e:
        logger.warning(f"File download error: {e}")
        return b""


def _parse_sp_date(date_str: str) -> datetime | None:
    """Parse SharePoint date strings — handles /Date(...)/ and ISO formats."""
    if not date_str:
        return None
    try:
        if date_str.startswith("/Date("):
            ts = int(date_str[6:-2]) / 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        return None


# ── Site pages ────────────────────────────────────────────────────────────────

def _get_site_pages(
    session: requests.Session,
    site_url: str,
    updated_since: datetime | None,
) -> list[dict]:
    """Fetch SharePoint wiki/site pages via Pages library."""
    base = site_url.rstrip("/")
    url  = (
        f"{base}/_api/web/lists/getbytitle('Site Pages')/items"
        f"?$select=Title,FileRef,Modified,Author/Title,Description0"
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


# ── Main entry point ──────────────────────────────────────────────────────────

async def fetch_documents(updated_since: datetime | None = None) -> list[Document]:
    """
    Fetch all SharePoint documents across configured sites.
    Auto-detects auth type from SHAREPOINT_AUTH_TYPE setting.
    Falls back gracefully if auth fails or site is unreachable.
    """
    site_urls = settings.sharepoint_site_url_list
    if not site_urls:
        logger.warning("No SharePoint site URLs configured (SHAREPOINT_SITE_URLS) — skipping")
        return []

    mode = "incremental" if updated_since else "full"
    logger.info(f"SharePoint: {mode} sync across {len(site_urls)} site(s)")

    # Suppress SSL warnings for internal sites
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    all_documents: list[Document] = []

    for site_url in site_urls:
        site_url     = site_url.strip().rstrip("/")
        site_display = site_url.split("/")[-1]

        logger.info(f"SharePoint: connecting to '{site_display}'...")

        # ── Get auth session ──────────────────────────────────────────────────
        session = _get_session(site_url)
        if session is None:
            logger.error(f"SharePoint: could not create session for '{site_display}' — skipping")
            continue

        site_doc_count = 0

        # ── 1. Site pages ─────────────────────────────────────────────────────
        try:
            pages = _get_site_pages(session, site_url, updated_since)
            for page in pages:
                title       = page.get("Title") or "Untitled Page"
                file_ref    = page.get("FileRef", "")
                modified    = _parse_sp_date(page.get("Modified", ""))
                author      = (page.get("Author") or {}).get("Title", "")
                description = page.get("Description0") or ""
                page_url    = f"{site_url}{file_ref}" if file_ref.startswith("/") else f"{site_url}/{file_ref}"

                doc = Document(
                    external_id = file_ref or title,
                    source_type = SourceType.SHAREPOINT,
                    source      = f"SharePoint / {site_display}",
                    title       = title,
                    content     = description,
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
                site_doc_count += 1

            logger.info(f"SharePoint '{site_display}': {len(pages)} site pages")
        except Exception as e:
            logger.warning(f"SharePoint site pages error '{site_display}': {e}")

        # ── 2. Document libraries ─────────────────────────────────────────────
        try:
            libraries = _get_lists(session, site_url)
            logger.info(f"SharePoint '{site_display}': {len(libraries)} document libraries")

            for lib in libraries:
                lib_title    = lib.get("Title", "Documents")
                lib_root_url = lib.get("RootFolder", {}).get("ServerRelativeUrl") or \
                               f"/{site_url.split('/', 3)[-1]}/{lib_title}"

                logger.info(f"SharePoint: crawling '{lib_title}'...")

                try:
                    items = _get_folder_files(
                        session, site_url, lib_root_url, updated_since
                    )
                except Exception as e:
                    logger.warning(f"SharePoint crawl failed for '{lib_title}': {e}")
                    continue

                logger.info(f"SharePoint '{lib_title}': {len(items)} files to process")

                for item in items[:MAX_FILES_PER_LIBRARY]:
                    name         = item.get("Name", "Untitled")
                    server_url   = item.get("ServerRelativeUrl", "")
                    modified     = _parse_sp_date(item.get("TimeLastModified", ""))
                    author       = (item.get("Author") or {}).get("Title", "")
                    ext          = name.lower().rsplit(".", 1)[-1] if "." in name else ""
                    file_web_url = f"{site_url}{server_url}"

                    # Download and extract
                    try:
                        raw_bytes = _download_file(session, site_url, server_url)
                        content   = extract_text(raw_bytes, name) if raw_bytes else ""
                    except Exception as e:
                        logger.warning(f"SharePoint extraction failed '{name}': {e}")
                        content = ""

                    if not content:
                        content = f"{name} {lib_title}".strip()

                    # Build folder path for context
                    folder_path = "/".join(server_url.split("/")[:-1]) if "/" in server_url else ""

                    doc = Document(
                        external_id = server_url or name,
                        source_type = SourceType.SHAREPOINT,
                        source      = f"SharePoint / {site_display} / {lib_title}",
                        title       = name,
                        content     = content,
                        url         = file_web_url,
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
                            "folder_path":  folder_path,
                            "size_bytes":   int(item.get("Length") or 0),
                        },
                        updated_at  = modified,
                    )
                    all_documents.append(doc)
                    site_doc_count += 1

                    if site_doc_count % 50 == 0:
                        logger.info(f"SharePoint '{site_display}': {site_doc_count} docs processed...")

        except Exception as e:
            logger.error(f"SharePoint libraries error '{site_display}': {e}")

        logger.info(f"SharePoint '{site_display}': done — {site_doc_count} total documents")

    logger.info(f"SharePoint: TOTAL {len(all_documents)} documents across all sites")
    return all_documents
