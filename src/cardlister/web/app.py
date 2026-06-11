"""FastAPI application factory for the local review UI."""

from __future__ import annotations

from fastapi import FastAPI

from cardlister.config import Settings, get_settings
from cardlister.db.base import Database
from cardlister.web.routes import router


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    """Build the app. Tests inject an in-memory database; the CLI uses the real one."""
    settings = settings or get_settings()
    if database is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        database = Database(settings.database_url)
        database.create_all()

    app = FastAPI(title="cardlister")
    app.state.settings = settings
    app.state.database = database
    app.include_router(router)
    return app
