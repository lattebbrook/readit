"""ReadIt API — a forum where everyone except you is generated."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_admin,
    routes_auth,
    routes_boards,
    routes_content,
    routes_media,
    routes_users,
)
from app.config import settings
from app.db import db, seed
from app.services import simulation

logger = logging.getLogger("readit")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.persist and db.load_snapshot():
        logger.info("Restored snapshot from %s", settings.snapshot_path)

    summary = seed.bootstrap()
    logger.info("Bootstrap: %s", summary)

    async def warm_up() -> None:
        """Fill empty boards in the background so the first page load is not blank."""
        with contextlib.suppress(Exception):
            await seed.seed_content()

    warm_task = asyncio.create_task(warm_up())

    if settings.simulation_enabled:
        simulation.engine.start()
        logger.info("Simulation engine running (tick ~%.0fs)", settings.tick_seconds)

    try:
        yield
    finally:
        warm_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await warm_task
        await simulation.engine.stop()
        if settings.persist:
            with contextlib.suppress(Exception):
                db.save_snapshot()
                logger.info("Snapshot saved to %s", settings.snapshot_path)


def create_app() -> FastAPI:
    app = FastAPI(
        title="ReadIt",
        description="An AI-run forum simulator.",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_origins if origin.strip()],
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(routes_auth.router)
    app.include_router(routes_users.router)
    app.include_router(routes_boards.router)
    app.include_router(routes_content.router)
    app.include_router(routes_media.router)
    app.include_router(routes_admin.public_router)
    app.include_router(routes_admin.router)

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        return {
            "ok": True,
            "collections": db.stats(),
            "simulation": simulation.engine.status(),
        }

    return app


app = create_app()
