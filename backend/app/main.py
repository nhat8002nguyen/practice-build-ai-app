from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin_chunks import router as admin_chunks_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.drafts import router as drafts_router
from app.api.health import router as health_router
from app.api.tickets import router as tickets_router
from app.core.config import settings, validate_production_settings
from app.core.db import Base, engine
from app.core.redis import redis_client
from app.models import entities


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_production_settings(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield
    finally:
        await redis_client.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(documents_router)
    app.include_router(admin_chunks_router)
    app.include_router(chat_router)
    app.include_router(drafts_router)
    app.include_router(tickets_router)
    return app


app = create_app()
