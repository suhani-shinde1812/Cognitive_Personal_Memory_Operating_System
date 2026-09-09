# ðŸ“ LOCATION: backend/app/routes/graph_routes.py
"""
graph_routes.py
===============
Memory relationship graph endpoints for frontend visualization.
Provides nodes + edges for D3.js / Cytoscape graph rendering.
"""

from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlalchemy.orm import Session

from typing import Optional
from database.database import get_db
from app.services.graph_service import rebuild_graph, get_graph, get_neighbors
from app.models.user import User
from app.auth.deps import get_optional_current_user

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/")
def get_memory_graph(
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns the full memory relationship graph scoped to user.
    """
    graph = get_graph(db)
    if current_user:
        # Filter nodes and edges to current user
        from app.models.memory import Memory
        user_mem_ids = {m.id for m in db.query(Memory.id).filter(Memory.user_id == str(current_user.id)).all()}
        filtered_nodes = [n for n in graph.get("nodes", []) if n.get("id") in user_mem_ids]
        filtered_edges = [e for e in graph.get("edges", []) if e.get("source") in user_mem_ids and e.get("target") in user_mem_ids]
        return {
            "nodes": filtered_nodes,
            "edges": filtered_edges,
            "stats": {"total_nodes": len(filtered_nodes), "total_edges": len(filtered_edges)},
        }
    return graph


@router.post("/rebuild")
def rebuild_memory_graph(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Rebuilds the relationship graph from scratch.
    Runs in background — can take a few seconds for large collections.
    """
    background_tasks.add_task(_rebuild_task)
    return {"message": "Graph rebuild started in background"}


@router.get("/neighbors/{memory_id}")
def get_memory_neighbors(
    memory_id: int,
    top_k: int = Query(10, ge=1, le=50),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns the top_k most strongly connected memories to a given memory.
    """
    if current_user:
        from app.models.memory import Memory
        mem = db.query(Memory).filter(Memory.id == memory_id, Memory.user_id == str(current_user.id)).first()
        if not mem:
            return {"memory_id": memory_id, "neighbors": []}
    neighbors = get_neighbors(db, memory_id, top_k=top_k)
    return {"memory_id": memory_id, "neighbors": neighbors}


@router.get("/patterns")
def detect_patterns(current_user: Optional[User] = Depends(get_optional_current_user)):
    """
    Detects recurring memory patterns scoped to user.
    """
    from ai.temporal_reasoner import detect_recurring_patterns
    from app.services.database_service import get_all_memories
    user_id = current_user.id if current_user else None
    memories = get_all_memories(user_id=user_id)
    patterns = detect_recurring_patterns(memories)
    return {"patterns": patterns}


def _rebuild_task():
    from database.database import SessionLocal
    db = SessionLocal()
    try:
        stats = rebuild_graph(db)
        print(f"[Graph] Rebuild complete: {stats}")
    finally:
        db.close()


