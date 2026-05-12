import os
from typing import Annotated, Generator

from dotenv import load_dotenv
from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()

SALARY_DB_URL = (
    f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)

AUTH_DB_URL = (
    f"mysql+pymysql://{os.getenv('AUTH_DB_USER', os.getenv('DB_USER'))}"
    f":{os.getenv('AUTH_DB_PASSWORD', os.getenv('DB_PASSWORD'))}"
    f"@{os.getenv('AUTH_DB_HOST', os.getenv('DB_HOST'))}"
    f":{os.getenv('AUTH_DB_PORT', os.getenv('DB_PORT'))}"
    f"/{os.getenv('AUTH_DB_NAME', os.getenv('DB_NAME'))}"
)

REFERENCE_DB_URL = (
    f"mysql+pymysql://{os.getenv('REFERENCE_DB_USER', os.getenv('DB_USER'))}"
    f":{os.getenv('REFERENCE_DB_PASSWORD', os.getenv('DB_PASSWORD'))}"
    f"@{os.getenv('REFERENCE_DB_HOST', os.getenv('DB_HOST'))}"
    f":{os.getenv('REFERENCE_DB_PORT', os.getenv('DB_PORT'))}"
    f"/{os.getenv('REFERENCE_DB_NAME', 'reference_service')}"
)

TIMETRACK_DB_URL = (
    f"mysql+pymysql://{os.getenv('TIMETRACK_DB_USER', os.getenv('DB_USER'))}"
    f":{os.getenv('TIMETRACK_DB_PASSWORD', os.getenv('DB_PASSWORD'))}"
    f"@{os.getenv('TIMETRACK_DB_HOST', os.getenv('DB_HOST'))}"
    f":{os.getenv('TIMETRACK_DB_PORT', os.getenv('DB_PORT'))}"
    f"/{os.getenv('TIMETRACK_DB_NAME', 'timetrack_service')}"
)

salary_engine = create_engine(SALARY_DB_URL)
auth_engine = create_engine(AUTH_DB_URL)
reference_engine = create_engine(REFERENCE_DB_URL)
timetrack_engine = create_engine(TIMETRACK_DB_URL)

SalarySessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=salary_engine)
AuthSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=auth_engine)
ReferenceSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=reference_engine
)
TimetrackSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=timetrack_engine
)


class Base(DeclarativeBase):
    pass


class AuthBase(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:  # pyright: ignore[reportInvalidTypeForm]
    db = SalarySessionLocal()
    try:
        yield db  # pyright: ignore[reportReturnType]
    finally:
        db.close()


def get_auth_db() -> Generator[Session, None, None]:  # pyright: ignore[reportInvalidTypeForm]
    db = AuthSessionLocal()
    try:
        yield db  # pyright: ignore[reportReturnType]
    finally:
        db.close()


def get_reference_db() -> Generator[Session, None, None]:  # pyright: ignore[reportInvalidTypeForm]
    db = ReferenceSessionLocal()
    try:
        yield db  # pyright: ignore[reportReturnType]
    finally:
        db.close()


def get_timetrack_db() -> Generator[Session, None, None]:  # pyright: ignore[reportInvalidTypeForm]
    db = TimetrackSessionLocal()
    try:
        yield db  # pyright: ignore[reportReturnType]
    finally:
        db.close()


def init_db():
    """Create salary tables explicitly when needed.

    The application does not call this on import because production/local dumps
    already contain schema, foreign keys, and cross-database references.
    """
    Base.metadata.create_all(bind=salary_engine)


DbSession = Annotated[Session, Depends(get_db)]
AuthDbSession = Annotated[Session, Depends(get_auth_db)]
ReferenceDbSession = Annotated[Session, Depends(get_reference_db)]
TimetrackDbSession = Annotated[Session, Depends(get_timetrack_db)]
