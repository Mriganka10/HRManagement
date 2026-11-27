"""FastAPI application factory: middleware, error handlers, routers, static files, startup seeding."""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, db
from .api import auth as auth_api
from .api import candidate as candidate_api
from .api import employee as employee_api
from .api import hr_operations, hr_people, hr_recruitment
from .api import pages as pages_api
from .engines.guardrails import RateLimited
from .services import ServiceError
from .services.demo import seed_reference_data
from .settings import get_settings

STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = logging.getLogger("hr_management")
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def create_app() -> FastAPI:
    cfg = get_settings()
    if cfg.secret_key == "dev-only-change-me":
        if cfg.is_production:
            raise RuntimeError("HRM_SECRET_KEY must be set in production.")
        logger.warning("HRM_SECRET_KEY is not set — using an insecure development key.")
    db.init_db()
    seed_reference_data()

    app = FastAPI(title=f"{cfg.company_name} HR Management", version=__version__,
                  docs_url=None if cfg.is_production else "/docs", redoc_url=None)

    @app.middleware("http")
    async def security(request: Request, call_next):
        # Cross-site request protection on top of SameSite=Lax cookies: unsafe requests
        # that carry an Origin header must come from this site.
        if request.method in UNSAFE and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc not in {request.url.netloc, urlparse(get_settings().public_base_url).netloc}:
                return JSONResponse({"detail": "Cross-site request blocked."}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), payment=(), microphone=(self)")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        if get_settings().cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    @app.exception_handler(RateLimited)
    async def rate_limited(_: Request, exc: RateLimited) -> JSONResponse:
        return JSONResponse({"detail": f"Too many attempts. Try again in {max(1, exc.retry_after // 60)} minute(s)."},
                            status_code=429, headers={"Retry-After": str(exc.retry_after)})

    @app.get("/health", include_in_schema=False)
    def health() -> dict:
        db.fetch_one("SELECT 1 AS ok")  # the load balancer only routes to tasks that can reach the database
        return {"status": "ok", "version": __version__}

    for router in (pages_api.router, auth_api.router, candidate_api.router, employee_api.router,
                   hr_recruitment.router, hr_people.router, hr_operations.router):
        app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
