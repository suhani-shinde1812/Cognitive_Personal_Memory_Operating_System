# LOCATION: desktop_agent/scanner.py
"""
scanner.py
==========
Incremental filesystem scanner for CogniSphere Desktop Agent.
Calculates SHA-256 hashes, maintains a persistent local manifest,
and discovers added, modified, and deleted files.
"""

from __future__ import annotations
import os
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Tuple, Optional

from desktop_agent.config import get_agent_data_dir
from desktop_agent.parsers import is_sync_candidate, should_ignore_file


MANIFEST_FILE = get_agent_data_dir() / "manifest.json"


def compute_sha256(path: Path, chunk_size: int = 65536) -> str:
    """Computes SHA-256 hash of a file safely in chunks."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        print(f"[Scanner] Hash error for {path.name}: {e}")
        return ""


import threading

class LocalManifest:
    """
    Persisted cache of indexed files and their SHA-256 hashes.
    Key: absolute path string
    Value: dict with relative_path, sha256, mtime, size, memory_id
    """
    def __init__(self, manifest_path: Optional[Path] = None):
        self.path = manifest_path or MANIFEST_FILE
        self.entries: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._dirty = False
        self.load()

    def load(self) -> None:
        with self._lock:
            if self.path.exists():
                try:
                    with open(self.path, "r", encoding="utf-8") as f:
                        self.entries = json.load(f)
                except Exception as e:
                    print(f"[Manifest] Error loading manifest: {e}")
                    self.entries = {}

    def save(self) -> None:
        with self._lock:
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        try:
            tmp_path = self.path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.entries, f, indent=2)
            tmp_path.replace(self.path)
            self._dirty = False
        except Exception as e:
            print(f"[Manifest] Error saving manifest: {e}")

    def get(self, abs_path: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self.entries.get(abs_path)

    def set(self, abs_path: str, data: Dict[str, Any], autosave: bool = True) -> None:
        with self._lock:
            self.entries[abs_path] = data
            self._dirty = True
            if autosave:
                self._save_unlocked()

    def flush(self) -> None:
        with self._lock:
            if self._dirty:
                self._save_unlocked()

    def remove(self, abs_path: str) -> None:
        with self._lock:
            if abs_path in self.entries:
                del self.entries[abs_path]
                self._save_unlocked()


class FolderScanner:
    def __init__(self, manifest: Optional[LocalManifest] = None):
        self.manifest = manifest or LocalManifest()

    def scan_folder(
        self,
        folder_path: str,
        folder_name: str,
    ) -> Dict[str, Any]:
        """
        Scans a single folder recursively and identifies changes.
        Returns:
            {
                "added": [...],
                "modified": [...],
                "deleted": [...],
                "unchanged_count": int,
                "total_found": int,
            }
        """
        root = Path(folder_path).resolve()
        if not root.exists() or not root.is_dir():
            return {"added": [], "modified": [], "deleted": [], "unchanged_count": 0, "total_found": 0}

        current_files: Dict[str, Path] = {}
        added: List[Dict[str, Any]] = []
        modified: List[Dict[str, Any]] = []
        unchanged_count = 0

        # 1. Discover all candidate files
        for p in root.rglob("*"):
            if not p.is_file() or should_ignore_file(p):
                continue
            if not is_sync_candidate(p):
                continue

            abs_str = str(p.resolve())
            current_files[abs_str] = p

            try:
                stat = p.stat()
                mtime = stat.st_mtime
                size = stat.st_size
            except Exception:
                continue

            rel_path = f"{folder_name}/{p.relative_to(root).as_posix()}"
            prev_entry = self.manifest.get(abs_str)

            if prev_entry is None:
                # Brand new file
                file_hash = compute_sha256(p)
                if file_hash:
                    item = {
                        "abs_path": abs_str,
                        "relative_path": rel_path,
                        "filename": p.name,
                        "sha256": file_hash,
                        "mtime": mtime,
                        "size": size,
                    }
                    added.append(item)
            else:
                # Previously indexed — check if modified
                if prev_entry.get("mtime") != mtime or prev_entry.get("size") != size:
                    file_hash = compute_sha256(p)
                    if file_hash and file_hash != prev_entry.get("sha256"):
                        item = {
                            "abs_path": abs_str,
                            "relative_path": rel_path,
                            "filename": p.name,
                            "sha256": file_hash,
                            "mtime": mtime,
                            "size": size,
                        }
                        modified.append(item)
                    else:
                        # Hash unchanged despite timestamp touch
                        unchanged_count += 1
                        prev_entry["mtime"] = mtime
                        self.manifest.set(abs_str, prev_entry)
                else:
                    unchanged_count += 1

        # 2. Detect deleted files (were in manifest under this folder root but missing now)
        deleted: List[Dict[str, Any]] = []
        folder_prefix = str(root)
        for abs_str, entry in list(self.manifest.entries.items()):
            if abs_str.startswith(folder_prefix) and abs_str not in current_files:
                deleted.append({
                    "abs_path": abs_str,
                    "relative_path": entry.get("relative_path", ""),
                    "filename": Path(abs_str).name,
                })

        return {
            "added": added,
            "modified": modified,
            "deleted": deleted,
            "unchanged_count": unchanged_count,
            "total_found": len(current_files),
        }
