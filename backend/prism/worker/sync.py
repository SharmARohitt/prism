"""Auto-sync scheduler for keeping repository mirrors up to date.

Problem: PRISM is event-driven. Without a GitHub webhook, new commits are
never discovered. This module adds a lightweight background polling loop
that periodically checks every connected repository for new commits and
automatically triggers incremental indexing when changes are found.

Design:
- Pure asyncio — no external scheduler (APScheduler, Celery, etc.).
- Single asyncio.Task started in the app lifespan.
- One git fetch per repository per interval — minimal network usage.
- Detects new commits by comparing stored head_commit_sha vs. remote head.
- Only enqueues a new job if the SHA actually changed (idempotent).
- Respects existing QUEUED/RUNNING jobs — never double-enqueues.
- Honours SYNC_INTERVAL_SECONDS=0 to disable entirely.
- Staggered per-repo checks to avoid thundering-herd on startup.
- Updates Branch.last_synced_at and Repository.updated_at on each check.
- Emits structured log events for every sync action (new commit or up-to-date).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from prism.config import get_settings
from prism.core.git_mirror import GitMirror
from prism.database import get_session
from prism.logging_config import get_logger
from prism.models import (
    AnalysisJob,
    Branch,
    IndexStatus,
    IndexVersion,
    JobStatus,
    JobType,
    Repository,
)

logger = get_logger("prism.sync")


class AutoSyncScheduler:
    """Background service that polls repositories for new commits.

    Usage:
        scheduler = AutoSyncScheduler()
        await scheduler.start()     # begin polling loop
        ...
        await scheduler.stop()      # graceful shutdown
    """

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        settings = get_settings()
        if settings.sync_interval_seconds <= 0:
            logger.info("auto_sync_disabled", reason="SYNC_INTERVAL_SECONDS=0")
            return

        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "auto_sync_started",
            interval_seconds=settings.sync_interval_seconds,
            batch_size=settings.sync_batch_size,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("auto_sync_stopped")

    async def _loop(self) -> None:
        """Main polling loop.

        On first startup, waits 30 seconds before the first check so the
        server can finish initialising. After that, runs every sync_interval
        seconds regardless of how long the check took.
        """
        settings = get_settings()
        interval = settings.sync_interval_seconds

        # Grace period on startup — let the app finish initialising
        await asyncio.sleep(30)

        while self._running:
            next_run_at = asyncio.get_event_loop().time() + interval
            try:
                await self._check_all_repositories()
            except Exception as exc:
                logger.error("auto_sync_loop_error", error=str(exc))

            # Sleep until the next scheduled run (accounting for check duration)
            now = asyncio.get_event_loop().time()
            sleep_for = max(0.0, next_run_at - now)
            try:
                await asyncio.sleep(sleep_for)
            except asyncio.CancelledError:
                break

    async def _check_all_repositories(self) -> None:
        """Fetch and check every active repository for new commits."""
        settings = get_settings()
        batch_size = settings.sync_batch_size

        async with get_session() as session:
            result = await session.execute(
                select(Repository)
                .where(Repository.is_active == True)
                .order_by(Repository.updated_at.asc())  # oldest-synced first
                .limit(batch_size)
            )
            repos = result.scalars().all()
            repo_data = [
                {"id": r.id, "url": r.url, "full_name": r.full_name}
                for r in repos
            ]

        if not repo_data:
            return

        logger.info("auto_sync_pass", repo_count=len(repo_data))

        # Check repos with a small stagger to spread network load
        for i, repo_info in enumerate(repo_data):
            if not self._running:
                break
            try:
                await self._check_repository(repo_info)
            except Exception as e:
                logger.warning(
                    "auto_sync_repo_error",
                    repo=repo_info["full_name"],
                    error=str(e),
                )
            # 2-second stagger between repos to avoid hitting rate limits
            if i < len(repo_data) - 1:
                await asyncio.sleep(2)

    async def _check_repository(self, repo_info: dict) -> None:
        """Check one repository for new commits. Enqueues incremental index if needed."""
        repo_id = repo_info["id"]
        url = repo_info["url"]
        full_name = repo_info["full_name"]

        mirror = GitMirror(repo_id, url)

        if not mirror.exists:
            # Mirror missing — trigger a fresh ingestion
            logger.info("auto_sync_mirror_missing", repo=full_name)
            await self._enqueue_if_idle(repo_id, "initial_ingestion", commit_sha=None)
            return

        # Fetch remote changes into the local mirror
        try:
            await mirror.fetch()
        except Exception as e:
            logger.warning("auto_sync_fetch_failed", repo=full_name, error=str(e))
            return

        # Get the latest remote HEAD SHA
        try:
            remote_sha = await mirror.get_head_sha()
        except Exception:
            return

        # Get stored head_commit_sha from the DB
        async with get_session() as session:
            # Check Branch for stored head SHA
            branch_result = await session.execute(
                select(Branch).where(
                    Branch.repository_id == repo_id,
                    Branch.is_default == True,
                )
            )
            branch = branch_result.scalar_one_or_none()
            stored_sha = branch.head_commit_sha if branch else None

            # Also check IndexVersion in case Branch.head_commit_sha is not set
            iv_result = await session.execute(
                select(IndexVersion)
                .where(IndexVersion.repository_id == repo_id)
                .where(IndexVersion.status == IndexStatus.COMPLETED)
                .order_by(IndexVersion.created_at.desc())
                .limit(1)
            )
            latest_iv = iv_result.scalar_one_or_none()
            indexed_sha = latest_iv.commit_sha if latest_iv else None

        # If the remote HEAD matches what we've already indexed, nothing to do
        if remote_sha and (remote_sha == stored_sha or remote_sha == indexed_sha):
            logger.debug(
                "auto_sync_up_to_date",
                repo=full_name,
                sha=remote_sha[:12],
            )
            # Still update last_synced_at so the UI shows a fresh timestamp
            await self._update_synced_at(repo_id, remote_sha)
            return

        # New commits detected — log and enqueue
        logger.info(
            "auto_sync_new_commits",
            repo=full_name,
            old_sha=(indexed_sha or stored_sha or "none")[:12],
            new_sha=remote_sha[:12] if remote_sha else "unknown",
        )

        # Update Branch head SHA
        await self._update_synced_at(repo_id, remote_sha)

        # Enqueue incremental index if no job is already running for this repo
        await self._enqueue_if_idle(repo_id, "incremental_index", commit_sha=remote_sha)

    async def _update_synced_at(self, repo_id: str, head_sha: str | None) -> None:
        """Update Branch.head_commit_sha and Branch.last_synced_at."""
        try:
            async with get_session() as session:
                branch_result = await session.execute(
                    select(Branch).where(
                        Branch.repository_id == repo_id,
                        Branch.is_default == True,
                    )
                )
                branch = branch_result.scalar_one_or_none()
                if branch:
                    if head_sha:
                        branch.head_commit_sha = head_sha
                    branch.last_synced_at = datetime.now(timezone.utc)
                    await session.commit()

                # Touch Repository.updated_at so the dashboard shows freshness
                repo_result = await session.execute(
                    select(Repository).where(Repository.id == repo_id)
                )
                repo = repo_result.scalar_one_or_none()
                if repo:
                    repo.updated_at = datetime.now(timezone.utc)
                    await session.commit()
        except Exception as e:
            logger.warning("auto_sync_update_failed", repo_id=repo_id, error=str(e))

    async def _enqueue_if_idle(
        self,
        repo_id: str,
        job_type_str: str,
        commit_sha: str | None,
    ) -> None:
        """Enqueue a job only if no job of the same type is already queued/running.

        This is the idempotency guard — calling it twice for the same repo
        will not create duplicate work.
        """
        job_type = JobType(job_type_str)

        async with get_session() as session:
            # Check for any active (queued or running) job of the same type
            existing = await session.execute(
                select(AnalysisJob).where(
                    AnalysisJob.repository_id == repo_id,
                    AnalysisJob.job_type == job_type,
                    AnalysisJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                )
            )
            if existing.scalar_one_or_none():
                logger.debug("auto_sync_job_already_active", repo_id=repo_id, job_type=job_type_str)
                return

            # Create the job record
            job_id = uuid4().hex
            job = AnalysisJob(
                id=job_id,
                repository_id=repo_id,
                job_type=job_type,
                status=JobStatus.QUEUED,
                commit_sha=commit_sha,
            )
            session.add(job)
            await session.commit()

        # Push onto the worker queue
        from prism.worker.tasks import get_job_queue
        queue = get_job_queue()
        await queue.enqueue({
            "job_id": job_id,
            "job_type": job_type.value,
            "repository_id": repo_id,
            "commit_sha": commit_sha,
            "pr_id": None,
            "base_sha": None,
            "head_sha": commit_sha,
            "pr_info": {},
        })

        logger.info(
            "auto_sync_job_enqueued",
            repo_id=repo_id,
            job_type=job_type_str,
            job_id=job_id,
            sha=(commit_sha or "")[:12],
        )


# ── Singleton ───────────────────────────────────────────────

_scheduler: AutoSyncScheduler | None = None


def get_sync_scheduler() -> AutoSyncScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AutoSyncScheduler()
    return _scheduler
