"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import articles, blogger, dashboard, health, ideas
from app.api import publish_log as publish_log_api
from app.api import research as research_api
from app.api import schedule as schedule_api
from app.api import settings as settings_api
from app.config import get_settings
from db.base import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    from scheduler import start_scheduler, shutdown_scheduler
    start_scheduler()
    yield
    shutdown_scheduler()


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
    app.include_router(articles.router)
    app.include_router(settings_api.router)
    app.include_router(dashboard.router)
    app.include_router(blogger.router)
    app.include_router(publish_log_api.router)
    app.include_router(schedule_api.router)
    return app


app = create_app()
