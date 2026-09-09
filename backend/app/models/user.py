# LOCATION: backend/app/models/user.py
"""
user.py
=======
SQLAlchemy model for user authentication and multi-tenant data isolation.
"""

from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
from database.database import Base


class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    email         = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=True)
    created_at    = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())
    updated_at    = Column(String, default=lambda: datetime.now(timezone.utc).isoformat(), onupdate=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self):
        return {
            "id":         self.id,
            "email":      self.email,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
