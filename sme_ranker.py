"""
SME Ranker
───────────
Ranks people by subject matter expertise for a given set of matching documents.
Pure Python — no AI, no external libraries.

Scoring per person:
  +3  authored a Confluence page in results
  +3  reporter on a matching Jira issue
  +2  assignee on a matching Jira issue
  +1  per comment they made on matching Jira issues
  +2  resolved/closed a matching Jira issue

Recency multiplier:
  doc updated within 30 days  → ×1.5
  doc updated within 90 days  → ×1.2
  doc updated within 1 year   → ×1.0
  older                        → ×0.7

Final list is sorted by score descending, max 5 people returned.
"""

from datetime import datetime, timezone
from collections import defaultdict


def _recency_multiplier(updated_at) -> float:
    """Returns a score multiplier based on how recently a doc was updated."""
    if not updated_at:
        return 1.0
    try:
        now = datetime.now(timezone.utc)
        # Handle both datetime objects and strings
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        days_old = (now - updated_at).days
        if days_old <= 30:  return 1.5
        if days_old <= 90:  return 1.2
        if days_old <= 365: return 1.0
        return 0.7
    except Exception:
        return 1.0


def _clean_name(name: str) -> str:
    """Normalise name — strip whitespace, handle None."""
    if not name or not isinstance(name, str):
        return ""
    return name.strip()


def rank_smes(documents: list[dict]) -> list[dict]:
    """
    Given a list of matching documents, return a ranked list of SMEs.

    Each SME dict:
    {
        "name": "Jane Smith",
        "score": 18.5,
        "doc_count": 5,
        "roles": ["Confluence Author", "Jira Assignee"],
        "sources": ["Confluence / ENG", "Jira / OPS"],
        "last_active": "2024-03-01",
        "contribution_breakdown": {
            "authored": 2,
            "assigned": 2,
            "reported": 1,
            "commented": 3,
            "resolved": 1,
        }
    }
    """
    if not documents:
        return []

    # person_name → accumulated data
    scores       = defaultdict(float)
    doc_counts   = defaultdict(int)
    roles        = defaultdict(set)
    sources      = defaultdict(set)
    last_active  = defaultdict(lambda: None)
    breakdown    = defaultdict(lambda: defaultdict(int))

    def _update_last_active(name: str, updated_at):
        """Keep track of most recent activity per person."""
        if not updated_at:
            return
        try:
            if isinstance(updated_at, str):
                updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            current = last_active[name]
            if current is None or updated_at > current:
                last_active[name] = updated_at
        except Exception:
            pass

    for doc in documents:
        source_type = doc.get("source_type", "")
        source      = doc.get("source", "")
        updated_at  = doc.get("updated_at")
        metadata    = doc.get("metadata") or {}
        multiplier  = _recency_multiplier(updated_at)

        # ── Confluence page author ─────────────────────────────────────────────
        if source_type == "confluence":
            author = _clean_name(doc.get("author"))
            if author:
                scores[author]     += 3 * multiplier
                doc_counts[author] += 1
                roles[author].add("Confluence Author")
                sources[author].add(source)
                breakdown[author]["authored"] += 1
                _update_last_active(author, updated_at)

        # ── Jira issue ────────────────────────────────────────────────────────
        elif source_type == "jira":
            reporter = _clean_name(metadata.get("reporter"))
            assignee = _clean_name(metadata.get("assignee"))
            status   = (metadata.get("status") or "").lower()
            resolution = _clean_name(metadata.get("resolution"))
            comment_count = int(metadata.get("comment_count") or 0)

            if reporter:
                scores[reporter]     += 3 * multiplier
                doc_counts[reporter] += 1
                roles[reporter].add("Jira Reporter")
                sources[reporter].add(source)
                breakdown[reporter]["reported"] += 1
                _update_last_active(reporter, updated_at)

            if assignee and assignee != reporter:
                scores[assignee]     += 2 * multiplier
                doc_counts[assignee] += 1
                roles[assignee].add("Jira Assignee")
                sources[assignee].add(source)
                breakdown[assignee]["assigned"] += 1
                _update_last_active(assignee, updated_at)

            # Bonus for resolving/closing issues
            if resolution and status in ("resolved", "closed", "done"):
                person = assignee or reporter
                if person:
                    scores[person]           += 2 * multiplier
                    breakdown[person]["resolved"] += 1
                    roles[person].add("Issue Resolver")

            # Comment author bonus — distributed evenly if we don't have
            # individual comment authors (we store count not names from sync)
            if comment_count > 0 and assignee:
                comment_score = min(comment_count, 10) * 1 * multiplier
                scores[assignee]           += comment_score
                breakdown[assignee]["commented"] += comment_count

        # ── SharePoint document author ─────────────────────────────────────────
        elif source_type == "sharepoint":
            author = _clean_name(doc.get("author"))
            if author:
                scores[author]     += 2 * multiplier
                doc_counts[author] += 1
                roles[author].add("SharePoint Author")
                sources[author].add(source)
                breakdown[author]["authored"] += 1
                _update_last_active(author, updated_at)

    # ── Build output ──────────────────────────────────────────────────────────
    smes = []
    for name, score in scores.items():
        if not name:
            continue

        last = last_active[name]
        last_active_str = None
        if last:
            try:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                last_active_str = last.strftime("%Y-%m-%d")
            except Exception:
                pass

        smes.append({
            "name":       name,
            "score":      round(score, 2),
            "doc_count":  doc_counts[name],
            "roles":      sorted(roles[name]),
            "sources":    sorted(sources[name]),
            "last_active": last_active_str,
            "contribution_breakdown": dict(breakdown[name]),
        })

    # Sort by score descending, then by doc_count as tiebreaker
    smes.sort(key=lambda x: (x["score"], x["doc_count"]), reverse=True)
    return smes[:5]   # top 5 SMEs
