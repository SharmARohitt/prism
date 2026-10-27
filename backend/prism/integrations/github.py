"""GitHub webhook integration.

Parses GitHub webhook payloads into normalized PRISM events.
Implements webhook signature verification.

This is the primary Git provider integration. GitLab and other providers
follow the same interface pattern.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from prism.config import get_settings
from prism.logging_config import get_logger
from prism.schemas import WebhookEvent

logger = get_logger("prism.github")


def verify_github_signature(payload_body: bytes, signature_header: str | None) -> bool:
    """Verify the X-Hub-Signature-256 header from GitHub webhooks."""
    settings = get_settings()
    secret = settings.github_webhook_secret or settings.webhook_secret
    if not secret or secret == "change-me-to-a-random-secret":
        # In development, skip verification if no real secret set
        logger.warning("webhook_secret_not_set", message="Skipping signature verification — no webhook secret configured")
        return True

    if not signature_header:
        return False

    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), payload_body, hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)


def parse_github_event(headers: dict[str, str], payload: dict[str, Any]) -> WebhookEvent | None:
    """Parse a GitHub webhook event into a normalized WebhookEvent."""
    event_type = headers.get("X-GitHub-Event", headers.get("x-github-event", ""))

    if event_type == "ping":
        return WebhookEvent(
            event_type="ping",
            repository_url=payload.get("repository", {}).get("clone_url", ""),
            repository_full_name=payload.get("repository", {}).get("full_name", ""),
            action="ping",
            raw_payload=payload,
        )

    repo_info = payload.get("repository", {})
    repo_url = repo_info.get("clone_url") or repo_info.get("html_url", "")
    repo_full_name = repo_info.get("full_name", "")

    if event_type == "pull_request":
        pr = payload.get("pull_request", {})
        action = payload.get("action", "")
        # Only process opened, synchronize (new commits), reopened
        if action not in ("opened", "synchronize", "reopened", "ready_for_review"):
            return None

        return WebhookEvent(
            event_type="pull_request",
            repository_url=repo_url,
            repository_full_name=repo_full_name,
            action=action,
            pr_number=pr.get("number"),
            pr_title=pr.get("title"),
            pr_author=pr.get("user", {}).get("login"),
            pr_body=pr.get("body"),
            base_sha=pr.get("base", {}).get("sha"),
            head_sha=pr.get("head", {}).get("sha"),
            base_branch=pr.get("base", {}).get("ref"),
            head_branch=pr.get("head", {}).get("ref"),
            raw_payload=payload,
        )

    if event_type == "push":
        return WebhookEvent(
            event_type="push",
            repository_url=repo_url,
            repository_full_name=repo_full_name,
            action="push",
            commit_sha=payload.get("after"),
            ref=payload.get("ref"),
            raw_payload=payload,
        )

    logger.info("unhandled_github_event", event_type=event_type)
    return None
