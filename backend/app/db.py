"""SQLite database shared by the API process and the worker process."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

log = logging.getLogger("pdft.db")


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _set_sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    # WAL lets the API read while the worker writes.
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=10000")
    cur.close()


def _default_sql(column) -> str | None:
    """A literal DEFAULT for ALTER TABLE ADD COLUMN, or None if the column has none."""
    server_default = getattr(column.server_default, "arg", None)
    if server_default is not None:
        return str(getattr(server_default, "text", server_default))
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    value = default.arg
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def migrate(engine: Engine) -> list[str]:
    """Bring an existing database up to date with the models.

    create_all() only creates missing tables. A data folder from an older version keeps
    its tables, so add any columns and indexes they lack. Only additive changes are
    made; nothing is dropped or rewritten. Returns the changes made (for the log).
    """
    changes: list[str] = []
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            ddl = (f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" '
                   f"{column.type.compile(dialect=engine.dialect)}")
            default = _default_sql(column)
            if default is not None:
                ddl += f" DEFAULT {default}"
                if not column.nullable:
                    ddl += " NOT NULL"
            try:
                with engine.begin() as conn:
                    conn.exec_driver_sql(ddl)
                changes.append(f"{table.name}.{column.name}")
            except OperationalError as e:
                # The other process (API or worker) may have added it a moment ago.
                if "duplicate column" not in str(e).lower():
                    raise
        for index in table.indexes:
            try:
                with engine.begin() as conn:
                    index.create(conn, checkfirst=True)
            except SQLAlchemyError as e:
                # For example old duplicate rows: the app still works without the index.
                log.warning("could not create index %s: %s", index.name, e)
    if changes:
        log.info("database updated: added %s", ", ".join(changes))
    return changes


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        engine = create_engine(
            f"sqlite:///{settings.db_path}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        event.listen(engine, "connect", _set_sqlite_pragmas)
        from . import models  # noqa: F401  (register tables)

        Base.metadata.create_all(engine)
        migrate(engine)
        _engine = engine
        _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    """Used by tests after pointing PDFT_HOME somewhere else."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
