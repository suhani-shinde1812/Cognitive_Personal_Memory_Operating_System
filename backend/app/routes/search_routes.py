# ðŸ“ LOCATION: backend/app/routes/search_routes.py
"""
search_routes.py  â€” ACCURACY FIX v2
======================================
New endpoints:
  GET /search/              â€” hybrid ACMA search (default, most accurate)
  GET /search/fast          â€” BM25 keyword-only (instant, high precision)
  GET /search/semantic      â€” semantic-only FAISS (broader recall)
  GET /search/explain/{id}  â€” ACMA activation breakdown
  GET /search/suggest       â€” autocomplete suggestions
  POST /search/feedback     â€” relevance feedback (thumbs up/down)
"""

from fastapi import APIRouter, Query, Depends, Body
from sqlalchemy.orm import Session
from typing import Optional

from database.database import get_db
from ai.semantic_search import acma_search, semantic_search
from app.services.search_service import keyword_search
from app.models.user import User
from app.auth.deps import get_optional_current_user

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
@router.get("/")
def search(
    q:       str = Query(..., description="Natural language query"),
    mode:    str = Query("acma", description="acma | fast | semantic | keyword"),
    top_k:   int = Query(12, ge=1, le=100),
    file_type: Optional[str] = Query(None, description="Filter by file type: pdf, jpg, docx..."),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """
    Search memories using the selected mode.
    Enforces user isolation: User A cannot see User B's search results.
    """
    uid = current_user.id if current_user else None
    if mode == "acma":
        results = acma_search(q, db, top_k=top_k, user_id=uid)
    elif mode == "fast":
        results = keyword_search(q, db, top_k=top_k, user_id=uid)
    elif mode == "semantic":
        results = semantic_search(q, top_k=top_k, user_id=uid)
    elif mode == "keyword":
        results = keyword_search(q, db, top_k=top_k, user_id=uid)
    else:
        results = acma_search(q, db, top_k=top_k, user_id=uid)

    # Scoped to current authenticated user
    if current_user:
        results = [r for r in results if r.get("user_id") == current_user.id]

    # File type filter
    if file_type:
        results = [r for r in results if (r.get("file_type") or "").lower() == file_type.lower()]

    return {
        "query":   q,
        "mode":    mode,
        "count":   len(results),
        "results": results,
    }


@router.get("/suggest")
def suggest(
    q:    str = Query(..., min_length=1),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """
    Fast autocomplete suggestions (keyword match, top 5).
    Suitable for search-as-you-type.
    """
    uid = current_user.id if current_user else None
    results = keyword_search(q, db, top_k=5, user_id=uid)
    return [{"id": r["id"], "title": r.get("title", ""), "file_type": r.get("file_type", "")} for r in results]


@router.get("/explain/{memory_id}")
def explain_activation(
    memory_id: int,
    q: str = Query(...),
    db: Session = Depends(get_db),
):
    """Returns the full ACMA activation breakdown for a specific memory + query."""
    results = acma_search(q, db, top_k=100)
    match   = next((r for r in results if r["id"] == memory_id), None)

    if not match:
        return {
            "memory_id":  memory_id,
            "query":      q,
            "in_results": False,
            "message":    "Memory was not activated for this query â€” likely no semantic or keyword match",
        }
    rank = next((i + 1 for i, r in enumerate(results) if r["id"] == memory_id), None)
    return {
        "memory_id":  memory_id,
        "query":      q,
        "in_results": True,
        "rank":       rank,
        "activation": match,
    }


@router.post("/feedback")
def search_feedback(
    memory_id:  int  = Body(...),
    query:      str  = Body(...),
    relevant:   bool = Body(...),
    db: Session = Depends(get_db),
):
    """
    Relevance feedback â€” user marks a result as relevant or not.
    Relevant=True boosts access_count (increases future activation).
    Relevant=False decrements it (reduces future activation).
    Future extension: store feedback in DB for offline learning.
    """
    from app.models.memory import Memory as MemModel
    mem = db.query(MemModel).filter(MemModel.id == memory_id).first()
    if not mem:
        return {"error": "Memory not found"}
    if relevant:
        mem.access_count = (mem.access_count or 0) + 3  # strong boost
    else:
        mem.access_count = max(0, (mem.access_count or 0) - 1)
    db.commit()
    return {"memory_id": memory_id, "relevant": relevant, "new_access_count": mem.access_count}


