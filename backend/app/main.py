"""Точка входа FastAPI."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api import (
    account,
    admin,
    applications,
    b2g,
    browser_actions,
    discovery,
    health,
    lots,
    products,
)
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.llm import close_llm, get_llm
from app.services.discovery import close_discovery, get_discovery
from app.services.goszakup_parser import close_parser, get_parser


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # Прогрев провайдеров
    get_llm()
    get_parser()
    get_discovery()
    yield
    await close_llm()
    await close_parser()
    await close_discovery()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Tendr API",
        version="0.1.0",
        description="AI-ассистент для участия МСБ в госзакупках РК",
        lifespan=lifespan,
    )
    allowed_origins = [
        item.strip()
        for item in settings.allowed_frontend_origins.split(",")
        if item.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "0.0.0.0", "tendr.local"],
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(lots.router, prefix="/api")
    app.include_router(account.router, prefix="/api")
    app.include_router(discovery.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    app.include_router(b2g.router, prefix="/api")
    app.include_router(products.router, prefix="/api")
    app.include_router(applications.router, prefix="/api")
    app.include_router(browser_actions.router, prefix="/api")
    return app


app = create_app()
