# LOCATION: backend/app/models/indexed_file.py
"""
indexed_file.py
===============
SQLAlchemy model for files synced from user desktop computers.
Maintains SHA-256 content hashes, sync state, and foreign links to memories.
"""

from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Boolean
from database.database import Base


class IndexedFile(Base):
    __tablename__ = "indexed_files"

    id               = Column(Integer, primary_key=True, index=True)
    device_id        = Column(String, index=True, nullable=False)
    relative_path    = Column(String, index=True, nullable=False)
    filename         = Column(String, index=True, nullable=False)
    extension        = Column(String, default="")
    mime_type        = Column(String, default="application/octet-stream")
    file_size        = Column(Integer, default=0)
    sha256_hash      = Column(String, index=True, nullable=False)
    file_modified_at = Column(String, nullable=True)
    first_indexed_at = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())
    last_indexed_at  = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())
    sync_status      = Column(String, default="synced")  # synced, pending, error, deleted
    memory_id        = Column(Integer, nullable=True)     # Links to memories.id
    error_message    = Column(Text, nullable=True)
    is_deleted       = Column(Boolean, default=False, nullable=False)
    user_id          = Column(String, index=True, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "user_id":          self.user_id,
            "device_id":        self.device_id,
            "relative_path":    self.relative_path,
            "filename":         self.filename,
            "extension":        self.extension,
            "mime_type":        self.mime_type,
            "file_size":        self.file_size,
            "sha256_hash":      self.sha256_hash,
            "file_modified_at": self.file_modified_at,
            "first_indexed_at": self.first_indexed_at,
            "last_indexed_at":  self.last_indexed_at,
            "sync_status":      self.sync_status,
            "memory_id":        self.memory_id,
            "error_message":    self.error_message,
            "is_deleted":       self.is_deleted,
        }
