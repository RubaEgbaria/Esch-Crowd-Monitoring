"""FastAPI application factory.

Run with:  uvicorn app.main:create_app --factory --port 8000   (from backend/)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .api import drive as drive_api
from .api import live as live_api
from .api import meta as meta_api
from .api import runs as runs_api
from .errors import AppError
from .services import Services
from .settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = settings or load_settings()
    services = Services(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        services.start()
        yield
        services.stop()

    app = FastAPI(title="Crowd Monitoring: LiDAR + Camera Fusion", version=__version__, lifespan=lifespan)
    app.state.services = services
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=settings.cors_origin_regex,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def _app_error(_req: Request, exc: AppError) -> JSONResponse:
        return JSONResponse({"error": exc.to_dict()}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        msg = f"{where}: {first.get('msg', 'invalid value')}" if where else first.get("msg", "Invalid request")
        return JSONResponse({"error": {"code": "invalid_request", "message": msg, "details": {}}},
                            status_code=422)

    app.include_router(meta_api.router)
    app.include_router(drive_api.router)
    app.include_router(runs_api.router)
    app.include_router(live_api.router)
    return app
