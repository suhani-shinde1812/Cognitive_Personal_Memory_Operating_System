"""
app/routes/chat_routes.py
==========================
Chat endpoint — RAG over ACMA-ranked memories.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from database.database import get_db
from ai.chat_service import chat_with_memories
from app.models.user import User
from app.auth.deps import get_optional_current_user

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    query: str
    history: Optional[list[dict]] = None


@router.post("")
@router.post("/")
def chat(
    payload: ChatRequest,
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """
    Ask a question over your memories.
    Scoped strictly to the authenticated user's memories.

    Response includes:
    - answer: str — the AI answer (or fast structured memory summary)
    - sources: list — each memory used, with file_path and abstract
    - fast_answer: bool — True if answered without Ollama (instant)
    - memories_used: list — full memory objects used for retrieval
    """
    user_id = current_user.id if current_user else None
    result = chat_with_memories(
        query=payload.query,
        db=db,
        conversation_history=payload.history,
        user_id=user_id,
    )
    return result
