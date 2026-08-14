"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import dashboard, health, ideas
from app.api import research as research_api
from app.api import settings as settings_api
from app.config import get_settings
from db.base import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(ideas.router)
    app.include_router(research_api.router)
    app.include_router(settings_api.router)
    app.include_router(dashboard.router)
    return app


app = create_app()
