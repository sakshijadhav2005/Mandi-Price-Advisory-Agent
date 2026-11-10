from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.models import Base


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, **kwargs)


def init_db(engine: Engine | None = None) -> None:
    engine = engine or get_engine()
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine: Engine) -> None:
    """Minimal forward migration: add new nullable columns to existing tables.

    create_all() creates missing tables but never alters existing ones. For any
    schema change beyond adding a nullable column, use Alembic.
    """
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing and col.nullable:
                    conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}"))


def session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    session = session_factory(engine)()
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
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()
