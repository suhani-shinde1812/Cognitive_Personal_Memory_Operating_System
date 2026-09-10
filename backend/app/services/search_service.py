# ðŸ“ LOCATION: backend/app/services/search_service.py
"""
search_service.py
=================
Unified search service combining ACMA, keyword, object, and date search.
All search modes are available through a single search() entry point.
"""

from __future__ import annotations
import json
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.memory import Memory
from ai.semantic_search import acma_search, semantic_search


def search(
    query: str,
    db: Session,
    mode: str = "acma",
    top_k: int = 10,
    user_id: int | None = None,
) -> dict:
    """
    Unified search entry point.

    Modes:
        acma     — ACMA 6-factor activation ranking (default, best quality)
        semantic — FAISS cosine similarity only (faster)
        keyword  — SQLite LIKE full-text search
        object   — Search by detected YOLO object labels
        combined — semantic + keyword merged and de-duplicated
    """
    if mode == "acma":
        results = acma_search(query, db, top_k=top_k, user_id=user_id)
        return {"mode": mode, "count": len(results), "results": results}

    if mode == "semantic":
        results = semantic_search(query, top_k=top_k, user_id=user_id)
        return {"mode": mode, "count": len(results), "results": results}

    if mode == "keyword":
        results = keyword_search(query, db, top_k=top_k, user_id=user_id)
        return {"mode": mode, "count": len(results), "results": results}

    if mode == "object":
        results = object_search(query, db, top_k=top_k, user_id=user_id)
        return {"mode": mode, "count": len(results), "results": results}

    if mode == "combined":
        sem  = semantic_search(query, top_k=top_k, user_id=user_id)
        kw   = keyword_search(query, db, top_k=top_k, user_id=user_id)
        results = _merge_dedupe(sem, kw, top_k)
        return {"mode": mode, "count": len(results), "results": results}

    return {"error": f"Unknown search mode: {mode}", "results": []}


def keyword_search(query: str, db: Session, top_k: int = 10, user_id: int | None = None) -> list[dict]:
    """
    SQLite LIKE search on title + description.
    Fast fallback when embeddings are unavailable.
    """
    pattern = f"%{query}%"
    q_filter = db.query(Memory).filter(
        or_(
            Memory.title.ilike(pattern),
            Memory.description.ilike(pattern),
            Memory.text_content.ilike(pattern),
        )
    )
    if user_id is not None:
        q_filter = q_filter.filter(Memory.user_id == str(user_id))
    rows = q_filter.limit(top_k).all()
    results = []
    for m in rows:
        d = m.to_dict()
        d["score"] = 1.0   # keyword match = max score
        d["match_type"] = "keyword"
        results.append(d)
    return results


def object_search(query: str, db: Session, top_k: int = 10, user_id: int | None = None) -> list[dict]:
    """
    Search memories by YOLO-detected objects stored in the objects column.
    e.g. query='car' finds memories where car was detected in the image.
    """
    query_lower = query.lower()
    q_mem = db.query(Memory)
    if user_id is not None:
        q_mem = q_mem.filter(Memory.user_id == str(user_id))
    all_memories = q_mem.all()
    results = []

    for m in all_memories:
        objects = json.loads(m.objects or "[]")
        if any(query_lower in str(obj).lower() for obj in objects):
            d = m.to_dict()
            d["score"] = 1.0
            d["match_type"] = "object_detection"
            results.append(d)
        if len(results) >= top_k:
            break

    return results


def date_range_search(
    db: Session,
    start_date: str,
    end_date: str,
    top_k: int = 50,
) -> list[dict]:
    """
    Filter memories by date range (ISO strings: YYYY-MM-DD).
    Used by timeline_routes.py.
    """
    rows = (
        db.query(Memory)
        .filter(Memory.date >= start_date, Memory.date <= end_date)
        .order_by(Memory.date.desc())
        .limit(top_k)
        .all()
    )
    return [m.to_dict() for m in rows]


def _merge_dedupe(list_a: list[dict], list_b: list[dict], top_k: int) -> list[dict]:
    """Merge two result lists, deduplicate by id, sort by score."""
    seen: set[int] = set()
    merged = []
    for item in list_a + list_b:
        mid = item.get("id")
        if mid not in seen:
            seen.add(mid)
            merged.append(item)
    merged.sort(key=lambda x: x.get("score", 0), reverse=True)
    return merged[:top_k]


