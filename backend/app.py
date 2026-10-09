"""CampusVision AI — FastAPI application entry point.

Run: uvicorn backend.app:app --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend import config, database as db
from backend.routes import events, metrics, videos, zones
from backend.workers.video_worker import VideoWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(worker: VideoWorker | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init_db()
        app.state.worker.start()
        yield
        app.state.worker.stop()

    app = FastAPI(title="CampusVision AI", version="0.1.0", lifespan=lifespan)
    app.state.worker = worker or VideoWorker()
    for module in (videos, metrics, events, zones):
        app.include_router(module.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
