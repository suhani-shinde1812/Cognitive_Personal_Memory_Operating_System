"""
app/routes/goal_routes.py
==========================
Goal graph CRUD and progress reporting endpoints.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from database.database import get_db
from app.services.goal_service import (
    create_goal, get_all_goals, get_goal_progress,
    update_goal_status, delete_goal, get_goals_for_memory,
)

from app.models.user import User
from app.auth.deps import get_current_user

router = APIRouter(prefix="/goals", tags=["goals"])


class GoalCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    parent_id: Optional[int] = None


class GoalStatusUpdate(BaseModel):
    status: str  # active | completed | paused


@router.get("/")
def list_goals(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_all_goals(db, user_id=str(current_user.id))


@router.post("/")
def add_goal(
    payload: GoalCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return create_goal(db, payload.name, payload.description, payload.parent_id, user_id=str(current_user.id))


@router.get("/{goal_id}/progress")
def goal_progress(
    goal_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns goal completion report with present memories and inferred missing docs.
    This is the Explainable AI endpoint.
    """
    try:
        return get_goal_progress(db, goal_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{goal_id}/status")
def set_goal_status(
    goal_id: int,
    payload: GoalStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = update_goal_status(db, goal_id, payload.status, user_id=current_user.id)
    if not result:
        raise HTTPException(status_code=404, detail="Goal not found")
    return result


@router.delete("/{goal_id}")
def remove_goal(
    goal_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ok = delete_goal(db, goal_id, user_id=current_user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Goal not found")
    return {"deleted": goal_id}


@router.get("/memory/{memory_id}")
def goals_for_memory(memory_id: int, db: Session = Depends(get_db)):
    """Returns all goals that a given memory is linked to."""
    return get_goals_for_memory(db, memory_id)


