"""FastAPI application factory: middleware, error handlers, routers and static files."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, db
from .api import auth as auth_api
from .api import candidate as candidate_api
from .api import hr as hr_api
from .api import pages as pages_api
from .engines.guardrails import RateLimited
from .services import ServiceError
from .settings import get_settings

STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = logging.getLogger("hr_management")


def create_app() -> FastAPI:
    cfg = get_settings()
    if cfg.secret_key == "dev-only-change-me":
        logger.warning("HRM_SECRET_KEY is not set — using an insecure development key.")
    db.init_db()

    app = FastAPI(title=f"{cfg.company_name} HR Management", version=__version__)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Camera stays off; the microphone is used only for optional voice answers in the interview.
        response.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), payment=(), microphone=(self)")
        if get_settings().cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    @app.exception_handler(RateLimited)
    async def rate_limited(_: Request, exc: RateLimited) -> JSONResponse:
        return JSONResponse(
            {"detail": f"Too many attempts. Try again in {max(1, exc.retry_after // 60)} minute(s)."},
            status_code=429, headers={"Retry-After": str(exc.retry_after)},
        )

    @app.get("/health", include_in_schema=False)
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    app.include_router(pages_api.router)
    app.include_router(auth_api.router)
    app.include_router(candidate_api.router)
    app.include_router(hr_api.router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
