"""
SharePoint Connector — Playwright Edition
──────────────────────────────────────────
Uses Microsoft Edge with your existing logged-in profile.
Bypasses Zscaler/corporate proxy completely — Edge IS the browser,
so all org network policies are satisfied automatically.

Handles both URL types:
  /sites/xxx   — SharePoint sites (SitePages + document libraries)
  /teams/xxx   — Teams-connected sites (document libraries focus)

Per site, crawls:
  1. SitePages  — all .aspx wiki pages, extracts text/tables/content
  2. Documents  — all document libraries, downloads + extracts files
                  (.docx .pptx .xlsx .pdf .txt .md .csv)

Sites config: sharepoint_sites.txt (one URL per line) — easier than
comma-separating 10+ URLs in .env.

Setup (one time):
  pip install playwright
  playwright install msedge
"""

import os
import re
import json
import asyncio
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from config import get_settings
from models import Document, SourceType
from utils.file_extractor import extract_text, SUPPORTED_EXTENSIONS, MAX_FILE_SIZE_MB

logger    = logging.getLogger(__name__)
settings  = get_settings()

# Edge user data dir — reuses your existing logged-in session
EDGE_USER_DATA = os.path.expandvars(
    r"%LOCALAPPDATA%\Microsoft\Edge\User Data"
)
EDGE_PROFILE   = "Default"

# Playwright timeouts
NAV_TIMEOUT    = 60_000   # 60s page navigation
WAIT_TIMEOUT   = 15_000   # 15s element wait

MAX_PAGES_PER_SITE  = 200
MAX_FILES_PER_SITE  = 500
MAX_CHARS           = 50_000


# ── Site list ─────────────────────────────────────────────────────────────────

def _load_site_urls() -> list[str]:
    """
    Load SharePoint site URLs from:
    1. sharepoint_sites.txt  (one URL per line, preferred for 10+ sites)
    2. SHAREPOINT_SITE_URLS  in .env (comma-separated, fallback)
    """
    # Look for sites file next to .env
    sites_file = Path(__file__).parent.parent.parent / "sharepoint_sites.txt"
    if not sites_file.exists():
        sites_file = Path(__file__).parent.parent / "sharepoint_sites.txt"

    if sites_file.exists():
        lines = sites_file.read_text(encoding="utf-8").splitlines()
        urls  = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
        if urls:
            logger.info(f"SharePoint: loaded {len(urls)} sites from sharepoint_sites.txt")
            return urls

    # Fallback to .env
    return settings.sharepoint_site_url_list


# ── Edge browser launch ───────────────────────────────────────────────────────

def _get_edge_executable() -> str:
    """Find Edge executable on Windows."""
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""   # Playwright will try to find it


async def _launch_browser(playwright):
    """
    Launch Edge reusing your existing profile so you're already logged in.
    Falls back to a fresh context if profile is locked (Edge already open).
    """
    edge_exe = _get_edge_executable()

    try:
        # Try persistent context (reuses login session)
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir  = EDGE_USER_DATA,
            channel        = "msedge",
            executable_path= edge_exe or None,
            headless       = True,
            args           = [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                f"--profile-directory={EDGE_PROFILE}",
            ],
            accept_downloads = True,
        )
        logger.info("SharePoint: Edge launched with existing profile (logged-in session)")
        return context, None   # context, browser

    except Exception as e:
        logger.warning(f"Could not use Edge profile ({e}) — trying fresh Edge context")
        browser = await playwright.chromium.launch(
            channel         = "msedge",
            executable_path = edge_exe or None,
            headless        = True,
        )
        context = await browser.new_context(accept_downloads=True)
        return context, browser


# ── Text extraction from page HTML ────────────────────────────────────────────

def _extract_page_text(html: str, title: str = "") -> str:
    """
    Extract meaningful text from SharePoint page HTML.
    Removes nav, headers, footers, scripts, styles.
    Preserves main content, tables, list items.
    """
    # Remove script, style, nav, header, footer blocks
    for tag in ["script", "style", "nav", "header", "footer",
                "aside", "noscript", "svg"]:
        html = re.sub(
            rf"<{tag}[^>]*>.*?</{tag}>", " ", html,
            flags=re.DOTALL | re.IGNORECASE
        )

    # Convert table cells to readable format
    html = re.sub(r"<td[^>]*>", " | ", html, flags=re.IGNORECASE)
    html = re.sub(r"<tr[^>]*>", "\n", html, flags=re.IGNORECASE)

    # Convert list items
    html = re.sub(r"<li[^>]*>", "\n• ", html, flags=re.IGNORECASE)

    # Headings → add newlines
    html = re.sub(r"<h[1-6][^>]*>", "\n\n", html, flags=re.IGNORECASE)

    # Paragraphs and divs → newlines
    html = re.sub(r"<(p|div|br)[^>]*>", "\n", html, flags=re.IGNORECASE)

    # Strip remaining tags
    html = re.sub(r"<[^>]+>", " ", html)

    # Decode entities
    html = re.sub(r"&nbsp;",  " ", html)
    html = re.sub(r"&amp;",   "&", html)
    html = re.sub(r"&lt;",    "<", html)
    html = re.sub(r"&gt;",    ">", html)
    html = re.sub(r"&#\d+;",  " ", html)
    html = re.sub(r"&[a-z]+;", " ", html)

    # Clean up whitespace
    lines = [l.strip() for l in html.splitlines()]
    lines = [l for l in lines if len(l) > 2]   # drop very short lines
    text  = "\n".join(lines)
    text  = re.sub(r"\n{3,}", "\n\n", text)

    return text[:MAX_CHARS]


# ── Site pages crawler ────────────────────────────────────────────────────────

async def _crawl_site_pages(
    context,
    site_url: str,
    site_display: str,
    updated_since: datetime | None,
) -> list[Document]:
    """Crawl all SitePages for a SharePoint site."""
    documents = []
    page      = await context.new_page()

    try:
        # Navigate to SitePages library via REST to get page list
        api_url = f"{site_url}/_api/web/lists/getbytitle('Site Pages')/items?$select=Title,FileRef,Modified,AuthorId,EncodedAbsUrl&$top=500&$orderby=Modified desc"

        await page.goto(api_url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        content = await page.content()

        # Extract page references from REST response
        page_refs = re.findall(r'"FileRef"\s*:\s*"([^"]+\.aspx)"', content)
        titles    = re.findall(r'"Title"\s*:\s*"([^"]+)"', content)
        modifieds = re.findall(r'"Modified"\s*:\s*"([^"]+)"', content)
        abs_urls  = re.findall(r'"EncodedAbsUrl"\s*:\s*"([^"]+)"', content)

        if not page_refs:
            # Fallback — navigate to SitePages library directly
            await page.goto(f"{site_url}/SitePages", timeout=NAV_TIMEOUT, wait_until="networkidle")
            page_refs = await page.eval_on_selector_all(
                "a[href*='.aspx']",
                "els => els.map(e => e.getAttribute('href'))"
            )
            page_refs = list(set(
                href for href in page_refs
                if href and "SitePages" in href and not href.endswith("Forms")
            ))

        logger.info(f"SharePoint '{site_display}': found {len(page_refs)} site pages")

        for i, file_ref in enumerate(page_refs[:MAX_PAGES_PER_SITE]):
            # Build full URL
            if file_ref.startswith("http"):
                full_url = file_ref
            elif file_ref.startswith("/"):
                base = "/".join(site_url.split("/")[:3])
                full_url = f"{base}{file_ref}"
            else:
                full_url = f"{site_url}/{file_ref}"

            # Check modified date for incremental sync
            modified = None
            if i < len(modifieds):
                try:
                    modified = datetime.fromisoformat(
                        modifieds[i].replace("Z", "+00:00")
                    )
                    if updated_since and modified <= updated_since:
                        continue
                except Exception:
                    pass

            title = titles[i] if i < len(titles) else file_ref.split("/")[-1].replace(".aspx", "")

            try:
                await page.goto(full_url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)   # let dynamic content load

                html    = await page.content()
                text    = _extract_page_text(html, title)
                author  = ""

                # Try to get author from page meta
                try:
                    author = await page.eval_on_selector(
                        "meta[name='author']", "el => el.content"
                    )
                except Exception:
                    pass

                if not text or len(text) < 50:
                    logger.debug(f"SharePoint: skipping low-content page: {title}")
                    continue

                doc = Document(
                    external_id = full_url,
                    source_type = SourceType.SHAREPOINT,
                    source      = f"SharePoint / {site_display}",
                    title       = title,
                    content     = text,
                    url         = full_url,
                    author      = author or None,
                    tags        = ["sharepoint", "page", site_display.lower()],
                    metadata    = {
                        "content_type": "page",
                        "site":         site_display,
                        "file_ref":     file_ref,
                    },
                    updated_at  = modified,
                )
                documents.append(doc)
                logger.info(f"SharePoint pages [{i+1}/{min(len(page_refs), MAX_PAGES_PER_SITE)}]: {title}")

            except Exception as e:
                logger.warning(f"SharePoint: failed to load page '{title}': {e}")
                continue

    except Exception as e:
        logger.error(f"SharePoint site pages error for '{site_display}': {e}")
    finally:
        await page.close()

    return documents


# ── Document library crawler ──────────────────────────────────────────────────

async def _get_library_file_list(
    context,
    site_url: str,
    updated_since: datetime | None,
) -> list[dict]:
    """
    Get list of all files in all document libraries via SharePoint REST API.
    Using browser context so Zscaler passes it through.
    """
    page  = await context.new_page()
    files = []

    try:
        # Get all document libraries
        libs_url = f"{site_url}/_api/web/lists?$filter=BaseTemplate eq 101 and Hidden eq false&$select=Title,RootFolder/ServerRelativeUrl&$expand=RootFolder"
        await page.goto(libs_url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        content = await page.content()

        # Parse library root folders from JSON response
        lib_roots = re.findall(r'"ServerRelativeUrl"\s*:\s*"([^"]+)"', content)
        lib_titles = re.findall(r'"Title"\s*:\s*"([^"]+)"', content)

        logger.info(f"SharePoint: found {len(lib_roots)} libraries")

        for lib_idx, root_url in enumerate(lib_roots):
            lib_title = lib_titles[lib_idx] if lib_idx < len(lib_titles) else "Documents"

            # Skip system libraries
            if any(skip in lib_title.lower() for skip in
                   ["style library", "site assets", "site collection", "form templates"]):
                continue

            # Get files recursively via REST
            await _collect_files_from_folder(
                page, site_url, root_url, lib_title, updated_since, files, depth=0
            )

    except Exception as e:
        logger.error(f"SharePoint library list error: {e}")
    finally:
        await page.close()

    return files


async def _collect_files_from_folder(
    page,
    site_url: str,
    folder_url: str,
    lib_title: str,
    updated_since: datetime | None,
    files: list,
    depth: int,
):
    """Recursively collect file metadata from a folder."""
    if depth > 6 or len(files) >= MAX_FILES_PER_SITE:
        return

    encoded = folder_url.replace("'", "''")
    api_url = (
        f"{site_url}/_api/web/GetFolderByServerRelativeUrl('{encoded}')"
        f"/Files?$select=Name,ServerRelativeUrl,TimeLastModified,Length"
        f"&$top=500"
    )

    try:
        await page.goto(api_url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        content = await page.content()

        names     = re.findall(r'"Name"\s*:\s*"([^"]+)"', content)
        srv_urls  = re.findall(r'"ServerRelativeUrl"\s*:\s*"([^"]+)"', content)
        modifieds = re.findall(r'"TimeLastModified"\s*:\s*"([^"]+)"', content)
        lengths   = re.findall(r'"Length"\s*:\s*"(\d+)"', content)

        for i, name in enumerate(names):
            ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            size_bytes = int(lengths[i]) if i < len(lengths) else 0
            size_mb    = size_bytes / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                continue

            modified = None
            if i < len(modifieds):
                try:
                    modified = datetime.fromisoformat(
                        modifieds[i].replace("Z", "+00:00")
                    )
                    if updated_since and modified <= updated_since:
                        continue
                except Exception:
                    pass

            srv_url = srv_urls[i] if i < len(srv_urls) else ""
            files.append({
                "name":       name,
                "server_url": srv_url,
                "library":    lib_title,
                "modified":   modified,
                "size_bytes": size_bytes,
                "ext":        ext,
            })

    except Exception as e:
        logger.warning(f"SharePoint folder list error ({folder_url}): {e}")

    # Recurse into subfolders
    try:
        sub_url = (
            f"{site_url}/_api/web/GetFolderByServerRelativeUrl('{encoded}')"
            f"/Folders?$select=Name,ServerRelativeUrl&$filter=Name ne 'Forms'"
        )
        await page.goto(sub_url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        sub_content = await page.content()
        sub_names   = re.findall(r'"Name"\s*:\s*"([^"]+)"', sub_content)
        sub_urls    = re.findall(r'"ServerRelativeUrl"\s*:\s*"([^"]+)"', sub_content)

        for j, sub_name in enumerate(sub_names):
            if sub_name.startswith(("_", ".")):
                continue
            if j < len(sub_urls):
                await _collect_files_from_folder(
                    page, site_url, sub_urls[j], lib_title,
                    updated_since, files, depth + 1
                )
    except Exception:
        pass


async def _download_and_extract_file(
    context,
    site_url: str,
    file_info: dict,
) -> str:
    """Download a file via browser and extract its text."""
    server_url = file_info["server_url"]
    name       = file_info["name"]

    if not server_url:
        return ""

    base     = "/".join(site_url.split("/")[:3])
    file_url = f"{base}{server_url}"

    page = await context.new_page()
    try:
        # Use download interception for file types
        async with page.expect_download(timeout=30_000) as dl_info:
            await page.goto(file_url, timeout=NAV_TIMEOUT)

        download = await dl_info.value
        with tempfile.NamedTemporaryFile(
            suffix=f".{file_info['ext']}", delete=False
        ) as tmp:
            tmp_path = tmp.name

        await download.save_as(tmp_path)

        with open(tmp_path, "rb") as f:
            raw = f.read()

        os.unlink(tmp_path)
        return extract_text(raw, name)

    except Exception:
        # Fallback — try direct fetch via JS
        try:
            result = await page.evaluate(
                """async (url) => {
                    const r = await fetch(url, {credentials: 'include'});
                    if (!r.ok) return '';
                    const buf = await r.arrayBuffer();
                    return Array.from(new Uint8Array(buf));
                }""",
                file_url
            )
            if result:
                raw = bytes(result)
                return extract_text(raw, name)
        except Exception as e:
            logger.warning(f"SharePoint: could not download '{name}': {e}")

        return ""
    finally:
        await page.close()


# ── Main entry point ──────────────────────────────────────────────────────────

async def fetch_documents(updated_since: datetime | None = None) -> list[Document]:
    """
    Crawl all SharePoint sites using Edge browser (bypasses Zscaler).
    Reads site list from sharepoint_sites.txt or SHAREPOINT_SITE_URLS env var.
    """
    from playwright.async_api import async_playwright

    site_urls = _load_site_urls()
    if not site_urls:
        logger.warning(
            "No SharePoint URLs configured. "
            "Create sharepoint_sites.txt in project root with one URL per line."
        )
        return []

    mode = "incremental" if updated_since else "full"
    logger.info(f"SharePoint: {mode} sync across {len(site_urls)} site(s) via Edge browser")

    all_documents: list[Document] = []

    async with async_playwright() as pw:
        context, browser = await _launch_browser(pw)

        try:
            for site_url in site_urls:
                site_url     = site_url.strip().rstrip("/")
                site_display = site_url.rstrip("/").split("/")[-1]
                is_teams     = "/teams/" in site_url.lower()

                logger.info(f"SharePoint: processing '{site_display}' ({'Teams' if is_teams else 'Site'})")
                site_count = 0

                # ── Site pages (skip for pure Teams document sites) ───────────
                if not is_teams:
                    try:
                        pages = await _crawl_site_pages(
                            context, site_url, site_display, updated_since
                        )
                        all_documents.extend(pages)
                        site_count += len(pages)
                        logger.info(f"SharePoint '{site_display}': {len(pages)} pages crawled")
                    except Exception as e:
                        logger.error(f"SharePoint pages error '{site_display}': {e}")

                # ── Document libraries ────────────────────────────────────────
                try:
                    file_list = await _get_library_file_list(
                        context, site_url, updated_since
                    )
                    logger.info(f"SharePoint '{site_display}': {len(file_list)} files to download")

                    for file_info in file_list:
                        name    = file_info["name"]
                        content = await _download_and_extract_file(
                            context, site_url, file_info
                        )

                        if not content:
                            content = f"{name} {file_info['library']}"

                        folder = "/".join(
                            file_info["server_url"].split("/")[:-1]
                        ) if file_info["server_url"] else ""

                        base     = "/".join(site_url.split("/")[:3])
                        file_url = f"{base}{file_info['server_url']}"

                        doc = Document(
                            external_id = file_info["server_url"] or name,
                            source_type = SourceType.SHAREPOINT,
                            source      = f"SharePoint / {site_display} / {file_info['library']}",
                            title       = name,
                            content     = content,
                            url         = file_url,
                            author      = None,
                            tags        = [
                                "sharepoint",
                                file_info["ext"],
                                file_info["library"].lower().replace(" ", "_"),
                                site_display.lower(),
                            ],
                            metadata    = {
                                "content_type": file_info["ext"],
                                "library":      file_info["library"],
                                "site":         site_display,
                                "folder_path":  folder,
                                "size_bytes":   file_info["size_bytes"],
                            },
                            updated_at  = file_info["modified"],
                        )
                        all_documents.append(doc)
                        site_count += 1

                        if site_count % 25 == 0:
                            logger.info(
                                f"SharePoint '{site_display}': {site_count} docs so far..."
                            )

                except Exception as e:
                    logger.error(f"SharePoint files error '{site_display}': {e}")

                logger.info(f"SharePoint '{site_display}': done — {site_count} total")

        finally:
            await context.close()
            if browser:
                await browser.close()

    logger.info(f"SharePoint: TOTAL {len(all_documents)} documents")
    return all_documents
