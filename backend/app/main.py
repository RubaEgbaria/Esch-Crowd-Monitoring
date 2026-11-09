"""FastAPI application factory.

Run with:  uvicorn app.main:create_app --factory --port 8000   (from backend/)
"""
from __future__ import annotations

import base64
import logging
import secrets
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import drive as drive_api
from .api import live as live_api
from .api import meta as meta_api
from .api import runs as runs_api
from .errors import AppError
from .services import Services
from .settings import Settings, load_settings


log = logging.getLogger(__name__)


def seed_runs(settings: Settings) -> None:
    """Copy pre-processed runs (seed/runs/<id>, seed/cache/<id>) that are not there yet.

    Used on hosted servers whose disk is wiped on restart, so the baseline run
    is always available without uploading or re-running YOLO.
    """
    seed = settings.seed_dir
    if seed is None or not (seed / "runs").is_dir():
        return
    settings.ensure_dirs()
    for run in sorted((seed / "runs").iterdir()):
        if not (run / "run.json").is_file() or (settings.runs_dir / run.name).exists():
            continue
        shutil.copytree(run, settings.runs_dir / run.name)
        cache = seed / "cache" / run.name
        if cache.is_dir() and not (settings.cache_dir / run.name).exists():
            shutil.copytree(cache, settings.cache_dir / run.name)
        log.info("Seeded run %s", run.name)


def create_app(settings: Settings | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = settings or load_settings()
    seed_runs(settings)
    services = Services(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        services.start()
        yield
        services.stop()

    app = FastAPI(title="Crowd Monitoring: LiDAR + Camera Fusion", version=__version__, lifespan=lifespan)
    app.state.services = services

    if settings.app_password:
        password = settings.app_password

        @app.middleware("http")
        async def _basic_auth(request: Request, call_next):
            """One shared password for the whole site (any user name)."""
            if request.url.path == "/api/health" or request.method == "OPTIONS":
                return await call_next(request)
            ok = False
            header = request.headers.get("authorization", "")
            if header.lower().startswith("basic "):
                try:
                    _, _, given = base64.b64decode(header[6:]).decode("utf-8").partition(":")
                    ok = secrets.compare_digest(given.encode(), password.encode())
                except (ValueError, UnicodeDecodeError):
                    ok = False
            if not ok:
                return Response("Password required", status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="Crowd Monitoring"'})
            return await call_next(request)

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
    if settings.web_dir is not None and (settings.web_dir / "index.html").is_file():
        # the built Flutter app, same origin as the API (registered last: the API wins)
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")
    return app
