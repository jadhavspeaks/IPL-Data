"""
Search Route
─────────────
GET /api/search?q=...

Pipeline:
1. MongoDB $text pre-filter     — fast candidate retrieval
2. Entity lookup                — direct match on ticket/change refs
3. BM25 re-ranking              — industry-standard relevance scoring
4. SME ranking                  — who knows most about this topic
5. Best answer extraction       — top relevant sentence from best doc
6. Cross-linking                — related docs via shared entities
"""

import re
import logging
from fastapi import APIRouter, Query
from database import get_db
from config import get_settings
from utils.bm25 import rerank_bm25
from utils.extractor import extract_entities
from utils.sme_ranker import rank_smes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["search"])
settings = get_settings()

CANDIDATE_POOL = 200


def _extract_best_answer(query: str, documents: list[dict], max_chars: int = 500) -> str:
    """
    Extract the single most relevant passage from the top documents.
    Scores each sentence by how many query words it contains.
    Pure keyword matching — no AI.
    """
    if not documents:
        return ""

    query_words = set(re.findall(r'\b[a-z]{3,}\b', query.lower()))
    if not query_words:
        return documents[0].get("content", "")[:max_chars]

    best_sentence = ""
    best_score = -1

    for doc in documents[:5]:   # look in top 5 docs only
        content = doc.get("content", "")
        if not content:
            continue
        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', content)
        for sentence in sentences:
            if len(sentence) < 30 or len(sentence) > 600:
                continue
            words = set(re.findall(r'\b[a-z]{3,}\b', sentence.lower()))
            score = len(query_words & words)   # how many query words appear
            if score > best_score:
                best_score = score
                best_sentence = sentence

    if best_sentence:
        return best_sentence[:max_chars]

    # Fallback — first 500 chars of top doc
    return documents[0].get("content", "")[:max_chars]


async def _find_related(db, doc: dict) -> list[dict]:
    """Find docs sharing the same Jira tickets or change numbers."""
    entities = doc.get("entities") or {}
    tickets  = entities.get("jira_tickets", [])
    changes  = entities.get("change_numbers", [])

    if not tickets and not changes:
        return []

    query_parts = []
    if tickets:
        query_parts.append({"entities.jira_tickets": {"$in": tickets}})
    if changes:
        query_parts.append({"entities.change_numbers": {"$in": changes}})

    cursor = db.documents.find(
        {"$or": query_parts, "external_id": {"$ne": doc.get("external_id")}},
        {"title": 1, "url": 1, "source": 1, "source_type": 1,
         "author": 1, "metadata": 1, "entities": 1, "updated_at": 1}
    ).limit(5)

    related = []
    async for r in cursor:
        related.append({
            "id":          str(r["_id"]),
            "title":       r.get("title", ""),
            "url":         r.get("url", ""),
            "source":      r.get("source", ""),
            "source_type": r.get("source_type", ""),
            "author":      r.get("author"),
            "metadata":    r.get("metadata", {}),
            "entities":    r.get("entities", {}),
        })
    return related


def _doc_to_out(doc: dict) -> dict:
    content = doc.get("content", "")
    return {
        "id":              str(doc["_id"]),
        "external_id":     doc.get("external_id", ""),
        "source_type":     doc.get("source_type", ""),
        "source":          doc.get("source", ""),
        "title":           doc.get("title", ""),
        "content_preview": content[:400] + ("…" if len(content) > 400 else ""),
        "url":             doc.get("url", ""),
        "author":          doc.get("author"),
        "tags":            doc.get("tags", []),
        "metadata":        doc.get("metadata", {}),
        "entities":        doc.get("entities", {}),
        "ingested_at":     doc.get("ingested_at"),
        "updated_at":      doc.get("updated_at"),
        "bm25_score":      doc.get("bm25_score"),
        "related_docs":    doc.get("related_docs", []),
    }


@router.get("")
async def search(
    q:           str        = Query(..., min_length=1),
    source_type: str | None = Query(None),
    page:        int        = Query(1, ge=1),
    page_size:   int | None = Query(None),
):
    db        = get_db()
    page_size = page_size or settings.max_results_per_page
    skip      = (page - 1) * page_size

    # ── Step 1: Entity lookup (ticket/change refs in query) ───────────────────
    query_entities = extract_entities(q)
    entity_docs    = []
    entity_ids     = set()

    if query_entities.get("jira_tickets") or query_entities.get("change_numbers"):
        parts = []
        if query_entities.get("jira_tickets"):
            parts.append({"entities.jira_tickets": {"$in": query_entities["jira_tickets"]}})
        if query_entities.get("change_numbers"):
            parts.append({"entities.change_numbers": {"$in": query_entities["change_numbers"]}})

        cur = db.documents.find(
            {"$or": parts},
            {"title":1,"content":1,"source":1,"source_type":1,"url":1,
             "author":1,"tags":1,"metadata":1,"entities":1,
             "ingested_at":1,"updated_at":1,"external_id":1}
        ).limit(20)
        entity_docs = await cur.to_list(length=20)
        entity_ids  = {str(d["_id"]) for d in entity_docs}

    # ── Step 2: MongoDB full-text search ─────────────────────────────────────
    match_filter: dict = {"$text": {"$search": q}}
    if source_type:
        match_filter["source_type"] = source_type

    cur = db.documents.find(
        match_filter,
        {"title":1,"content":1,"source":1,"source_type":1,"url":1,
         "author":1,"tags":1,"metadata":1,"entities":1,
         "ingested_at":1,"updated_at":1,"external_id":1}
    ).limit(CANDIDATE_POOL)
    text_candidates = await cur.to_list(length=CANDIDATE_POOL)

    # Merge — entity docs first, deduplicated
    all_candidates = list(entity_docs)
    for doc in text_candidates:
        if str(doc["_id"]) not in entity_ids:
            all_candidates.append(doc)

    if not all_candidates:
        return {
            "query": q, "total": 0, "results": [],
            "page": page, "page_size": page_size,
            "smes": [], "best_answer": "",
        }

    # ── Step 3: BM25 re-ranking ───────────────────────────────────────────────
    ranked = rerank_bm25(q, all_candidates)
    total  = len(ranked)

    # ── Step 4: SME ranking (across ALL matched docs, not just current page) ──
    smes = rank_smes(ranked)

    # ── Step 5: Best answer (from top 5 ranked docs) ─────────────────────────
    best_answer = _extract_best_answer(q, ranked[:5])

    # ── Step 6: Paginate + cross-link ────────────────────────────────────────
    page_docs = ranked[skip: skip + page_size]
    results   = []
    for doc in page_docs:
        doc["related_docs"] = await _find_related(db, doc)
        results.append(_doc_to_out(doc))

    return {
        "query":       q,
        "total":       total,
        "results":     results,
        "page":        page,
        "page_size":   page_size,
        "smes":        smes,
        "best_answer": best_answer,
    }
