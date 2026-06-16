"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ormah.api.middleware import AgentMiddleware
from ormah.api.routes_admin import router as admin_router
from ormah.api.routes_agent import router as agent_router
from ormah.api.routes_ingest import router as ingest_router
from ormah.api.routes_stats import router as stats_router
from ormah.api.routes_ui import router as ui_router
from ormah.background.maintenance_manager import MaintenanceManager
from ormah.config import settings
from ormah.engine.memory_engine import MemoryEngine
from ormah.logging_setup import setup_logging
from ormah.server_manager import LOG_DIR

setup_logging(
    log_format=settings.log_format,
    level=getattr(logging, settings.log_level),
    log_file=LOG_DIR / "ormah.log",
)
logger = logging.getLogger(__name__)

_RESERVED_API_PREFIXES = {"agent", "admin", "ingest", "stats", "ui"}
_LOCAL_CORS_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"


def _is_reserved_api_path(full_path: str) -> bool:
    return full_path.split("/", 1)[0] in _RESERVED_API_PREFIXES


try:
    APP_VERSION = pkg_version("ormah")
except PackageNotFoundError:
    APP_VERSION = "0.0.0"


# Embedding-backfill fallback: how many times the daemon thread retries the
# reconciliation (with exponential backoff) before giving up. The recurring job /
# sleep-cycle remains the long-term net; this only covers a scheduler that failed
# to start plus a transient encoder outage at boot.
_BACKFILL_FALLBACK_MAX_ATTEMPTS = 5
_BACKFILL_FALLBACK_BASE_BACKOFF = 30.0  # seconds
_BACKFILL_FALLBACK_MAX_BACKOFF = 600.0  # seconds


def _start_backfill_fallback(engine) -> None:
    """Run embedding reconciliation off a daemon thread when the scheduler is
    unavailable, so missing vectors are still healed without it (#32, council I1).
    Off the bind path -- never blocks startup. Retries with exponential backoff
    until the gap closes (``run_embedding_backfill`` raises while incomplete) or
    the attempt budget is exhausted, instead of a single one-shot."""
    import threading
    import time

    def _run():
        from ormah.background.embedding_backfill import run_embedding_backfill

        for attempt in range(_BACKFILL_FALLBACK_MAX_ATTEMPTS):
            try:
                run_embedding_backfill(engine)
                return  # gap closed (the job raises while it is still incomplete)
            except Exception as e:
                logger.warning(
                    "Embedding backfill fallback attempt %d/%d failed: %s",
                    attempt + 1, _BACKFILL_FALLBACK_MAX_ATTEMPTS, e,
                )
                if attempt + 1 < _BACKFILL_FALLBACK_MAX_ATTEMPTS:
                    time.sleep(min(
                        _BACKFILL_FALLBACK_BASE_BACKOFF * (2 ** attempt),
                        _BACKFILL_FALLBACK_MAX_BACKOFF,
                    ))

    threading.Thread(
        target=_run, name="embedding-backfill-fallback", daemon=True
    ).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting ormah server on port %d...", settings.port)
    logger.info("Initializing memory engine...")
    engine = MemoryEngine(settings)
    engine.startup()
    app.state.engine = engine
    logger.info("Memory engine ready.")

    # Start background scheduler if available
    try:
        from ormah.background.scheduler import start_scheduler

        logger.info("Starting background scheduler...")
        scheduler, tracker = start_scheduler(engine)
        app.state.scheduler = scheduler
        app.state.job_tracker = tracker
        app.state.maintenance_manager = MaintenanceManager(engine, tracker=tracker)
        logger.info("Background scheduler ready.")
    except Exception as e:
        logger.warning("Background scheduler not started: %s", e)

    # If the scheduler did not start, its recurring embedding_backfill job won't
    # run. Heal missing vectors off a daemon thread so recovery doesn't depend on
    # the scheduler (#32, council I1). Off the bind path -- never blocks startup.
    if not hasattr(app.state, "scheduler"):
        _start_backfill_fallback(engine)

    if not hasattr(app.state, "maintenance_manager"):
        app.state.maintenance_manager = MaintenanceManager(engine)

    # Start hippocampus file watchers
    try:
        from ormah.background.hippocampus import start_hippocampus, stop_hippocampus

        observers = start_hippocampus(engine)
        app.state.hippocampus_observers = observers
    except Exception as e:
        logger.warning("Hippocampus watchers not started: %s", e)

    # Start session watcher for agent transcripts
    try:
        from ormah.background.session_watcher import start_session_watcher, stop_session_watcher

        session_observers = start_session_watcher(engine)
        app.state.session_watcher_observers = session_observers
    except Exception as e:
        logger.warning("Session watcher not started: %s", e)

    yield

    # Shutdown — stop session watcher first
    if hasattr(app.state, "session_watcher_observers"):
        stop_session_watcher(app.state.session_watcher_observers)

    # Shutdown — stop hippocampus watchers
    if hasattr(app.state, "hippocampus_observers"):
        stop_hippocampus(app.state.hippocampus_observers)

    # Shutdown — wait for running jobs to finish (up to 10s)
    if hasattr(app.state, "scheduler"):
        app.state.scheduler.shutdown(wait=True)
    engine.shutdown()
    logger.info("Ormah stopped")


app = FastAPI(
    title="Ormah",
    description="Local-first, LLM-agnostic memory system for AI agents",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=_LOCAL_CORS_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AgentMiddleware)

app.include_router(agent_router)
app.include_router(admin_router)
app.include_router(stats_router)
app.include_router(ui_router)
app.include_router(ingest_router)

# Serve the built frontend bundled inside the package
_ui_dist = Path(__file__).resolve().parent / "ui_dist"
if _ui_dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_ui_dist / "assets"), name="static")

    _ui_dist_resolved = _ui_dist.resolve()

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA index.html for all non-API routes."""
        if _is_reserved_api_path(full_path):
            raise HTTPException(status_code=404, detail="Not found")
        file = (_ui_dist / full_path).resolve()
        try:
            file.relative_to(_ui_dist_resolved)
        except ValueError:
            return FileResponse(_ui_dist / "index.html")
        if file.is_file():
            return FileResponse(file)
        return FileResponse(_ui_dist / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "ormah.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
