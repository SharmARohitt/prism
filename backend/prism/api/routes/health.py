"""Health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from prism import __version__
from prism.config import get_settings
from prism.llm.provider import get_provider
from prism.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check — reports service status, version, and LLM availability."""
    settings = get_settings()
    provider = get_provider()
    llm_available = await provider.is_available()

    return HealthResponse(
        status="ok",
        version=__version__,
        database="sqlite" if settings.is_sqlite else "postgresql",
        llm_provider=settings.llm_provider,
        llm_model=settings.ollama_model,
        llm_available=llm_available,
    )


@router.get("/ready")
async def readiness_check():
    """Readiness check — verifies the service can accept requests."""
    return {"ready": True}
