# LOCATION: backend/app/models/user.py
"""
user.py
=======
SQLAlchemy model for user authentication and multi-tenant data isolation.
"""

from __future__ import annotations
from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, Integer, String, DateTime
from database.database import Base


class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name            = Column(String, nullable=True)
    email           = Column(String, unique=True, index=True, nullable=False)
    password_hash   = Column(String, nullable=True)
    hashed_password = Column(String, nullable=True)
    created_at      = Column(String, default=lambda: datetime.now(timezone.utc).isoformat())
    updated_at      = Column(String, default=lambda: datetime.now(timezone.utc).isoformat(), onupdate=lambda: datetime.now(timezone.utc).isoformat())

    def __init__(self, **kwargs):
        # Synchronize password_hash and hashed_password for legacy database compatibility
        if "password_hash" in kwargs and "hashed_password" not in kwargs:
            kwargs["hashed_password"] = kwargs["password_hash"]
        elif "hashed_password" in kwargs and "password_hash" not in kwargs:
            kwargs["password_hash"] = kwargs["hashed_password"]
        super().__init__(**kwargs)

    def to_dict(self):
        return {
            "id":         self.id,
            "name":       self.name,
            "email":      self.email,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
