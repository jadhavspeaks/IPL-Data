"""
GET /api/explain/{doc_id}
Returns structured code explanation using 4 intelligence signals.
"""
import logging
from fastapi import APIRouter, HTTPException, Query
from database import get_db
from bson import ObjectId
from utils.code_explainer import explain

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/explain", tags=["explain"])


@router.get("/{doc_id}")
async def explain_document(
    doc_id:  str,
    context: str | None = Query(None),
):
    db = get_db()
    try:
        oid = ObjectId(doc_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid document ID")

    doc = await db.documents.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.get("source_type") != "github":
        raise HTTPException(status_code=400, detail="Explain is only available for GitHub documents")

    result = await explain(db, doc, context)
    return result
