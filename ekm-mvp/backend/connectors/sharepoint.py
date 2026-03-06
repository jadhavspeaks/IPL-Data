"""
SharePoint Connector — Modern Auth via Office365 REST Client
─────────────────────────────────────────────────────────────
Uses office365-rest-python-client which:
  1. Auto-discovers Citi's ADFS endpoint from the SharePoint URL
  2. Authenticates with username + password directly to ADFS
  3. Gets an OAuth bearer token (no login.microsoftonline.com needed)
  4. Uses token for all SharePoint REST API calls

This is the correct approach for SharePoint Online with federated
modern auth (ADFS) on a corporate network.

Required: pip install Office365-REST-Python-Client

Handles both URL types:
  /sites/xxx  — SitePages + document libraries
  /teams/xxx  — document libraries

Sites config: sharepoint_sites.txt in project root (one URL per line)
"""

import os
import re
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from config import get_settings
from models import Document, SourceType
from utils.file_extractor import extract_text, SUPPORTED_EXTENSIONS, MAX_FILE_SIZE_MB

logger   = logging.getLogger(__name__)
settings = get_settings()

MAX_FILES_PER_LIB  = 500
MAX_PAGES_PER_SITE = 300


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


# ── Auth ──────────────────────────────────────────────────────────────────────

def _make_ctx(site_url: str):
    """
    Create an authenticated ClientContext for a SharePoint site.
    Uses UserCredential — authenticates via Citi's ADFS automatically.
    """
    from office365.runtime.auth.user_credential import UserCredential
    from office365.sharepoint.client_context import ClientContext

    username = settings.sharepoint_username
    password = settings.sharepoint_password

    if not username or not password:
        raise ValueError(
            "SharePoint requires SHAREPOINT_USERNAME and SHAREPOINT_PASSWORD in .env\n"
            "Format: firstname.lastname@citi.com"
        )

    credentials = UserCredential(username, password)
    ctx = ClientContext(site_url).with_credentials(credentials)

    # Test connection
    web = ctx.web
    ctx.load(web, ["Title"])
    ctx.execute_query()

    logger.info(f"SharePoint: authenticated to '{web.properties.get('Title', site_url)}'")
    return ctx


# ── HTML to text ──────────────────────────────────────────────────────────────

def _html_to_text(html: str) -> str:
    for tag in ["script", "style", "nav", "header", "footer", "aside", "noscript"]:
        html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", " ", html,
                      flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<td[^>]*>", " | ", html, flags=re.IGNORECASE)
    html = re.sub(r"<tr[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<li[^>]*>", "\n• ", html, flags=re.IGNORECASE)
    html = re.sub(r"<(p|div|br|h[1-6])[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    for pat, rep in [("&nbsp;"," "),("&amp;","&"),("&lt;","<"),
                     ("&gt;",">"),("&#\\d+;"," "),("&[a-z]+;"," ")]:
        html = re.sub(pat, rep, html)
    lines = [l.strip() for l in html.splitlines() if len(l.strip()) > 3]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))[:50_000]


def _parse_date(val) -> datetime | None:
    if not val:
        return None
    try:
        if isinstance(val, datetime):
            return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
        s = str(val)
        if s.startswith("/Date("):
            return datetime.fromtimestamp(int(s[6:-2]) / 1000, tz=timezone.utc)
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


# ── Site pages ────────────────────────────────────────────────────────────────

def _crawl_site_pages(
    ctx,
    site_url: str,
    site_display: str,
    updated_since: datetime | None,
) -> list[Document]:
    from office365.sharepoint.listitems.caml.query import CamlQuery

    documents = []
    try:
        pages_list = ctx.web.lists.get_by_title("Site Pages")
        items = pages_list.items.select([
            "Title", "FileRef", "Modified",
            "EncodedAbsUrl", "AuthorId",
        ]).top(MAX_PAGES_PER_SITE).get().execute_query()

        logger.info(f"SharePoint '{site_display}': {len(items)} site pages")

        for item in items:
            props    = item.properties
            title    = props.get("Title") or "Untitled Page"
            file_ref = props.get("FileRef", "")
            abs_url  = props.get("EncodedAbsUrl", "")
            modified = _parse_date(props.get("Modified"))

            if updated_since and modified and modified <= updated_since:
                continue

            page_url = abs_url or f"{site_url}{file_ref}"

            # Fetch page HTML content
            try:
                import requests as req
                import urllib3
                urllib3.disable_warnings()
                # Use the same auth session from ctx
                resp = req.get(
                    page_url,
                    headers={"Authorization": f"Bearer {ctx._auth_context._client._access_token}"},
                    verify=False, timeout=30
                )
                content = _html_to_text(resp.text) if resp.status_code == 200 else title
            except Exception:
                content = title

            doc = Document(
                external_id = file_ref or abs_url,
                source_type = SourceType.SHAREPOINT,
                source      = f"SharePoint / {site_display}",
                title       = title,
                content     = content,
                url         = page_url,
                author      = None,
                tags        = ["sharepoint", "page", site_display.lower()],
                metadata    = {"content_type": "page", "site": site_display},
                updated_at  = modified,
            )
            documents.append(doc)

    except Exception as e:
        logger.warning(f"SharePoint site pages error '{site_display}': {e}")

    return documents


# ── Document libraries ────────────────────────────────────────────────────────

def _crawl_libraries(
    ctx,
    site_url: str,
    site_display: str,
    updated_since: datetime | None,
) -> list[Document]:
    documents = []

    try:
        # Get all document libraries
        lists = ctx.web.lists.filter("BaseTemplate eq 101 and Hidden eq false") \
            .select(["Title", "RootFolder"]) \
            .expand(["RootFolder"]) \
            .get().execute_query()

        skip_libs = {"style library", "site assets", "form templates",
                     "site collection documents", "site pages"}
        libs = [l for l in lists if l.properties.get("Title","").lower() not in skip_libs]

        logger.info(f"SharePoint '{site_display}': {len(libs)} document libraries")

        for lib in libs:
            lib_title  = lib.properties.get("Title", "Documents")
            root_props = lib.properties.get("RootFolder", {})
            root_url   = root_props.get("ServerRelativeUrl", "") if isinstance(root_props, dict) else ""

            if not root_url:
                continue

            logger.info(f"SharePoint: crawling '{lib_title}'...")

            try:
                files = _collect_files(ctx, root_url, updated_since, depth=0)
                logger.info(f"SharePoint '{lib_title}': {len(files)} files")

                for f_props in files[:MAX_FILES_PER_LIB]:
                    name       = f_props.get("Name", "Untitled")
                    server_url = f_props.get("ServerRelativeUrl", "")
                    modified   = _parse_date(f_props.get("TimeLastModified"))
                    ext        = name.lower().rsplit(".", 1)[-1] if "." in name else ""
                    folder     = "/".join(server_url.split("/")[:-1])

                    # Download and extract
                    raw     = _download_file(ctx, server_url)
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
                        author      = None,
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
                            "size_bytes":   int(f_props.get("Length") or 0),
                        },
                        updated_at  = modified,
                    )
                    documents.append(doc)

            except Exception as e:
                logger.warning(f"SharePoint library '{lib_title}' error: {e}")
                continue

    except Exception as e:
        logger.error(f"SharePoint libraries error '{site_display}': {e}")

    return documents


def _collect_files(ctx, folder_url: str, updated_since, depth: int) -> list[dict]:
    """Recursively collect files from a folder."""
    if depth > 8:
        return []

    files = []
    try:
        folder = ctx.web.get_folder_by_server_relative_url(folder_url)
        folder.expand(["Files", "Folders"])
        folder.get().execute_query()

        for f in folder.files:
            props = f.properties
            name  = props.get("Name", "")
            ext   = name.lower().rsplit(".", 1)[-1] if "." in name else ""
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            size_mb = int(props.get("Length") or 0) / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                continue
            modified = _parse_date(props.get("TimeLastModified"))
            if updated_since and modified and modified <= updated_since:
                continue
            files.append(props)

        for sub in folder.folders:
            sub_props = sub.properties
            sub_name  = sub_props.get("Name", "")
            if sub_name.startswith(("_", ".")) or sub_name == "Forms":
                continue
            sub_url = sub_props.get("ServerRelativeUrl", "")
            files.extend(_collect_files(ctx, sub_url, updated_since, depth + 1))

    except Exception as e:
        logger.warning(f"SharePoint folder error '{folder_url}': {e}")

    return files


def _download_file(ctx, server_relative_url: str) -> bytes:
    try:
        buf = []
        file_obj = ctx.web.get_file_by_server_relative_url(server_relative_url)
        file_obj.download(buf).execute_query()
        return buf[0] if buf else b""
    except Exception as e:
        logger.warning(f"SharePoint download failed '{server_relative_url}': {e}")
        return b""


# ── Main ──────────────────────────────────────────────────────────────────────

async def fetch_documents(updated_since: datetime | None = None) -> list[Document]:
    site_urls = _load_site_urls()
    if not site_urls:
        logger.warning(
            "No SharePoint URLs. Create sharepoint_sites.txt with one URL per line."
        )
        return []

    mode = "incremental" if updated_since else "full"
    logger.info(f"SharePoint: {mode} sync — {len(site_urls)} site(s)")

    all_documents: list[Document] = []

    for site_url in site_urls:
        site_url     = site_url.strip().rstrip("/")
        site_display = site_url.split("/")[-1]
        is_teams     = "/teams/" in site_url.lower()

        logger.info(f"SharePoint: connecting to '{site_display}'...")
        try:
            ctx = _make_ctx(site_url)
        except Exception as e:
            logger.error(
                f"SharePoint auth failed for '{site_display}': {e}\n"
                f"  → Check SHAREPOINT_USERNAME and SHAREPOINT_PASSWORD in .env\n"
                f"  → Format: firstname.lastname@citi.com"
            )
            continue

        site_count = 0

        # Site pages (not for Teams sites)
        if not is_teams:
            pages = _crawl_site_pages(ctx, site_url, site_display, updated_since)
            all_documents.extend(pages)
            site_count += len(pages)
            logger.info(f"SharePoint '{site_display}': {len(pages)} pages done")

        # Document libraries
        files = _crawl_libraries(ctx, site_url, site_display, updated_since)
        all_documents.extend(files)
        site_count += len(files)

        logger.info(f"SharePoint '{site_display}': done — {site_count} total")

    logger.info(f"SharePoint: TOTAL {len(all_documents)} documents")
    return all_documents
