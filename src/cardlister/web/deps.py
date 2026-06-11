"""FastAPI dependencies: pull settings/database from app state, hand out a repo."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from cardlister.config import Settings
from cardlister.db.base import Database
from cardlister.db.repository import CardRepository


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_database(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


def get_session(request: Request) -> Iterator[Session]:
    database = get_database(request)
    with database.session() as session:
        yield session


def get_repo(request: Request) -> Iterator[CardRepository]:
    database = get_database(request)
    with database.session() as session:
        yield CardRepository(session)
