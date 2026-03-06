"""
BM25 Scoring
─────────────
Re-ranks MongoDB text search candidates using the BM25 algorithm.
No external libraries — pure Python math.

BM25 is the industry standard relevance ranking used by
Elasticsearch, Solr, and Lucene. Much better than raw TF-IDF.

Parameters:
  k1 = 1.5   (term frequency saturation — higher = more weight on repeated terms)
  b  = 0.75  (length normalisation — 1.0 = full normalisation, 0 = none)
"""

import re
import math
from collections import Counter


K1 = 1.5
B  = 0.75


def _tokenize(text: str) -> list[str]:
    """Lowercase, remove punctuation, split into words of 2+ chars."""
    return re.findall(r'\b[a-z]{2,}\b', text.lower())


def _build_corpus(documents: list[dict]) -> tuple[list[list[str]], float]:
    """Tokenize all documents and compute average document length."""
    tokenized = []
    for doc in documents:
        text = f"{doc.get('title','')} {doc.get('content','')}"
        tokenized.append(_tokenize(text))

    avg_dl = sum(len(t) for t in tokenized) / max(len(tokenized), 1)
    return tokenized, avg_dl


def _idf(term: str, tokenized_docs: list[list[str]], n: int) -> float:
    """Compute IDF (Inverse Document Frequency) for a term."""
    df = sum(1 for doc_tokens in tokenized_docs if term in set(doc_tokens))
    return math.log((n - df + 0.5) / (df + 0.5) + 1)


def bm25_score(query: str, doc_tokens: list[str], idfs: dict, avg_dl: float) -> float:
    """Compute BM25 score for a single document."""
    dl = len(doc_tokens)
    tf_map = Counter(doc_tokens)
    score = 0.0

    for term in set(_tokenize(query)):
        if term not in idfs:
            continue
        tf = tf_map.get(term, 0)
        numerator   = tf * (K1 + 1)
        denominator = tf + K1 * (1 - B + B * dl / avg_dl)
        score += idfs[term] * (numerator / denominator)

    return score


def rerank_bm25(query: str, documents: list[dict]) -> list[dict]:
    """
    Re-rank a list of documents by BM25 score.
    Each doc gets a 'bm25_score' field added.
    Returns sorted list (highest score first).
    """
    if not documents or not query.strip():
        return documents

    n = len(documents)
    tokenized, avg_dl = _build_corpus(documents)

    # Compute IDF for each unique query term
    query_terms = set(_tokenize(query))
    idfs = {term: _idf(term, tokenized, n) for term in query_terms}

    # Score each document
    scored = []
    for i, doc in enumerate(documents):
        score = bm25_score(query, tokenized[i], idfs, avg_dl)
        doc_copy = dict(doc)
        doc_copy['bm25_score'] = round(score, 4)
        scored.append(doc_copy)

    # Sort by BM25 score descending
    scored.sort(key=lambda x: x['bm25_score'], reverse=True)
    return scored
