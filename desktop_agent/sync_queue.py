# LOCATION: desktop_agent/sync_queue.py
"""
sync_queue.py
=============
Persistent, offline-resilient local job queue for CogniSphere Desktop Agent.
Ensures file sync events are never lost if backend connection is interrupted.
"""

from __future__ import annotations
import sqlite3
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from desktop_agent.config import get_agent_data_dir

QUEUE_DB = get_agent_data_dir() / "sync_queue.db"


class SyncQueue:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or QUEUE_DB
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=30.0)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS queue_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    retries INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.commit()

    def enqueue(self, job_type: str, payload: Dict[str, Any]) -> int:
        """Adds a new job to the sync queue."""
        now = time.time()
        with self._connect() as conn:
            cur = conn.cursor()
            # Avoid duplicate pending jobs for the same file
            rel_path = payload.get("relative_path")
            if rel_path:
                cur.execute("""
                    SELECT id FROM queue_jobs
                    WHERE status = 'pending' AND job_type = ? AND payload LIKE ?
                """, (job_type, f'%"relative_path": "{rel_path}"%'))
                row = cur.fetchone()
                if row:
                    return row[0]

            cur.execute("""
                INSERT INTO queue_jobs (job_type, payload, status, retries, created_at, updated_at)
                VALUES (?, ?, 'pending', 0, ?, ?)
            """, (job_type, json.dumps(payload), now, now))
            conn.commit()
            return cur.lastrowid

    def get_pending(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetches pending jobs with retries < 5."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT id, job_type, payload, retries
                FROM queue_jobs
                WHERE status = 'pending' AND retries < 5
                ORDER BY id ASC
                LIMIT ?
            """, (limit,))
            rows = cur.fetchall()

        jobs = []
        for r in rows:
            try:
                payload = json.loads(r["payload"])
            except Exception:
                payload = {}
            jobs.append({
                "id": r["id"],
                "job_type": r["job_type"],
                "payload": payload,
                "retries": r["retries"],
            })
        return jobs

    def mark_done(self, job_id: int) -> None:
        """Removes or marks completed job."""
        with self._connect() as conn:
            conn.execute("DELETE FROM queue_jobs WHERE id = ?", (job_id,))
            conn.commit()

    def mark_failed(self, job_id: int, error: str) -> None:
        """Increments retry count and sets error."""
        now = time.time()
        with self._connect() as conn:
            conn.execute("""
                UPDATE queue_jobs
                SET retries = retries + 1,
                    error_message = ?,
                    updated_at = ?
                WHERE id = ?
            """, (error[:500], now, job_id))
            conn.commit()

    def count_pending(self) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM queue_jobs WHERE status = 'pending' AND retries < 5")
            return cur.fetchone()[0]

    def reset_failed(self) -> int:
        """Resets retries to 0 for all jobs with retries >= 5 so they can be re-attempted."""
        with self._connect() as conn:
            cur = conn.execute("UPDATE queue_jobs SET retries = 0 WHERE status = 'pending' AND retries >= 5")
            conn.commit()
            return cur.rowcount

    def clear(self) -> None:
        """Clears all jobs from the queue."""
        with self._connect() as conn:
            conn.execute("DELETE FROM queue_jobs")
            conn.commit()
