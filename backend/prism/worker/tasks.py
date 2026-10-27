"""Background worker for async ingestion and analysis jobs.

Uses asyncio task queues for background processing of:
- Initial repository ingestion (clone, index, analyze)
- Incremental commit indexing
- PR review analysis

Jobs are tracked in the database with status, progress, and error info.
Webhook processing is idempotent: duplicate events don't create duplicate analyses.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from prism.core.git_mirror import GitMirror
from prism.core.indexer import CodeIndexer
from prism.core.review import ReviewEngine
from prism.database import get_session
from prism.logging_config import get_logger
from prism.models import (
    AnalysisJob,
    Branch,
    Commit,
    FileEntry,
    IndexStatus,
    IndexVersion,
    JobStatus,
    JobType,
    PullRequest,
    Relationship,
    ReviewState,
    Repository,
    Symbol,
)

logger = get_logger("prism.worker")


class JobQueue:
    """Simple async job queue with status tracking.

    For the initial single-user prototype, we use an in-process asyncio queue.
    This can be replaced with a proper task broker (Celery, RQ, etc.) for
    multi-user deployments without changing the job interface.
    """

    def __init__(self, concurrency: int = 2):
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []
        self._concurrency = concurrency
        self._running = False
        self._handlers: dict[str, Callable] = {}

    def register_handler(self, job_type: str, handler: Callable) -> None:
        self._handlers[job_type] = handler

    async def enqueue(self, job_data: dict) -> str:
        """Enqueue a job and return the job ID."""
        await self._queue.put(job_data)
        logger.info("job_enqueued", job_type=job_data.get("job_type"), job_id=job_data.get("job_id"))
        return job_data.get("job_id", "")

    async def start(self) -> None:
        """Start the worker pool."""
        if self._running:
            return
        self._running = True
        for i in range(self._concurrency):
            task = asyncio.create_task(self._worker_loop(i))
            self._tasks.append(task)
        logger.info("worker_pool_started", concurrency=self._concurrency)

    async def stop(self) -> None:
        """Stop the worker pool."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        logger.info("worker_pool_stopped")

    async def _worker_loop(self, worker_id: int) -> None:
        while self._running:
            try:
                job_data = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            job_id = job_data.get("job_id", "")
            job_type = job_data.get("job_type", "")

            try:
                await self._update_job_status(job_id, JobStatus.RUNNING)
                handler = self._handlers.get(job_type)
                if handler:
                    result = await handler(job_data)
                    await self._update_job_status(
                        job_id,
                        JobStatus.COMPLETED,
                        progress=100.0,
                        result_data=result or {},
                    )
                else:
                    await self._update_job_status(
                        job_id, JobStatus.FAILED,
                        error=f"No handler for job type: {job_type}",
                    )
            except Exception as e:
                logger.error("job_failed", job_id=job_id, job_type=job_type, error=str(e))
                await self._update_job_status(job_id, JobStatus.FAILED, error=str(e))

    async def _update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        progress: float | None = None,
        error: str | None = None,
        result_data: dict | None = None,
    ) -> None:
        """Update job status in the database."""
        async with get_session() as session:
            values: dict[str, Any] = {"status": status}
            if progress is not None:
                values["progress"] = progress
            if error is not None:
                values["error_message"] = error
            if result_data is not None:
                values["result_data"] = result_data
            if status == JobStatus.RUNNING:
                values["started_at"] = datetime.now(timezone.utc)
            if status in (JobStatus.COMPLETED, JobStatus.FAILED):
                values["completed_at"] = datetime.now(timezone.utc)

            await session.execute(
                update(AnalysisJob).where(AnalysisJob.id == job_id).values(**values)
            )
            await session.commit()


# ── Singleton job queue ─────────────────────────────────────

_job_queue: JobQueue | None = None


def get_job_queue() -> JobQueue:
    global _job_queue
    if _job_queue is None:
        from prism.config import get_settings
        settings = get_settings()
        _job_queue = JobQueue(concurrency=settings.worker_concurrency)
        _job_queue.register_handler(JobType.INITIAL_INGESTION.value, handle_initial_ingestion)
        _job_queue.register_handler(JobType.INCREMENTAL_INDEX.value, handle_incremental_index)
        _job_queue.register_handler(JobType.PR_ANALYSIS.value, handle_pr_analysis)
    return _job_queue


# ── Job handlers ────────────────────────────────────────────


async def handle_initial_ingestion(job_data: dict) -> dict[str, Any]:
    """Handle initial repository ingestion: clone, analyze structure, index."""
    repo_id = job_data["repository_id"]
    job_id = job_data["job_id"]

    logger.info("starting_initial_ingestion", repo_id=repo_id, job_id=job_id)

    # Get repository from DB
    async with get_session() as session:
        repo_result = await session.execute(
            select(Repository).where(Repository.id == repo_id)
        )
        repo = repo_result.scalar_one_or_none()
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")

        url = repo.url

    # Create/get Git mirror
    mirror = GitMirror(repo_id, url)
    if not mirror.exists:
        await mirror.fetch()
        # Clone happens in _get_repo when not exists

    # Get head SHA
    head_sha = await mirror.get_head_sha()

    # Create index version record
    async with get_session() as session:
        # Check if index version already exists for this commit
        existing = await session.execute(
            select(IndexVersion).where(
                IndexVersion.repository_id == repo_id,
                IndexVersion.commit_sha == head_sha,
            )
        )
        index_version = existing.scalar_one_or_none()

        if not index_version:
            index_version = IndexVersion(
                repository_id=repo_id,
                commit_sha=head_sha,
                status=IndexStatus.IN_PROGRESS,
                started_at=datetime.now(timezone.utc),
            )
            session.add(index_version)
            await session.commit()
            await session.refresh(index_version)
        else:
            # Update status
            index_version.status = IndexStatus.IN_PROGRESS
            index_version.started_at = datetime.now(timezone.utc)
            await session.commit()

    # Analyze structure
    structure = await mirror.analyze_structure(head_sha)

    # Index files
    indexer = CodeIndexer()
    index_result = await indexer.index_repository(mirror, head_sha)

    # Persist FileEntry, Symbol, and Relationship records to the database
    # so the dashboard can display real data instead of zeros.
    async with get_session() as session:
        # Make sure we have a fresh index version record
        iv_lookup = await session.execute(
            select(IndexVersion).where(IndexVersion.id == index_version.id)
        )
        iv_record = iv_lookup.scalar_one_or_none()

        if not iv_record:
            iv_record = IndexVersion(
                repository_id=repo_id,
                commit_sha=head_sha,
                status=IndexStatus.IN_PROGRESS,
                started_at=datetime.now(timezone.utc),
            )
            session.add(iv_record)
            await session.flush()

        # Clear any existing entries for this index version (idempotent re-ingest)
        await session.execute(
            FileEntry.__table__.delete().where(FileEntry.index_version_id == iv_record.id)
        )

        # Create FileEntry records and track file_entry_id by path
        file_entry_map: dict[str, str] = {}
        for indexed_file in index_result.files:
            fe = FileEntry(
                index_version_id=iv_record.id,
                path=indexed_file.path,
                content_hash=indexed_file.content_hash,
                language=indexed_file.language,
                line_count=indexed_file.line_count,
                is_supported=indexed_file.is_supported,
                is_test=indexed_file.is_test,
            )
            session.add(fe)
            await session.flush()
            file_entry_map[indexed_file.path] = fe.id

        # Also create FileEntry records for unsupported files (for completeness)
        for unsupported_path in index_result.unsupported:
            if unsupported_path not in file_entry_map:
                fe = FileEntry(
                    index_version_id=iv_record.id,
                    path=unsupported_path,
                    content_hash="",
                    language=None,
                    line_count=0,
                    is_supported=False,
                    is_test=False,
                )
                session.add(fe)
                await session.flush()
                file_entry_map[unsupported_path] = fe.id

        # Create Symbol records, tracking symbol_id by (file_path, name) for relationships
        symbol_id_map: dict[tuple[str, str], str] = {}
        for indexed_file in index_result.files:
            fe_id = file_entry_map.get(indexed_file.path)
            if not fe_id:
                continue
            for sym in indexed_file.symbols:
                sym_record = Symbol(
                    file_entry_id=fe_id,
                    index_version_id=iv_record.id,
                    name=sym.name,
                    qualified_name=sym.qualified_name,
                    symbol_type=sym.symbol_type,
                    start_line=sym.start_line,
                    end_line=sym.end_line,
                    signature=sym.signature,
                    content_hash=sym.content_hash,
                    docstring=sym.docstring,
                )
                session.add(sym_record)
                await session.flush()
                symbol_id_map[(indexed_file.path, sym.name)] = sym_record.id

        # Create Relationship records
        for indexed_file in index_result.files:
            for rel in indexed_file.relationships:
                # Try to resolve source symbol to a DB id
                src_id = None
                if rel.source_symbol and rel.source_file_path:
                    src_id = symbol_id_map.get((rel.source_file_path, rel.source_symbol))

                # Try to resolve target symbol (may be in a different file)
                tgt_id = None
                if rel.target_symbol:
                    # Search across all files for a matching symbol name
                    for (fpath, sname), sid in symbol_id_map.items():
                        if sname == rel.target_symbol:
                            tgt_id = sid
                            break

                rel_record = Relationship(
                    index_version_id=iv_record.id,
                    source_symbol_id=src_id,
                    target_symbol_id=tgt_id,
                    source_file_path=rel.source_file_path,
                    target_file_path=rel.target_file_path,
                    relation_type=rel.relation_type,
                    certainty=rel.certainty,
                    line_number=rel.line_number,
                )
                session.add(rel_record)

        # Update index version with summary counts
        iv_record.status = IndexStatus.COMPLETED
        iv_record.languages = structure.languages
        iv_record.files_indexed = len(file_entry_map)
        iv_record.symbols_indexed = len(symbol_id_map)
        iv_record.relationships_indexed = index_result.total_relationships
        iv_record.files_unsupported = index_result.unsupported
        iv_record.errors = index_result.errors
        iv_record.warnings = index_result.warnings
        iv_record.completed_at = datetime.now(timezone.utc)

        await session.commit()

    # Fetch and persist recent commit history so the dashboard and timeline work
    try:
        recent_commits = await mirror.get_commit_history(branch=None, limit=50)
        async with get_session() as session:
            for commit_info in recent_commits:
                # Check if commit already exists
                existing_commit = await session.execute(
                    select(Commit).where(
                        Commit.repository_id == repo_id,
                        Commit.sha == commit_info["sha"],
                    )
                )
                if existing_commit.scalar_one_or_none():
                    continue

                committed_at = None
                if commit_info.get("committed_at"):
                    try:
                        from datetime import datetime as dt
                        committed_at = dt.fromisoformat(
                            commit_info["committed_at"].replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        pass

                commit_record = Commit(
                    repository_id=repo_id,
                    sha=commit_info["sha"],
                    message=commit_info.get("message", ""),
                    author_name=commit_info.get("author_name", ""),
                    author_email=commit_info.get("author_email"),
                    committed_at=committed_at,
                    parent_shas=commit_info.get("parent_shas", []),
                    is_merge=commit_info.get("is_merge", False),
                    stats_additions=commit_info.get("stats_additions", 0),
                    stats_deletions=commit_info.get("stats_deletions", 0),
                    files_changed=commit_info.get("files_changed", []),
                )
                session.add(commit_record)

                # ── Link merge commit to PR ──────────────────────────────────────
                # GitHub merge commits have messages like:
                #   "Merge pull request #42 from branch"
                #   "Merge branch 'feature/x' into main (#42)"
                # GitLab: "Merge branch 'x' into 'main'\n\n!42"
                # We extract the PR number and link the commit back.
                if commit_info.get("is_merge"):
                    import re as _re
                    msg = commit_info.get("message", "")
                    pr_num = None
                    # GitHub pattern: "Merge pull request #42"
                    m = _re.search(r"Merge pull request #(\d+)", msg)
                    if m:
                        pr_num = int(m.group(1))
                    # Squash-merge pattern: "Title (#42)"
                    if not pr_num:
                        m = _re.search(r"\(#(\d+)\)\s*$", msg.split("\n")[0])
                        if m:
                            pr_num = int(m.group(1))
                    if pr_num:
                        # Look up the PR and set merge_commit_sha + state
                        pr_link = await session.execute(
                            select(PullRequest).where(
                                PullRequest.repository_id == repo_id,
                                PullRequest.pr_number == pr_num,
                            )
                        )
                        pr_rec = pr_link.scalar_one_or_none()
                        if pr_rec:
                            pr_rec.merge_commit_sha = commit_info["sha"]
                            pr_rec.state = "merged"
                            if committed_at:
                                pr_rec.merged_at = committed_at
            await session.commit()

        # Update the default branch head SHA
        async with get_session() as session:
            branch_result = await session.execute(
                select(Branch).where(
                    Branch.repository_id == repo_id,
                    Branch.is_default == True,
                )
            )
            default_branch = branch_result.scalar_one_or_none()
            if default_branch:
                default_branch.head_commit_sha = head_sha
                default_branch.last_synced_at = datetime.now(timezone.utc)
                await session.commit()
    except Exception as e:
        logger.warning("commit_history_fetch_failed", repo_id=repo_id, error=str(e))

    logger.info(
        "initial_ingestion_complete",
        repo_id=repo_id,
        commit=head_sha[:12],
        files=len(file_entry_map),
        symbols=len(symbol_id_map),
        relationships=index_result.total_relationships,
    )

    return {
        "commit_sha": head_sha,
        "files_indexed": len(file_entry_map),
        "symbols_indexed": len(symbol_id_map),
        "languages": structure.languages,
    }


async def handle_incremental_index(job_data: dict) -> dict[str, Any]:
    """Handle incremental indexing for a new commit."""
    repo_id = job_data["repository_id"]
    job_id = job_data["job_id"]
    commit_sha = job_data.get("commit_sha")

    logger.info("starting_incremental_index", repo_id=repo_id, commit=commit_sha)

    async with get_session() as session:
        repo_result = await session.execute(
            select(Repository).where(Repository.id == repo_id)
        )
        repo = repo_result.scalar_one_or_none()
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")
        url = repo.url

    mirror = GitMirror(repo_id, url)
    if not mirror.exists:
        # Need to do initial clone
        await mirror.fetch()

    # Fetch latest
    await mirror.fetch()
    head_sha = commit_sha or await mirror.get_head_sha()

    # Get previous index version for reuse comparison
    async with get_session() as session:
        prev = await session.execute(
            select(IndexVersion)
            .where(IndexVersion.repository_id == repo_id)
            .where(IndexVersion.status == IndexStatus.COMPLETED)
            .order_by(IndexVersion.created_at.desc())
            .limit(1)
        )
        prev_iv = prev.scalar_one_or_none()

    reuse_hashes = {}
    if prev_iv:
        # Get previous file hashes for reuse
        from prism.models import FileEntry
        async with get_session() as session:
            files = await session.execute(
                select(FileEntry).where(FileEntry.index_version_id == prev_iv.id)
            )
            for fe in files.scalars():
                reuse_hashes[fe.path] = fe.content_hash

    # Get diff from previous commit
    if prev_iv:
        diff = await mirror.get_diff(prev_iv.commit_sha, head_sha)
        changed_paths = [cf.path for cf in diff.changed_files]
    else:
        changed_paths = None

    indexer = CodeIndexer()
    result = await indexer.index_repository(
        mirror, head_sha, file_paths=changed_paths, reuse_hashes=reuse_hashes
    )

    # Create new index version
    async with get_session() as session:
        new_iv = IndexVersion(
            repository_id=repo_id,
            commit_sha=head_sha,
            status=IndexStatus.COMPLETED,
            files_indexed=len(result.files),
            symbols_indexed=result.total_symbols,
            relationships_indexed=result.total_relationships,
            files_unsupported=result.unsupported,
            errors=result.errors,
            warnings=result.warnings,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        session.add(new_iv)
        await session.commit()

    return {
        "commit_sha": head_sha,
        "files_indexed": len(result.files),
        "symbols_indexed": result.total_symbols,
        "reused_entries": len(reuse_hashes) - len(changed_paths) if prev_iv else 0,
    }


async def handle_pr_analysis(job_data: dict) -> dict[str, Any]:
    """Handle PR review analysis."""
    repo_id = job_data["repository_id"]
    job_id = job_data["job_id"]
    pr_id = job_data.get("pr_id")
    base_sha = job_data["base_sha"]
    head_sha = job_data["head_sha"]
    pr_info = job_data.get("pr_info", {})

    logger.info("starting_pr_analysis", repo_id=repo_id, base=base_sha[:12], head=head_sha[:12])

    async with get_session() as session:
        repo_result = await session.execute(
            select(Repository).where(Repository.id == repo_id)
        )
        repo = repo_result.scalar_one_or_none()
        if not repo:
            raise ValueError(f"Repository {repo_id} not found")
        url = repo.url

    mirror = GitMirror(repo_id, url)
    if not mirror.exists:
        await mirror.fetch()

    # Fetch latest to ensure we have both commits
    await mirror.fetch()

    # Run the review engine
    review_engine = ReviewEngine(mirror, CodeIndexer())
    ctx = await review_engine.gather_context(base_sha, head_sha)
    report = await review_engine.generate_report(ctx, pr_info)

    # Store the review report
    async with get_session() as session:
        if pr_id:
            pr_result = await session.execute(
                select(PullRequest).where(PullRequest.id == pr_id)
            )
            pr = pr_result.scalar_one_or_none()
            if pr:
                from prism.models import ReviewReport
                review_record = ReviewReport(
                    pull_request_id=pr.id,
                    repository_id=repo_id,
                    commit_sha=head_sha,
                    base_sha=base_sha,
                    review_state=ReviewState(report["review_state"]),
                    change_summary=report["change_summary"],
                    functional_purpose=report.get("functional_purpose"),
                    affected_components=report.get("affected_components", []),
                    potential_security_impacts=report.get("potential_security_impacts", []),
                    executive_summary=report.get("executive_summary", {}),
                    technical_evidence=report.get("technical_evidence", {}),
                    uncertainty=report.get("uncertainty"),
                    analysis_coverage=report.get("analysis_coverage", {}),
                    recommended_action=report.get("recommended_action"),
                    required_checks=report.get("required_checks", []),
                    llm_model=report.get("llm_model"),
                    is_stale=False,
                )
                session.add(review_record)
                await session.commit()
                await session.refresh(review_record)
                report["report_id"] = review_record.id

    logger.info("pr_analysis_complete", repo_id=repo_id, state=report["review_state"])

    return report


# ── Job creation helpers ────────────────────────────────────


async def create_and_enqueue_job(
    repository_id: str,
    job_type: JobType | str,
    commit_sha: str | None = None,
    pr_id: str | None = None,
    base_sha: str | None = None,
    head_sha: str | None = None,
    pr_info: dict | None = None,
) -> str:
    """Create a job record in the DB and enqueue it for processing."""
    # Normalize job_type to JobType enum
    if isinstance(job_type, str):
        try:
            job_type = JobType(job_type)
        except ValueError:
            job_type = JobType.INITIAL_INGESTION

    job_id = uuid4().hex
    async with get_session() as session:
        job = AnalysisJob(
            id=job_id,
            repository_id=repository_id,
            job_type=job_type,
            status=JobStatus.QUEUED,
            commit_sha=commit_sha or head_sha,
            pr_id=pr_id,
        )
        session.add(job)
        await session.commit()

    queue = get_job_queue()
    await queue.enqueue({
        "job_id": job_id,
        "job_type": job_type.value,
        "repository_id": repository_id,
        "commit_sha": commit_sha,
        "pr_id": pr_id,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "pr_info": pr_info or {},
    })

    return job_id
