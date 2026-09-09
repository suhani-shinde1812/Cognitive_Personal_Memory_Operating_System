"""
app/services/folder_watcher.py
===============================
Watches Desktop, Downloads, Documents, Pictures for new files.
On detection, runs the full CogniSphere memory pipeline.
Uses watchdog. Run as background thread from main.py or standalone.

v2: Added auto_index_location() — triggers full batch conversion of all
    documents in a newly-allowed folder path, with real-time progress tracking.
"""

from __future__ import annotations
import os
import time
import threading
from pathlib import Path
from typing import Dict, Any

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    print("[FolderWatcher] watchdog not installed. Run: pip install watchdog")

from ai.memory_pipeline import run_pipeline


WATCHED_DIRS = [
    Path.home() / "Desktop",
    Path.home() / "Downloads",
    Path.home() / "Documents",
    Path.home() / "Pictures",
]

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp",
    ".pdf", ".docx", ".doc", ".txt",
}

EXCLUDED_DIR_NAMES = {
    ".venv", "venv", "env", ".env",
    "node_modules", "__pycache__", ".git", ".next",
    "dist", "build", "$RECYCLE.BIN",
}

# ── In-memory indexing status tracker ────────────────────────────────────────
# Key: location_id (int)  Value: status dict
_INDEX_STATUS: Dict[int, Dict[str, Any]] = {}
_INDEX_LOCK = threading.Lock()


def get_index_status(location_id: int) -> Dict[str, Any]:
    """Return current auto-indexing progress for a location."""
    with _INDEX_LOCK:
        return dict(_INDEX_STATUS.get(location_id, {
            "running": False,
            "total": 0,
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "done": True,
            "current_file": "",
        }))


def auto_index_location(
    location_id: int,
    folder_path: str,
    user_id: str | None = None,
) -> None:
    """
    Background auto-index: convert all supported files in folder_path
    into CogniSphere memories.

    Safe to call from any thread. Skips duplicates (handled by pipeline).
    Progress is tracked in _INDEX_STATUS[location_id].
    """
    t = threading.Thread(
        target=_run_auto_index,
        args=(location_id, folder_path, user_id),
        daemon=True,
        name=f"AutoIndex-{location_id}",
    )
    t.start()


def _run_auto_index(
    location_id: int,
    folder_path: str,
    user_id: str | None,
) -> None:
    """Worker thread: scan folder and run pipeline on each file."""
    path = Path(folder_path)

    if not path.exists():
        print(f"[AutoIndex] Path does not exist: {folder_path}")
        with _INDEX_LOCK:
            _INDEX_STATUS[location_id] = {
                "running": False, "total": 0, "processed": 0,
                "skipped": 0, "errors": 0, "done": True,
                "current_file": "", "error_msg": "Path does not exist",
            }
        return

    # ── Collect all supported files ───────────────────────────────────────────
    print(f"[AutoIndex] Scanning {folder_path} ...")
    files_to_index: list[Path] = []
    try:
        for f in path.rglob("*"):
            if not f.is_file():
                continue
            # Skip excluded dirs
            if any(part.lower() in EXCLUDED_DIR_NAMES for part in f.parts):
                continue
            if f.suffix.lower() in SUPPORTED_EXTENSIONS:
                files_to_index.append(f)
    except Exception as scan_err:
        print(f"[AutoIndex] Scan error: {scan_err}")

    total = len(files_to_index)
    print(f"[AutoIndex] Found {total} supported files in {folder_path}")

    with _INDEX_LOCK:
        _INDEX_STATUS[location_id] = {
            "running": True,
            "total": total,
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "done": False,
            "current_file": "",
        }

    if total == 0:
        with _INDEX_LOCK:
            _INDEX_STATUS[location_id].update({"running": False, "done": True})
        return

    processed = 0
    skipped = 0
    errors = 0

    for file_path in files_to_index:
        with _INDEX_LOCK:
            _INDEX_STATUS[location_id]["current_file"] = file_path.name

        try:
            uid = int(user_id) if user_id and str(user_id).isdigit() else None
            result = run_pipeline(str(file_path), user_id=uid)

            # Pipeline returns existing id if duplicate (skipped)
            if result.get("id") and result.get("detected_goals") == [] and \
               result.get("description") == "":
                skipped += 1
            else:
                processed += 1

        except Exception as e:
            print(f"[AutoIndex] Error processing {file_path.name}: {e}")
            errors += 1

        with _INDEX_LOCK:
            _INDEX_STATUS[location_id].update({
                "processed": processed,
                "skipped": skipped,
                "errors": errors,
            })

    # ── Refresh indices after batch ───────────────────────────────────────────
    _refresh_after_change()

    with _INDEX_LOCK:
        _INDEX_STATUS[location_id].update({
            "running": False,
            "done": True,
            "current_file": "",
        })

    print(
        f"[AutoIndex] Done: {processed} converted, "
        f"{skipped} skipped (duplicates), {errors} errors — {folder_path}"
    )


# ── File System Event Handler ─────────────────────────────────────────────────

class CogniSphereEventHandler(FileSystemEventHandler if WATCHDOG_AVAILABLE else object):
    def __init__(self):
        self._processing: set[str] = set()
        self._lock = threading.Lock()

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return
        # Debounce: avoid double-processing
        with self._lock:
            if str(path) in self._processing:
                return
            self._processing.add(str(path))

        # Small delay to ensure file is fully written
        time.sleep(1.5)
        try:
            print(f"[FolderWatcher] New file detected: {path.name}")
            result = run_pipeline(str(path))
            print(f"[FolderWatcher] Ingested: {result.get('title')} (goals: {result.get('detected_goals', [])})")

            # ✅ Refresh cache and rebuild indices after successful ingestion
            _refresh_after_change()

        except Exception as e:
            print(f"[FolderWatcher] Pipeline error for {path.name}: {e}")
        finally:
            with self._lock:
                self._processing.discard(str(path))


def start_watcher():
    if not WATCHDOG_AVAILABLE:
        print("[FolderWatcher] Cannot start — watchdog not installed.")
        return None

    handler = CogniSphereEventHandler()
    observer = Observer()

    watched = 0
    for watch_dir in WATCHED_DIRS:
        if watch_dir.exists():
            observer.schedule(handler, str(watch_dir), recursive=True)
            watched += 1
            print(f"[FolderWatcher] Watching: {watch_dir}")

    if watched == 0:
        print("[FolderWatcher] No valid directories to watch.")
        return None

    observer.start()
    print(f"[FolderWatcher] Started — watching {watched} directories.")
    return observer


def start_watcher_thread():
    """Start watcher in a background daemon thread."""
    t = threading.Thread(target=_run_watcher, daemon=True)
    t.start()
    return t


def _run_watcher():
    observer = start_watcher()
    if observer:
        try:
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()


def _refresh_after_change():
    """
    Refresh memory cache and rebuild search indices after any data modification.
    Called after successful pipeline ingestion.
    """
    try:
        from app.services.database_service import refresh_memory_cache, get_all_memories
        from ai.faiss_service import build_index
        from ai.hybrid_search import build_bm25

        # Refresh in-memory cache
        refresh_memory_cache()
        print("[FolderWatcher] Memory cache refreshed after ingestion")

        # Rebuild FAISS and BM25 indices
        memories = get_all_memories()
        if memories:
            build_index(memories)
            print(f"[FolderWatcher] FAISS index rebuilt with {len(memories)} memories")

            build_bm25(memories)
            print(f"[FolderWatcher] BM25 index rebuilt with {len(memories)} memories")
        else:
            print("[FolderWatcher] No memories to index")
    except Exception as e:
        print(f"[FolderWatcher] Error refreshing after change: {e}")


if __name__ == "__main__":
    observer = start_watcher()
    if observer:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
