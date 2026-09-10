# ðŸ“ LOCATION: backend/app/services/stats_service.py
"""
stats_service.py
================
Computes system-wide statistics for the CogniSphere dashboard.
Covers memories, goals, file types, embeddings, and ACMA quality.
"""

from __future__ import annotations
from collections import Counter
from sqlalchemy.orm import Session

from app.models.memory import Memory
from app.models.goal import Goal
from app.models.goal_memory import GoalMemory
import json


def get_full_stats(db: Session, user_id: int | None = None) -> dict:
    """
    Returns a comprehensive statistics snapshot scoped to a user.
    Called by stats_routes.py GET /stats/

    IMPORTANT: Memory.user_id is stored as String (e.g. '1'), not int.
    All filters must use str(user_id) to match correctly.
    """
    mem_query = db.query(Memory)
    goal_query = db.query(Goal)
    if user_id is not None:
        uid_str = str(user_id)          # Memory.user_id is String column
        mem_query = mem_query.filter(Memory.user_id == uid_str)
        goal_query = goal_query.filter(Goal.user_id == uid_str)

    memories = mem_query.all()
    goals    = goal_query.all()
    edges    = db.query(GoalMemory).count()

    # File type breakdown
    file_types = Counter(m.file_type or "unknown" for m in memories)

    # Goal status breakdown
    goal_status = Counter(g.status or "active" for g in goals)

    # Embedding coverage (how many memories have embeddings)
    has_embedding = sum(
        1 for m in memories
        if m.embedding and json.loads(m.embedding or "[]")
    )

    # Importance score distribution
    scores = [m.importance_score or 0.0 for m in memories]
    avg_importance  = sum(scores) / len(scores) if scores else 0.0
    high_importance = sum(1 for s in scores if s >= 0.7)
    low_importance  = sum(1 for s in scores if s < 0.3)

    # Access counts
    access_counts = [m.access_count or 0 for m in memories]
    total_accesses = sum(access_counts)
    most_accessed = sorted(
        [{"id": m.id, "title": m.title, "access_count": m.access_count or 0} for m in memories],
        key=lambda x: x["access_count"],
        reverse=True,
    )[:5]

    # Object detection coverage
    has_objects = sum(
        1 for m in memories
        if m.objects and json.loads(m.objects or "[]")
    )

    # Recent activity (last 10 memories added)
    recent = sorted(memories, key=lambda m: m.date or "", reverse=True)[:10]
    recent_list = [{"id": m.id, "title": m.title, "date": m.date} for m in recent]

    return {
        "totals": {
            "memories":           len(memories),
            "goals":              len(goals),
            "goal_memory_edges":  edges,
        },
        "goals": {
            "by_status": dict(goal_status),
            "active":    goal_status.get("active", 0),
            "completed": goal_status.get("completed", 0),
            "paused":    goal_status.get("paused", 0),
        },
        "files": {
            "by_type":         dict(file_types),
            "embedding_coverage": f"{has_embedding}/{len(memories)}",
            "object_detection_coverage": f"{has_objects}/{len(memories)}",
        },
        "acma": {
            "avg_importance_score": round(avg_importance, 3),
            "high_importance_count": high_importance,
            "low_importance_count":  low_importance,
            "total_retrievals":      total_accesses,
            "most_accessed":         most_accessed,
        },
        "recent_memories": recent_list,
    }


