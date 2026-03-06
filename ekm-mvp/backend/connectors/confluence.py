"""
Confluence Connector — with timeout + progress logging
"""

import logging
import re
import urllib3
from datetime import datetime, timezone
from atlassian import Confluence
from config import get_settings
from models import Document, SourceType

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)
settings = get_settings()

# Max pages per space before we stop (safety cap)
MAX_PAGES_PER_SPACE = 500
# Request timeout in seconds
REQUEST_TIMEOUT = 30


def _html_to_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"&nbsp;",  " ", text)
    text = re.sub(r"&amp;",   "&", text)
    text = re.sub(r"&lt;",    "<", text)
    text = re.sub(r"&gt;",    ">", text)
    text = re.sub(r"\s+",     " ", text).strip()
    return text


def _get_client() -> Confluence | None:
    if not all([settings.confluence_url, settings.confluence_api_token]):
        logger.warning("Confluence credentials not configured — skipping")
        return None
    return Confluence(
        url=settings.confluence_url,
        token=settings.confluence_api_token,
        cloud=False,
        verify_ssl=False,
        timeout=REQUEST_TIMEOUT,
    )


async def fetch_documents(updated_since: datetime | None = None) -> list[Document]:
    client = _get_client()
    if not client:
        return []

    spaces = settings.confluence_space_list
    if not spaces:
        try:
            all_spaces = client.get_all_spaces(limit=200)
            spaces = [s["key"] for s in all_spaces.get("results", [])]
            logger.info(f"Confluence: discovered {len(spaces)} spaces")
        except Exception as e:
            logger.error(f"Could not list Confluence spaces: {e}")
            return []

    mode = "incremental" if updated_since else "full"
    since_str = updated_since.strftime("%Y-%m-%d") if updated_since else None
    logger.info(f"Confluence: {mode} sync across {len(spaces)} spaces")

    documents = []

    for space_idx, space_key in enumerate(spaces):
        # Permission check
        try:
            if not client.get_space(space_key):
                logger.warning(f"Confluence [{space_idx+1}/{len(spaces)}]: no access to {space_key} — skipping")
                continue
        except Exception:
            logger.warning(f"Confluence [{space_idx+1}/{len(spaces)}]: no access to {space_key} — skipping")
            continue

        try:
            start = 0
            limit = 50
            space_count = 0

            while space_count < MAX_PAGES_PER_SPACE:
                try:
                    if updated_since:
                        cql = (
                            f'space = "{space_key}" AND type = "page" '
                            f'AND lastModified >= "{since_str}" '
                            f'ORDER BY lastModified DESC'
                        )
                        result = client.cql(cql, start=start, limit=limit,
                                           expand="body.storage,version,ancestors,metadata.labels")
                        pages = result.get("results", []) if result else []
                    else:
                        pages = client.get_all_pages_from_space(
                            space=space_key, start=start, limit=limit,
                            expand="body.storage,version,ancestors,metadata.labels",
                        ) or []
                except Exception as e:
                    logger.warning(f"Confluence: batch fetch failed for {space_key} at start={start}: {e}")
                    break

                if not pages:
                    break

                for page in pages:
                    try:
                        body_html = (page.get("body") or {}).get("storage", {}).get("value", "")
                        plain_text = _html_to_text(body_html)
                        labels = (page.get("metadata") or {}).get("labels", {}).get("results", [])
                        tags = ["confluence", space_key.lower()] + [l["name"] for l in labels]
                        version_info = page.get("version") or {}
                        author_info = version_info.get("by") or {}

                        updated_str = version_info.get("when")
                        updated_at = None
                        if updated_str:
                            try:
                                updated_at = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                            except Exception:
                                pass

                        doc = Document(
                            external_id=str(page["id"]),
                            source_type=SourceType.CONFLUENCE,
                            source=f"Confluence / {space_key}",
                            title=page.get("title", "Untitled"),
                            content=plain_text,
                            url=f"{settings.confluence_url.rstrip('/')}/pages/viewpage.action?pageId={page['id']}",
                            author=author_info.get("displayName"),
                            tags=tags,
                            metadata={
                                "space_key": space_key,
                                "version":   version_info.get("number"),
                                "status":    page.get("status"),
                                "ancestors": [a.get("title") for a in page.get("ancestors", [])],
                            },
                            updated_at=updated_at,
                        )
                        documents.append(doc)
                        space_count += 1
                    except Exception as e:
                        logger.warning(f"Confluence: skipping page {page.get('id')}: {e}")
                        continue

                logger.info(f"Confluence [{space_idx+1}/{len(spaces)}] {space_key}: {space_count} pages so far...")

                if len(pages) < limit:
                    break
                start += limit

            logger.info(f"Confluence {space_key}: done — {space_count} pages")

        except Exception as e:
            logger.warning(f"Confluence: skipping space {space_key} — {e}")
            continue

    logger.info(f"Confluence: TOTAL {len(documents)} documents")
    return documents
