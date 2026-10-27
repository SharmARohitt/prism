"""LLM provider abstraction.

Provides a unified interface for generating structured, constrained output
from language models. The default provider is Ollama, but the abstraction
allows adding other providers (OpenAI-compatible, self-hosted, etc.).

Key design principles:
- Never send credentials or secrets in prompts.
- Use constrained/structured JSON output where supported.
- Validate output against Pydantic schemas.
- Retry safely on malformed output — never silently accept bad output.
- Make the model configurable via environment variables.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel

from prism.config import get_settings
from prism.logging_config import get_logger

logger = get_logger("prism.llm")


@dataclass
class LLMResponse:
    text: str
    model: str
    success: bool
    error: str | None = None
    raw: dict[str, Any] | None = None


class LLMProvider(ABC):
    """Abstract LLM provider interface."""

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the LLM provider is reachable."""
        ...

    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = "", temperature: float = 0.1) -> LLMResponse:
        """Generate a text completion."""
        ...

    async def generate_json(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.1,
        schema: type[BaseModel] | None = None,
        max_retries: int = 2,
    ) -> tuple[dict[str, Any] | None, LLMResponse]:
        """
        Generate a structured JSON response with validation and retry.

        Returns (parsed_json | None, response).
        If parsing fails after max_retries, returns (None, response) with
        success=False — never silently accepts malformed output.
        """
        json_instruction = "\n\nRespond with a valid JSON object only. No markdown, no code fences, no commentary."

        if schema:
            schema_str = json.dumps(schema.model_json_schema(), indent=2)
            json_instruction += f"\n\nThe JSON must conform to this schema:\n{schema_str}"

        last_response: LLMResponse | None = None
        for attempt in range(max_retries + 1):
            full_prompt = prompt + json_instruction
            if attempt > 0:
                full_prompt += f"\n\nPrevious attempt produced invalid JSON. Please return valid JSON."

            response = await self.generate(full_prompt, system_prompt, temperature)
            last_response = response

            if not response.success:
                logger.warning("llm_generation_failed", attempt=attempt, error=response.error)
                continue

            # Try to parse JSON
            text = response.text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                lines = text.split("\n")
                # Remove first and last lines (fences)
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines).strip()

            try:
                parsed = json.loads(text)
                # Validate against schema if provided
                if schema:
                    try:
                        schema.model_validate(parsed)
                    except Exception as ve:
                        logger.warning("json_schema_validation_failed", attempt=attempt, error=str(ve))
                        if attempt < max_retries:
                            continue
                        return parsed, response  # Return parsed but unvalidated — let caller decide
                return parsed, response
            except json.JSONDecodeError as je:
                logger.warning("json_parse_failed", attempt=attempt, error=str(je), text_preview=text[:200])
                if attempt < max_retries:
                    continue

        # All retries exhausted
        return None, last_response or LLMResponse(text="", model=self.model_name, success=False, error="No response generated")


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    def __init__(self, base_url: str | None = None, model: str | None = None):
        settings = get_settings()
        self._base_url = base_url or settings.ollama_base_url
        self._model = model or settings.ollama_model

    @property
    def model_name(self) -> str:
        return self._model

    async def is_available(self) -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m.get("name", "") for m in data.get("models", [])]
                    # Check if our model (or its base name) is available
                    model_base = self._model.split(":")[0]
                    available = any(model_base in m for m in models)
                    if not available and len(models) > 0:
                        # Model not installed but Ollama is running
                        logger.warning(
                            "ollama_model_not_installed",
                            model=self._model,
                            available_models=models,
                        )
                    return True  # Ollama is running — model may auto-pull
                return False
        except (httpx.ConnectError, httpx.TimeoutException, Exception) as e:
            logger.info("ollama_not_available", error=str(e))
            return False

    async def generate(self, prompt: str, system_prompt: str = "", temperature: float = 0.1) -> LLMResponse:
        """Generate a completion via Ollama's /api/generate endpoint."""
        try:
            payload = {
                "model": self._model,
                "prompt": prompt,
                "system": system_prompt or "You are a security-focused code analysis assistant. "
                "You analyze code changes and explain their security impact in clear, evidence-backed terms. "
                "You never claim something is safe without evidence. You distinguish confirmed findings, "
                "hypotheses, and missing evidence.",
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": 4096,
                },
            }

            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(f"{self._base_url}/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()

                return LLMResponse(
                    text=data.get("response", ""),
                    model=data.get("model", self._model),
                    success=True,
                    raw=data,
                )
        except httpx.ConnectError as e:
            return LLMResponse(text="", model=self._model, success=False, error=f"Cannot connect to Ollama at {self._base_url}: {e}")
        except httpx.TimeoutException as e:
            return LLMResponse(text="", model=self._model, success=False, error=f"Ollama request timed out: {e}")
        except Exception as e:
            return LLMResponse(text="", model=self._model, success=False, error=str(e))


class StubProvider(LLMProvider):
    """Fallback provider that returns structured responses without an LLM.

    Used when Ollama is not available. Produces honest, clearly-labelled
    deterministic analysis based on the evidence gathered — no fake LLM output.
    """

    @property
    def model_name(self) -> str:
        return "stub-analyzer"

    async def is_available(self) -> bool:
        return True

    async def generate(self, prompt: str, system_prompt: str = "", temperature: float = 0.1) -> LLMResponse:
        return LLMResponse(
            text="{}",
            model=self.model_name,
            success=True,
            raw={"note": "stub provider — no LLM available"},
        )


def get_provider() -> LLMProvider:
    """Factory that returns the configured LLM provider."""
    settings = get_settings()
    if settings.llm_provider == "ollama":
        return OllamaProvider()
    return StubProvider()


async def get_available_provider() -> LLMProvider:
    """Return a provider, falling back to StubProvider if LLM is not available."""
    provider = get_provider()
    if await provider.is_available():
        return provider
    logger.info("llm_not_available_using_stub", requested_model=provider.model_name)
    return StubProvider()
