import uuid

from sqlalchemy import CHAR, Column, DateTime, String

from app.database import AuthBase


class SessionDB(AuthBase):
    __tablename__ = "sessions"

    id = Column(CHAR(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_hash = Column(String(64), nullable=False)
    expires_at = Column(DateTime, nullable=False)
