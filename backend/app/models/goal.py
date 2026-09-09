"""
app/models/goal.py
==================
Goal node in the GAMA graph.
parent_id enables hierarchical goals (e.g. "Germany Masters" under "Education").
"""

from sqlalchemy import Column, Integer, String, Text, Float, ForeignKey
from database.database import Base


class Goal(Base):
    __tablename__ = "goals"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String,  unique=True, nullable=False, index=True)
    description = Column(Text,    default="")
    parent_id   = Column(Integer, ForeignKey("goals.id"), nullable=True)
    status      = Column(String,  default="active")   # active | completed | paused
    progress    = Column(Float,   default=0.0)
    user_id     = Column(String, index=True, nullable=True)

    def to_dict(self):
        return {
            "id":          self.id,
            "user_id":     self.user_id,
            "name":        self.name,
            "description": self.description,
            "parent_id":   self.parent_id,
            "status":      self.status,
            "progress":    self.progress,
        }


