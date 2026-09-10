"""
database_service.py
===================
Enterprise in-memory memory cache.
Loads all memories once at startup.
All searches read from RAM instead of SQLite.
"""

from __future__ import annotations

from database.database import SessionLocal
from app.models.memory import Memory

_memory_cache: list[dict] = []
_cache_loaded = False


def load_memory_cache() -> None:
    """
    Loads every memory into RAM.
    Called once during application startup.
    """
    global _memory_cache, _cache_loaded

    db = SessionLocal()
    try:
        memories = db.query(Memory).all()
        _memory_cache = [m.to_dict() for m in memories]
        _cache_loaded = True
        print(f"[MemoryCache] Loaded {len(_memory_cache)} memories.")
    finally:
        db.close()


def refresh_memory_cache() -> None:
    """
    Rebuild cache after uploads/imports.
    """
    load_memory_cache()


def get_all_memories(user_id: int | None = None) -> list[dict]:
    """
    Returns cached memories, optionally scoped to a specific user.
    Falls back to loading if cache isn't ready.
    """
    global _cache_loaded

    if not _cache_loaded:
        load_memory_cache()

    if user_id is not None:
        uid_str = str(user_id)  # cache stores user_id as str
        return [m for m in _memory_cache if str(m.get("user_id") or "") == uid_str]

    return _memory_cache


def get_memory_by_id(memory_id: int, user_id: int | None = None) -> dict | None:
    global _cache_loaded

    if not _cache_loaded:
        load_memory_cache()

    for mem in _memory_cache:
        if mem["id"] == memory_id:
            if user_id is not None and str(mem.get("user_id") or "") != str(user_id):
                return None
            return mem

    return None


def delete_memory(memory_id: int, user_id: int | None = None) -> bool:
    db = SessionLocal()

    try:
        query = db.query(Memory).filter(Memory.id == memory_id)
        if user_id is not None:
            query = query.filter(Memory.user_id == str(user_id))
        mem = query.first()

        if mem is None:
            return False

        db.delete(mem)
        db.commit()

    finally:
        db.close()

    refresh_memory_cache()

    return True


