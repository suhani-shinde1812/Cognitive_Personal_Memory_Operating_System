# LOCATION: backend/app/models/sync_device.py
"""
sync_device.py
==============
SQLAlchemy model for desktop computers/devices paired with CogniSphere.
Tracks connection status, watched folders, and synchronization heartbeat.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text
from database.database import Base


class SyncDevice(Base):
    __tablename__ = "sync_devices"

    id              = Column(Integer, primary_key=True, index=True)
    device_id       = Column(String, unique=True, index=True, nullable=False)
    device_name     = Column(String, nullable=False, default="Windows PC")
    os_info         = Column(String, default="Windows")
    auth_token      = Column(String, index=True, nullable=False)
    status          = Column(String, default="connected")  # connected, watching, scanning, paused, disconnected
    watched_folders = Column(Text, default="[]")           # JSON list of folder dicts
    last_heartbeat  = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())
    last_sync       = Column(String, nullable=True)
    created_at      = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())
    user_id         = Column(String, index=True, nullable=True)
    pairing_code    = Column(String, index=True, nullable=True)

    def to_dict(self) -> dict:
        try:
            folders = json.loads(self.watched_folders or "[]")
        except Exception:
            folders = []

        return {
            "id":              self.id,
            "user_id":         self.user_id,
            "device_id":       self.device_id,
            "device_name":     self.device_name,
            "os_info":         self.os_info,
            "status":          self.status,
            "pairing_code":    self.pairing_code,
            "watched_folders": folders,
            "last_heartbeat":  self.last_heartbeat,
            "last_sync":       self.last_sync,
            "created_at":      self.created_at,
        }
