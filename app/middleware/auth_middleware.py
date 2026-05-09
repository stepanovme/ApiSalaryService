from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_auth_db
from app.repositories.session_repository import SessionRepository


def get_session(
    session_token: str | None = Cookie(default=None, alias="session"),
    db: Session = Depends(get_auth_db),
):
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session token missing"
        )

    session_repository = SessionRepository(db)
    authenticated_session = session_repository.get_authenticated_session(session_token)
    if not authenticated_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    return authenticated_session
