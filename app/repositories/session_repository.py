import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class AuthenticatedSession:
    token: str
    user_id: str | None = None


class SessionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def is_valid(self, token: str) -> bool:
        return self.get_authenticated_session(token) is not None

    def get_authenticated_session(self, token: str) -> AuthenticatedSession | None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = datetime.now(timezone.utc)
        try:
            result = self.db.execute(
                text(
                    """
                    SELECT user_id
                    FROM sessions
                    WHERE token_hash = :token_hash
                      AND expires_at > :now
                    LIMIT 1
                    """
                ),
                {"token_hash": token_hash, "now": now},
            ).first()
            return (
                AuthenticatedSession(token=token, user_id=result[0]) if result else None
            )
        except SQLAlchemyError:
            self.db.rollback()
            result = self.db.execute(
                text(
                    """
                    SELECT 1
                    FROM sessions
                    WHERE token_hash = :token_hash
                      AND expires_at > :now
                    LIMIT 1
                    """
                ),
                {"token_hash": token_hash, "now": now},
            ).first()
            return AuthenticatedSession(token=token) if result else None
