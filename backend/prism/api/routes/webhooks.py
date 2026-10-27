"""Webhook API routes.

Receives and processes Git provider webhooks. Idempotent: duplicate events
do not create duplicate analyses.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.database import get_db
from prism.integrations.github import parse_github_event, verify_github_signature
from prism.logging_config import get_logger
from prism.models import Repository
from prism.schemas import WebhookResponse
from prism.worker.tasks import create_and_enqueue_job

logger = get_logger("prism.api.webhooks")
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# Track processed event IDs for idempotency
# In production, use a database table or cache with TTL
_processed_events: set[str] = set()
_MAX_EVENT_CACHE = 1000


def _mark_event_processed(event_id: str) -> bool:
    """Returns True if this is a new event, False if already processed."""
    if event_id in _processed_events:
        return False
    _processed_events.add(event_id)
    # Evict old entries to prevent unbounded growth
    if len(_processed_events) > _MAX_EVENT_CACHE:
        _processed_events.discard(next(iter(_processed_events)))
    return True


@router.post("/github", response_model=WebhookResponse)
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(None),
    x_hub_signature_256: str | None = Header(None),
    x_github_delivery: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Receive and process a GitHub webhook event.

    Verifies signature, parses the event, finds the matching repository,
    and enqueues analysis. Idempotent: same delivery ID won't process twice.
    """
    body = await request.body()

    # Verify signature
    if not verify_github_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    # Parse event
    import json
    payload = json.loads(body) if body else {}

    # Idempotency check
    event_id = x_github_delivery or ""
    if event_id and not _mark_event_processed(event_id):
        return WebhookResponse(accepted=True, message="Event already processed.", event_type=x_github_event)

    # Parse into normalized event
    headers = {
        "X-GitHub-Event": x_github_event or "",
    }
    event = parse_github_event(headers, payload)

    if event is None:
        return WebhookResponse(accepted=False, message="Event type not supported.", event_type=x_github_event)

    if event.event_type == "ping":
        return WebhookResponse(accepted=True, message="Ping received.", event_type="ping")

    # Find matching repository
    # Match by URL or full_name
    repo_result = await db.execute(
        select(Repository).where(
            (Repository.url == event.repository_url)
            | (Repository.full_name == event.repository_full_name)
        )
    )
    repo = repo_result.scalar_one_or_none()

    if not repo:
        # Try to auto-connect if the URL matches a known pattern
        logger.info(
            "webhook_repo_not_found",
            url=event.repository_url,
            full_name=event.repository_full_name,
        )
        return WebhookResponse(
            accepted=False,
            message="Repository not connected. Connect it first via the API.",
            event_type=event.event_type,
        )

    # Enqueue analysis based on event type
    if event.event_type == "pull_request" and event.head_sha and event.base_sha:
        pr_info = {
            "pr_number": event.pr_number,
            "pr_title": event.pr_title,
            "pr_author": event.pr_author,
            "pr_body": event.pr_body,
        }
        await create_and_enqueue_job(
            repository_id=repo.id,
            job_type="pr_analysis",
            base_sha=event.base_sha,
            head_sha=event.head_sha,
            pr_info=pr_info,
        )
        return WebhookResponse(
            accepted=True,
            message=f"PR analysis started for PR #{event.pr_number}.",
            event_type=event.event_type,
        )

    elif event.event_type == "push" and event.commit_sha:
        await create_and_enqueue_job(
            repository_id=repo.id,
            job_type="incremental_index",
            commit_sha=event.commit_sha,
        )
        return WebhookResponse(
            accepted=True,
            message="Incremental indexing started for new commit.",
            event_type=event.event_type,
        )

    return WebhookResponse(
        accepted=False,
        message="Event type requires no action.",
        event_type=event.event_type,
    )
