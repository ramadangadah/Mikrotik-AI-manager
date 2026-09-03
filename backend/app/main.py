from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.database import init_db
from app.core.scheduler import start_scheduler, stop_scheduler
from app.services.bootstrap import seed_default_admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)
settings = get_settings()

FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting %s", settings.APP_NAME)
    await init_db()
    await seed_default_admin()
    start_scheduler()
    yield
    stop_scheduler()
    logger.info("shutdown complete")


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    logger.exception("unhandled error on %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME}


# --- API routers ---
from app.api.routes import (  # noqa: E402
    alerts,
    assistant,
    auth,
    config_backups,
    cpes,
    discovery,
    dashboard,
    firmware,
    jobs,
    management_routers,
    networks,
    pppoe,
    scripts,
    settings as settings_routes,
    users,
)

for module in (
    auth, users, management_routers, networks, cpes, discovery,
    dashboard, alerts, firmware, jobs, pppoe, config_backups, settings_routes, scripts, assistant,
):
    app.include_router(module.router)


# --- frontend (built React app) ---
if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        candidate = os.path.join(FRONTEND_DIST, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
else:
    logger.warning("frontend build not found at %s - API-only mode", FRONTEND_DIST)
