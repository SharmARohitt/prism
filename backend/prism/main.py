"""PRISM FastAPI application entry point.

Wires up all routers, middleware, database, worker, and lifecycle events.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from prism import __version__
from prism.api.routes import commits, graph, health, mcp, repositories, settings as settings_routes, webhooks
from prism.config import get_settings
from prism.database import close_db, init_db
from prism.logging_config import get_logger, setup_logging
from prism.worker.sync import get_sync_scheduler
from prism.worker.tasks import get_job_queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown."""
    # Startup
    setup_logging()
    logger = get_logger("prism.main")
    logger.info("prism_starting", version=__version__)

    # Initialize database
    await init_db()
    logger.info("database_initialized")

    # Start background worker
    queue = get_job_queue()
    await queue.start()
    logger.info("worker_started")

    # Start auto-sync scheduler (polls repos for new commits)
    sync = get_sync_scheduler()
    await sync.start()
    logger.info("auto_sync_scheduler_started")

    yield

    # Shutdown
    logger.info("prism_shutting_down")
    await sync.stop()
    await queue.stop()
    await close_db()
    logger.info("prism_stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="PRISM",
        description="Persistent Repository Intelligence & Security Mapping",
        version=__version__,
        lifespan=lifespan,
    )

    # CORS — allow the frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            settings.frontend_url,
            "http://localhost:3000",
            "http://localhost:3001",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(health.router)
    app.include_router(repositories.router)
    app.include_router(commits.router)
    app.include_router(graph.router)
    app.include_router(webhooks.router)
    app.include_router(mcp.router)
    app.include_router(settings_routes.router)

    return app


# Module-level app instance for uvicorn
app = create_app()
