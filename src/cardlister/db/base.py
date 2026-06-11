"""Database engine, session factory, and the declarative base."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Database:
    """Owns a SQLAlchemy engine and hands out sessions.

    Build one from :func:`cardlister.config.Settings.database_url` in the app, or with
    an in-memory URL in tests.
    """

    def __init__(self, url: str, *, echo: bool = False) -> None:
        connect_args: dict[str, object] = {}
        engine_kwargs: dict[str, object] = {"echo": echo, "future": True}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            if ":memory:" in url or url == "sqlite://":
                # Keep a single shared connection so an in-memory DB survives across
                # sessions within one Database instance (used in tests).
                engine_kwargs["poolclass"] = StaticPool
        self.engine: Engine = create_engine(url, connect_args=connect_args, **engine_kwargs)
        self._session_factory: sessionmaker[Session] = sessionmaker(
            bind=self.engine, expire_on_commit=False, future=True
        )

    def create_all(self) -> None:
        """Create all tables. Used in tests and first-run; production uses Alembic."""
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a session, committing on success and rolling back on error."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
