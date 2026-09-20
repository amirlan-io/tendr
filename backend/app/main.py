"""Точка входа FastAPI."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/admin") or request.url.path.startswith("/api/account"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    get_llm()
    get_parser()
    get_discovery()
    yield
    await close_llm()
    await close_parser()
    await close_discovery()


def create_app(*, test_mode: bool = False) -> FastAPI:
    settings = get_settings()
    allow_docs = settings.app_env in {"dev", "test"} or test_mode or settings.enable_openapi_in_prod
    app = FastAPI(
        title="Tendr API",
        version="0.1.0",
        description="AI-ассистент для участия МСБ в госзакупках РК",
        lifespan=lifespan,
        docs_url="/docs" if allow_docs else None,
        redoc_url="/redoc" if allow_docs else None,
        openapi_url="/openapi.json" if allow_docs else None,
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_frontend_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Accept-Language", "Authorization", "Content-Type", "X-Client-Id", "X-Admin-Key"],
    )

    allowed_hosts = settings.allowed_hosts_list
    if settings.app_env in {"dev", "test"} or test_mode:
        allowed_hosts = ["testserver", "localhost", "127.0.0.1", "0.0.0.0", *allowed_hosts]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

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
