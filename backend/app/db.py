"""Database engine and session management."""
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
    else:  # PostgreSQL: bound every statement so one bad query cannot hang a worker
        kwargs = {"connect_args": {"options": f"-c statement_timeout={get_settings().db_statement_timeout_ms}"}}
    engine = create_engine(url, pool_pre_ping=True, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # enforce foreign keys in SQLite
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(target: Engine | None = None) -> None:
    from . import models  # noqa: F401  (register tables)
    Base.metadata.create_all(target or engine)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
