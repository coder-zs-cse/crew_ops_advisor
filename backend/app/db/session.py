"""Engine and session factory."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from .models import Base

_engine = None
_SessionLocal: sessionmaker | None = None


def _connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        # The scheduler writes from its own thread.
        return {"check_same_thread": False}
    return {}


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            echo=settings.db_echo,
            future=True,
            pool_pre_ping=settings.is_postgres,
            connect_args=_connect_args(settings.database_url),
        )
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, class_=Session
        )
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    Base.metadata.create_all(bind=get_engine())


def healthcheck() -> dict:
    from sqlalchemy import text

    settings = get_settings()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "dialect": get_engine().dialect.name, "url_scheme": settings.database_url.split("://")[0]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
