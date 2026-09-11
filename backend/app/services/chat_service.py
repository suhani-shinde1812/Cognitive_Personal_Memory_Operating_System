"""
ai/chat_service.py
==================
RAG pipeline over CogniSphere memories.

Uses ACMA-ranked memories as context for Ollama.
Returns:
- answer
- memories used
- goal context
"""

from __future__ import annotations

import os
import requests
from sqlalchemy.orm import Session

from ai.semantic_search import acma_search

# -----------------------------
# Configuration
# -----------------------------

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_URL = os.getenv("OLLAMA_URL", f"{OLLAMA_BASE_URL}/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi3:mini")

MAX_CONTEXT_CHARS = 1000

SYSTEM_PROMPT = """
You are CogniSphere, an intelligent personal memory assistant.

Answer ONLY using the supplied memory context.

If the answer is not available in the memories,
say that clearly.

Keep responses concise, accurate and helpful.
"""


def chat_with_memories(
    query: str,
    db: Session,
    conversation_history: list[dict] | None = None,
) -> dict:
    """
    Chat over stored memories using Retrieval-Augmented Generation (RAG).

    Returns
    -------
    {
        "answer": str,
        "memories_used": [...],
        "goal_context": [...]
    }
    """

    # -------------------------------------------------------
    # 1. Retrieve relevant memories using ACMA
    # -------------------------------------------------------

    acma_results = acma_search(
        query=query,
        db=db,
        top_k=3,
    )

    if not acma_results:
        return {
            "answer": "I couldn't find any relevant memories for your question.",
            "memories_used": [],
            "goal_context": [],
        }

    # -------------------------------------------------------
    # 2. Build memory context
    # -------------------------------------------------------

    context_parts = []
    total_chars = 0
    memories_used = []

    for mem in acma_results:

        snippet = (
            f"Title: {mem['title']}\n"
            f"{mem.get('description', '')}"
        )

        if total_chars + len(snippet) > MAX_CONTEXT_CHARS:
            break

        context_parts.append(snippet)
        total_chars += len(snippet)

        memories_used.append(
            {
                "id": mem["id"],
                "title": mem["title"],
                "activation_score": mem.get("activation_score", 0),
                "activation_reason": mem.get("activation_reason", ""),
                "matched_goals": mem.get("matched_goals", []),
            }
        )

    context = "\n\n".join(context_parts)

    goal_context = sorted(
        {
            goal
            for memory in memories_used
            for goal in memory["matched_goals"]
        }
    )

    # -------------------------------------------------------
    # 3. Conversation history
    # -------------------------------------------------------

    history_text = ""

    if conversation_history:

        recent = conversation_history[-4:]

        for turn in recent:

            role = turn.get("role", "user").capitalize()

            content = turn.get("content", "")

            history_text += f"{role}: {content}\n"

    # -------------------------------------------------------
    # 4. Build final prompt
    # -------------------------------------------------------

    prompt = f"""
{SYSTEM_PROMPT}

Memory Context:
{context}

Conversation:
{history_text}

User:
{query}

Assistant:
"""

    # -------------------------------------------------------
    # 5. Call Ollama
    # -------------------------------------------------------

    try:

        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=(2.0, 45.0),
        )

        response.raise_for_status()

        answer = response.json().get("response", "").strip()

        if not answer:
            answer = "The model returned an empty response."

    except Exception as e:

        answer = (
            "Unable to communicate with Ollama.\n\n"
            f"Error: {str(e)}"
        )

    # -------------------------------------------------------
    # 6. Return response
    # -------------------------------------------------------

    return {
        "answer": answer,
        "memories_used": memories_used,
        "goal_context": goal_context,
    }


