from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from polymarket_edge.config import get_settings
from polymarket_edge.db.models import Base


def _engine_kwargs_for_url(url: str) -> dict[str, Any]:
    kwargs = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    elif "pooler.supabase.com" in url:
        kwargs["connect_args"] = {"prepare_threshold": None}
    return kwargs


def make_engine(database_url: str | None = None):
    settings = get_settings()
    url = database_url or settings.DATABASE_URL
    kwargs = _engine_kwargs_for_url(url)
    return create_engine(url, **kwargs)


def make_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=make_engine(database_url), expire_on_commit=False, future=True)


SessionLocal = make_session_factory


def init_db(database_url: str | None = None) -> None:
    engine = make_engine(database_url)
    Base.metadata.create_all(engine)


@contextmanager
def get_session(database_url: str | None = None) -> Iterator[Session]:
    factory = make_session_factory(database_url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
