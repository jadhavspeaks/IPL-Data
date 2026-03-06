from fastapi import APIRouter, HTTPException
from database import get_db
from models import SyncRequest, SourceType, DashboardStats, SourceStats, SyncStatus, DocumentOut
from utils.sync_service import run_sync
from bson import ObjectId
from datetime import datetime, timezone
import asyncio

# ─── Sync Router ─────────────────────────────────────────────────────────────
sync_router = APIRouter(prefix="/api/sync", tags=["sync"])

@sync_router.post("")
async def trigger_sync(body: SyncRequest = SyncRequest()):
    """Trigger a sync for one or all sources. Runs in background."""
    source = body.source_type
    # Run sync (for MVP runs synchronously; in production use a task queue)
    results = await run_sync(source)
    return {"message": "Sync complete", "results": results}


@sync_router.get("/logs")
async def get_sync_logs(limit: int = 20):
    """Get recent sync log entries."""
    db = get_db()
    logs = await db.sync_logs.find(
        {}, {"_id": 0}
    ).sort("started_at", -1).limit(limit).to_list(length=limit)
    return logs


# ─── Sources Router ───────────────────────────────────────────────────────────
sources_router = APIRouter(prefix="/api/sources", tags=["sources"])

KNOWN_SOURCES = [
    SourceType.SHAREPOINT,
    SourceType.CONFLUENCE,
    SourceType.JIRA,
    SourceType.GITHUB,
]

@sources_router.get("", response_model=DashboardStats)
async def get_sources():
    """Return stats for all sources including doc counts and sync status."""
    db = get_db()
    total = await db.documents.count_documents({})
    source_stats = []

    for src in KNOWN_SOURCES:
        count = await db.documents.count_documents({"source_type": src})

        # Last sync log for this source
        last_log = await db.sync_logs.find_one(
            {"source_type": src},
            sort=[("started_at", -1)],
        )

        status = SyncStatus.NEVER
        last_sync = None
        error_msg = None

        if last_log:
            status = last_log.get("status", SyncStatus.NEVER)
            last_sync = last_log.get("finished_at") or last_log.get("started_at")
            error_msg = last_log.get("error_message")

        source_stats.append(SourceStats(
            source_type=src,
            doc_count=count,
            last_sync=last_sync,
            sync_status=status,
            error_message=error_msg,
        ))

    # Recent sync activity
    recent_logs = await db.sync_logs.find(
        {}, {"_id": 0}
    ).sort("started_at", -1).limit(10).to_list(length=10)

    return DashboardStats(
        total_documents=total,
        sources=source_stats,
        recent_syncs=recent_logs,
    )


# ─── Documents Router ─────────────────────────────────────────────────────────
documents_router = APIRouter(prefix="/api/documents", tags=["documents"])

def _doc_out(doc: dict) -> dict:
    content = doc.get("content", "")
    return {
        "id": str(doc["_id"]),
        "external_id": doc.get("external_id", ""),
        "source_type": doc.get("source_type", ""),
        "source": doc.get("source", ""),
        "title": doc.get("title", ""),
        "content_preview": content[:300] + ("…" if len(content) > 300 else ""),
        "url": doc.get("url", ""),
        "author": doc.get("author"),
        "tags": doc.get("tags", []),
        "metadata": doc.get("metadata", {}),
        "ingested_at": doc.get("ingested_at"),
        "updated_at": doc.get("updated_at"),
    }


@documents_router.get("")
async def list_documents(
    source_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
):
    db = get_db()
    skip = (page - 1) * page_size
    query = {}
    if source_type:
        query["source_type"] = source_type

    total = await db.documents.count_documents(query)
    docs = await db.documents.find(query).sort(
        "ingested_at", -1
    ).skip(skip).limit(page_size).to_list(length=page_size)

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "results": [_doc_out(d) for d in docs],
    }


@documents_router.get("/{doc_id}")
async def get_document(doc_id: str):
    db = get_db()
    try:
        oid = ObjectId(doc_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid document ID")

    doc = await db.documents.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    result = _doc_out(doc)
    result["content"] = doc.get("content", "")   # full content for detail view
    return result
