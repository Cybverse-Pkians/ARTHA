"""Engine and session factory."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from .models import Base

_engine = None
_factory = None


def get_engine():
    global _engine
    if _engine is None:
        # SQLite needs check_same_thread=False under a threaded server; Postgres
        # ignores it. The local demo uses SQLite, deployment uses Postgres.
        kwargs = {"future": True, "pool_pre_ping": True}
        if settings.database_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs.pop("pool_pre_ping")
        _engine = create_engine(settings.database_url, **kwargs)
    return _engine


def get_session_factory():
    global _factory
    if _factory is None:
        _factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _factory


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all() -> None:
    """Create the schema. Alembic owns migrations in deployment."""
    Base.metadata.create_all(get_engine())
