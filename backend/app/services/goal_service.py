"""
app/services/goal_service.py
=============================
Service layer for Goal CRUD and progress reports.
Wraps GAMAService with HTTP-friendly return types.
"""

from __future__ import annotations
from sqlalchemy.orm import Session

from ai.gama_service import GAMAService
from app.models.goal import Goal
from app.models.goal_memory import GoalMemory


def create_goal(db: Session, name: str, description: str = "", parent_id: int = None, user_id: str | int | None = None) -> dict:
    gama = GAMAService(db)
    goal = gama.ensure_goal_exists(name, description, parent_id)
    if user_id is not None and goal.user_id != str(user_id):
        goal.user_id = str(user_id)
        db.commit()
        db.refresh(goal)
    return goal.to_dict()


def get_all_goals(db: Session, user_id: str | int | None = None) -> list[dict]:
    query = db.query(Goal)
    if user_id is not None:
        query = query.filter(Goal.user_id == str(user_id))
    goals = query.all()
    return [g.to_dict() for g in goals]


def get_goal_progress(db: Session, goal_id: int) -> dict:
    gama = GAMAService(db)
    report = gama.get_progress_report(goal_id)
    return report.to_dict()


def update_goal_status(db: Session, goal_id: int, status: str, user_id: str | int | None = None) -> dict | None:
    query = db.query(Goal).filter(Goal.id == goal_id)
    if user_id is not None:
        query = query.filter(Goal.user_id == str(user_id))
    goal = query.first()
    if not goal:
        return None
    goal.status = status
    db.commit()
    db.refresh(goal)
    return goal.to_dict()


def delete_goal(db: Session, goal_id: int, user_id: str | int | None = None) -> bool:
    query = db.query(Goal).filter(Goal.id == goal_id)
    if user_id is not None:
        query = query.filter(Goal.user_id == str(user_id))
    goal = query.first()
    if not goal:
        return False
    # Remove edges first
    db.query(GoalMemory).filter(GoalMemory.goal_id == goal_id).delete()
    db.delete(goal)
    db.commit()
    return True


def get_goals_for_memory(db: Session, memory_id: int) -> list[dict]:
    links = db.query(GoalMemory).filter(GoalMemory.memory_id == memory_id).all()
    goals = []
    for lnk in links:
        goal = db.query(Goal).filter(Goal.id == lnk.goal_id).first()
        if goal:
            goals.append(goal.to_dict())
    return goals


