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

_RESERVED_API_PREFIXES = {"agent", "admin", "ingest", "ui"}
_LOCAL_CORS_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"


def _is_reserved_api_path(full_path: str) -> bool:
    return full_path.split("/", 1)[0] in _RESERVED_API_PREFIXES


try:
    APP_VERSION = pkg_version("ormah")
except PackageNotFoundError:
    APP_VERSION = "0.0.0"


import threading

# Embedding-backfill fallback (#32, council C2/CH1/CH2): when the scheduler fails
# to start, a daemon thread heals missing vectors off the bind path. It retries
# indefinitely with backoff (capped) so a persistent encoder outage recovers
# automatically when the encoder returns. Lifecycle is controlled by a stop event
# and a singleton guard; _fallback_degraded exposes a persistent outage to
# /admin/health while no scheduler exists.
_BACKFILL_FALLBACK_BASE_BACKOFF = 30.0  # seconds
_BACKFILL_FALLBACK_MAX_BACKOFF = 600.0  # seconds

_fallback_thread: threading.Thread | None = None
_fallback_stop_event: threading.Event | None = None
_fallback_degraded: bool = False


def _start_backfill_fallback(engine) -> None:
    """Heal missing vectors off a daemon thread when the scheduler is unavailable
    (#32). Off the bind path -- never blocks startup. Retries with backoff
    (capped) until the gap closes; never gives up, so a persistent encoder outage
    recovers automatically. Singleton: a second call while one thread is alive is
    a no-op, so a lifespan restart cannot accumulate concurrent fallbacks."""
    global _fallback_thread, _fallback_stop_event, _fallback_degraded
    import time

    if _fallback_thread is not None and _fallback_thread.is_alive():
        return  # singleton guard (CH1)

    stop_event = threading.Event()
    _fallback_stop_event = stop_event
    _fallback_degraded = False

    def _run():
        global _fallback_degraded
        from ormah.background.embedding_backfill import run_embedding_backfill

        delay = _BACKFILL_FALLBACK_BASE_BACKOFF
        attempt = 0
        while not stop_event.is_set():
            attempt += 1
            try:
                run_embedding_backfill(engine)
                _fallback_degraded = False  # gap closed (CH2: recovery observable)
                return
            except Exception as e:
                _fallback_degraded = True  # CH2: persistent outage is observable
                logger.warning(
                    "Embedding backfill fallback attempt %d failed: %s", attempt, e,
                )
                # Interruptible sleep -- shutdown wakes us immediately (CH1).
                if stop_event.wait(delay):
                    return
                delay = min(delay * 2, _BACKFILL_FALLBACK_MAX_BACKOFF)

    thread = threading.Thread(
        target=_run, name="embedding-backfill-fallback", daemon=True
    )
    _fallback_thread = thread
    thread.start()


def _stop_backfill_fallback() -> None:
    """Signal the fallback thread to stop and join it (CH1). Idempotent."""
    global _fallback_thread
    if _fallback_stop_event is not None:
        _fallback_stop_event.set()
    if _fallback_thread is not None:
        _fallback_thread.join(timeout=5.0)
        _fallback_thread = None


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

    # Start session watcher for Claude Code transcripts
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

    # Shutdown — stop the scheduler-independent backfill fallback if it is running
    _stop_backfill_fallback()

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
