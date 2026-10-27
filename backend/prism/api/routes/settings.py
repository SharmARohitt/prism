"""Settings and integrations API routes."""

from __future__ import annotations

from fastapi import APIRouter

from prism.config import get_settings
from prism.integrations.scanners import get_scanner_adapters
from prism.llm.provider import get_provider
from prism.schemas import IntegrationStatus, LlmSettingsResponse, SettingsResponse

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
async def get_settings_response():
    """Get current settings: LLM config, integration status, database type."""
    settings = get_settings()
    provider = get_provider()
    llm_available = await provider.is_available()

    # Get scanner integration status
    integrations = []
    for adapter in get_scanner_adapters():
        integrations.append(IntegrationStatus(
            name=adapter.name,
            type="scanner",
            configured=adapter.is_configured,
            status="configured" if adapter.is_configured else "not_configured",
            details={},
        ))

    # Add GitHub integration status
    integrations.append(IntegrationStatus(
        name="github",
        type="git_provider",
        configured=bool(settings.github_webhook_secret and settings.github_webhook_secret != "change-me-to-a-random-secret"),
        status="configured" if settings.github_webhook_secret else "not_configured",
        details={},
    ))

    return SettingsResponse(
        llm=LlmSettingsResponse(
            provider=settings.llm_provider,
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            is_available=llm_available,
            model_info={} if not llm_available else {"name": provider.model_name},
        ),
        integrations=integrations,
        database_type="sqlite" if settings.is_sqlite else "postgresql",
    )
