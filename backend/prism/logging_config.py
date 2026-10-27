"""Structured logging configuration with secret redaction."""

from __future__ import annotations

import logging
import re
from typing import Any

import structlog

from prism.config import get_settings

# Patterns to redact from log output
_SECRET_PATTERNS = [
    re.compile(r"(?i)(token|secret|password|api_key|apikey|authorization)\s*[=:]\s*\S+"),
    re.compile(r"(ghp_[a-zA-Z0-9]{36})"),  # GitHub PAT
    re.compile(r"(gho_[a-zA-Z0-9]{36})"),  # GitHub OAuth
    re.compile(r"(Bearer\s+[a-zA-Z0-9\-._~+/]+=*)"),
]

_REDACTED = "[REDACTED]"


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        for pattern in _SECRET_PATTERNS:
            value = pattern.sub(_REDACTED, value)
    return value


def _redact_processor(_logger, _method_name, event_dict):
    """structlog processor that redacts secrets from all string values."""
    for key, value in event_dict.items():
        event_dict[key] = _redact_value(value)
    return event_dict


def setup_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        level=level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "prism") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
