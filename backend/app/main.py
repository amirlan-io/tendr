"""Точка входа FastAPI."""

from __future__ import annotations

import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import (
    account,
    admin,
    applications,
    approvals,
    b2g,
    browser_actions,
    discovery,
    errors,
    health,
    lots,
    products,
    sandbox,
    suppliers,
    tenders,
)
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.rate_limit import RateLimitMiddleware
from app.llm import close_llm, get_llm
from app.services.discovery import close_discovery, get_discovery
from app.services.goszakup_parser import close_parser, get_parser
from app.services.analysis_jobs import recover_analysis_jobs, shutdown_analysis_jobs


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
        except HTTPException:
            # Ожидаемый ответ приложения (401/403/404…): его должен
            # обработать сам FastAPI. Глотать его нельзя — иначе штатная
            # проверка прав превратится в 500.
            raise
        except Exception as exc:  # noqa: BLE001 - последний рубеж
            # Необработанное исключение не должно теряться: пересылаем
            # владельцу и отдаём клиенту безопасный ответ без деталей.
            from app.services.error_reporter import get_reporter, scrub

            try:
                await get_reporter().report(
                    {
                        "name": type(exc).__name__,
                        "message": scrub(str(exc)),
                        "stack": scrub("".join(traceback.format_exception(exc))[:1200]),
                        "source": "backend",
                        "where": f"{request.method} {request.url.path}",
                    }
                )
            except Exception:  # noqa: BLE001 - репортер не должен ломать ответ
                pass
            logger_opt = __import__("loguru").logger
            logger_opt.exception("[unhandled] {} {}", request.method, request.url.path)
            return JSONResponse(
                status_code=500,
                content={"detail": "INTERNAL_ERROR"},
            )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if (
            request.url.path.startswith("/api/admin")
            or request.url.path.startswith("/api/account")
            or request.url.path.startswith("/api/suppliers")
            or request.url.path.startswith("/api/approvals")
            or request.url.path.startswith("/api/outreach")
            or request.url.path.startswith("/api/lots/analysis-jobs")
            or request.url.path.startswith("/api/lots/assistant")
        ):
            response.headers.setdefault("Cache-Control", "no-store")
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    get_llm()
    get_parser()
    get_discovery()
    await recover_analysis_jobs()
    yield
    await shutdown_analysis_jobs()
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
    # Лимит по IP на дорогостоящие эндпоинты: подделать его сменой
    # заголовка нельзя, в отличие от клиентского ключа внутри /api/browser.
    app.add_middleware(RateLimitMiddleware)
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
    # Сбор ошибок от клиента и тест канала уведомлений.
    app.include_router(errors.router, prefix="/api")
    # Песочница агента: прогон на реальных данных со следом и фильтрами.
    app.include_router(sandbox.router, prefix="/api")
    # Supplier Agent: поиск поставщиков, одобрения, исходящие, персонализация.
    app.include_router(suppliers.router, prefix="/api")
    app.include_router(approvals.router, prefix="/api")
    app.include_router(approvals.outreach_router, prefix="/api")
    app.include_router(tenders.router, prefix="/api")
    app.include_router(tenders.profile_router, prefix="/api")
    return app


app = create_app()
