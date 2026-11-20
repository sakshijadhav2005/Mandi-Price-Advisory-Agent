from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateTable
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
    _allow_null(engine, "users", "phone")  # Google sign-in accounts have no phone number
    _create_missing_indexes(engine)


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


def _allow_null(engine: Engine, table_name: str, column: str) -> None:
    """Drop NOT NULL from a column that the model now declares nullable."""
    insp = inspect(engine)
    if not insp.has_table(table_name):
        return
    col = next((c for c in insp.get_columns(table_name) if c["name"] == column), None)
    if col is None or col["nullable"]:
        return
    table = Base.metadata.tables[table_name]
    with engine.begin() as conn:
        if engine.dialect.name != "sqlite":
            conn.execute(text(f"ALTER TABLE {table_name} ALTER COLUMN {column} DROP NOT NULL"))
            return
        # SQLite cannot alter a column: copy into a new table, drop the old one, rename the new one
        # into place (the rename keeps other tables' foreign keys pointing at "users").
        tmp = f"{table_name}__new"
        conn.execute(text(str(CreateTable(table).compile(engine)).replace(f"CREATE TABLE {table_name}", f"CREATE TABLE {tmp}", 1)))
        cols = ", ".join(c.name for c in table.columns)
        conn.execute(text(f"INSERT INTO {tmp} ({cols}) SELECT {cols} FROM {table_name}"))
        conn.execute(text(f"DROP TABLE {table_name}"))
        conn.execute(text(f"ALTER TABLE {tmp} RENAME TO {table_name}"))


def _create_missing_indexes(engine: Engine) -> None:
    """Indexes for columns added by _add_missing_columns (and tables rebuilt by _allow_null)."""
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            for index in table.indexes:
                index.create(conn, checkfirst=True)


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
