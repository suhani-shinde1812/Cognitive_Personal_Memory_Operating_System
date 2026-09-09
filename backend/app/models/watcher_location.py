# LOCATION: backend/app/models/watcher_location.py
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from database.database import Base


class WatcherLocation(Base):
    __tablename__ = "watcher_locations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    path = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    location_type = Column(String, default="standard")  # standard | custom | drive
    permission_status = Column(String, default="granted")  # granted | pending | revoked | denied
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_scan_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "path": self.path,
            "display_name": self.display_name,
            "location_type": self.location_type,
            "permission_status": self.permission_status,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_scan_at": self.last_scan_at.isoformat() if self.last_scan_at else None,
        }
