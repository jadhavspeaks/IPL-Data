"""
Sync Service
─────────────
Orchestrates incremental syncs with:
  - Incremental pulls (only changed docs since last sync)
  - Entity extraction on every document (tickets, dates, change numbers)
  - Bulk MongoDB writes (10-50x faster than one-by-one)
  - Sync state tracking (last_sync_at per source)
  - Duplicate prevention via unique (source_type, external_id) index
"""

import logging
from datetime import datetime, timezone
from pymongo import UpdateOne
from database import get_db, get_last_sync, set_last_sync
from models import Document, SourceType, SyncStatus
from connectors import sharepoint, confluence, jira, servicenow, github
from utils.extractor import extract_from_document

logger = logging.getLogger(__name__)

CONNECTORS = {
    SourceType.SHAREPOINT: sharepoint.fetch_documents,
    SourceType.CONFLUENCE: confluence.fetch_documents,
    SourceType.JIRA:       jira.fetch_documents,
    SourceType.GITHUB:     github.fetch_documents,
    # SourceType.SERVICENOW: servicenow.fetch_documents,
}

BATCH_SIZE = 200   # docs per bulk_write batch


def _enrich_document(doc: Document) -> dict:
    """Convert Document to dict and inject extracted entities."""
    doc_dict = doc.model_dump()
    doc_dict["ingested_at"] = datetime.now(timezone.utc)

    # Extract structured entities from title + content
    entities = extract_from_document(doc.title, doc.content)
    doc_dict["entities"] = entities

    return doc_dict


async def bulk_upsert(documents: list[Document]) -> tuple[int, int]:
    """
    Bulk upsert documents with entity extraction.
    Uses MongoDB bulk_write — much faster than individual update_one calls.
    Returns (added, updated) counts.
    """
    db = get_db()
    if not documents:
        return 0, 0

    added = updated = 0

    # Process in batches
    for i in range(0, len(documents), BATCH_SIZE):
        batch = documents[i:i + BATCH_SIZE]
        operations = []

        for doc in batch:
            doc_dict = _enrich_document(doc)
            operations.append(
                UpdateOne(
                    # Match key — prevents duplicates
                    {
                        "source_type": doc.source_type,
                        "external_id": doc.external_id,
                    },
                    {"$set": doc_dict},
                    upsert=True,
                )
            )

        if not operations:
            continue

        result = await db.documents.bulk_write(operations, ordered=False)
        added   += result.upserted_count
        updated += result.modified_count

        logger.info(
            f"Bulk write batch {i//BATCH_SIZE + 1}: "
            f"+{result.upserted_count} added, ~{result.modified_count} updated"
        )

    return added, updated


async def run_sync(source_type: SourceType | None = None, force_full: bool = False) -> dict:
    """
    Run incremental sync for one or all sources.

    Args:
        source_type: Specific source to sync, or None for all
        force_full:  If True, ignores last_sync_at and pulls everything
    """
    db = get_db()
    sources_to_sync = [source_type] if source_type else list(CONNECTORS.keys())
    results = {}
    sync_started_at = datetime.now(timezone.utc)

    for src in sources_to_sync:
        log = {
            "source_type": src,
            "status":      SyncStatus.RUNNING,
            "started_at":  datetime.now(timezone.utc),
            "docs_added":    0,
            "docs_updated":  0,
            "docs_skipped":  0,
            "error_message": None,
            "sync_mode":     "full",
        }
        log_result = await db.sync_logs.insert_one(log.copy())
        log_id = log_result.inserted_id

        try:
            # ── Determine sync mode ───────────────────────────────────────────
            last_sync = None if force_full else await get_last_sync(src)
            sync_mode = "full" if last_sync is None else "incremental"
            log["sync_mode"] = sync_mode

            logger.info(
                f"Starting {sync_mode} sync for {src}"
                + (f" (since {last_sync.strftime('%Y-%m-%d %H:%M')})" if last_sync else "")
            )

            # ── Fetch from source ─────────────────────────────────────────────
            fetch_fn = CONNECTORS[src]

            # Connectors that support incremental (Confluence, Jira)
            # Pass updated_since only if they accept it
            import inspect
            sig = inspect.signature(fetch_fn)
            if "updated_since" in sig.parameters:
                documents = await fetch_fn(updated_since=last_sync)
            else:
                documents = await fetch_fn()

            # ── Bulk upsert ───────────────────────────────────────────────────
            added, upd = await bulk_upsert(documents)

            # ── Update sync state ─────────────────────────────────────────────
            await set_last_sync(src, sync_started_at)

            log.update({
                "status":       SyncStatus.SUCCESS,
                "finished_at":  datetime.now(timezone.utc),
                "docs_added":   added,
                "docs_updated": upd,
                "docs_skipped": len(documents) - added - upd,
            })
            results[src] = {
                "status":    "success",
                "mode":      sync_mode,
                "added":     added,
                "updated":   upd,
                "total":     len(documents),
            }
            logger.info(
                f"Sync {src} ({sync_mode}): "
                f"+{added} added, ~{upd} updated, "
                f"{len(documents)-added-upd} unchanged"
            )

        except Exception as e:
            error_msg = str(e)
            log.update({
                "status":        SyncStatus.FAILED,
                "finished_at":   datetime.now(timezone.utc),
                "error_message": error_msg,
            })
            results[src] = {"status": "failed", "error": error_msg}
            logger.error(f"Sync {src} failed: {e}")

        await db.sync_logs.update_one(
            {"_id": log_id},
            {"$set": {
                "status":        log["status"],
                "finished_at":   log.get("finished_at"),
                "docs_added":    log["docs_added"],
                "docs_updated":  log["docs_updated"],
                "docs_skipped":  log["docs_skipped"],
                "error_message": log["error_message"],
                "sync_mode":     log["sync_mode"],
            }},
        )

    return results
