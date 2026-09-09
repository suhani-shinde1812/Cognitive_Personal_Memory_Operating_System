"""
app/models/memory.py
====================
Updated Memory model. Adds importance_score and access_count
needed by the ACMA engine. Fully backward-compatible with existing
migration data (new columns have defaults).

v3: Added version + parent_id for memory history / temporal experiments.
"""

from sqlalchemy import Column, Integer, String, Text, Float
from database.database import Base


class Memory(Base):
    __tablename__ = "memories"

    id               = Column(Integer, primary_key=True, index=True)
    title            = Column(String,  index=True)
    description      = Column(Text)
    text_content     = Column(Text)
    source           = Column(String)
    file_type        = Column(String)
    image            = Column(String)
    date             = Column(String)
    location         = Column(String)
    embedding        = Column(Text)    # JSON-serialized list[float]
    objects          = Column(Text)    # JSON-serialized list[str]

    # ACMA fields
    importance_score = Column(Float,   default=0.5, nullable=False, server_default="0.5")
    access_count     = Column(Integer, default=0,   nullable=False, server_default="0")

    # Versioning fields — for memory update history / temporal experiments
    version          = Column(Integer, default=1,    nullable=False, server_default="1")
    parent_id        = Column(Integer, default=None, nullable=True)

    # Multi-user isolation
    user_id          = Column(String, index=True,   nullable=True)

    def to_dict(self):
        import json
        return {
            "id":               self.id,
            "user_id":          self.user_id,
            "title":            self.title,
            "description":      self.description,
            "text_content":     self.text_content or "",
            "source":           self.source,
            "file_type":        self.file_type,
            "image":            self.image,
            "date":             self.date,
            "location":         self.location,
            "embedding":        json.loads(self.embedding or "[]"),
            "objects":          json.loads(self.objects or "[]"),
            "importance_score": self.importance_score or 0.5,
            "access_count":     self.access_count or 0,
            "version":          self.version or 1,
            "parent_id":        self.parent_id,
        }



