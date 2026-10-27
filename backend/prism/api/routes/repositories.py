"""Repository API routes.

Endpoints for connecting, ingesting, and querying repository intelligence.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.core.git_mirror import GitMirror
from prism.core.indexer import CodeIndexer, detect_language
from prism.core.security import validate_repo_url
from prism.database import get_db
from prism.logging_config import get_logger
from prism.models import (
    AnalysisJob,
    Branch,
    Commit,
    FileEntry,
    IndexStatus,
    IndexVersion,
    Repository,
    Symbol,
)
from prism.schemas import (
    CodeGraphResponse,
    CommitResponse,
    GraphEdge,
    GraphNode,
    IngestionStatusResponse,
    IndexVersionResponse,
    LanguageStat,
    PullRequestResponse,
    RepositoryCreate,
    RepositoryListResponse,
    RepositoryOverviewResponse,
    RepositoryResponse,
    ReviewRequest,
)
from prism.worker.tasks import create_and_enqueue_job, get_job_queue

logger = get_logger("prism.api.repositories")
router = APIRouter(prefix="/api/repositories", tags=["repositories"])


# ── Manual sync ─────────────────────────────────────────────


@router.post("/{repo_id}/sync")
async def trigger_sync(repo_id: str, db: AsyncSession = Depends(get_db)):
    """Immediately check a repository for new commits and enqueue indexing if needed.

    This does what the background poller does, but on demand.
    Safe to call anytime — idempotent.
    """
    from prism.worker.sync import get_sync_scheduler
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    scheduler = get_sync_scheduler()
    await scheduler._check_repository({"id": repo_id, "url": repo.url, "full_name": repo.full_name})

    # Return the latest known head SHA
    from prism.models import Branch
    br = await db.execute(
        select(Branch).where(Branch.repository_id == repo_id, Branch.is_default == True)
    )
    branch = br.scalar_one_or_none()
    return {
        "triggered": True,
        "repository_id": repo_id,
        "head_sha": branch.head_commit_sha if branch else None,
        "last_synced_at": branch.last_synced_at.isoformat() if branch and branch.last_synced_at else None,
    }


@router.post("", response_model=RepositoryResponse, status_code=200)
async def connect_repository(req: RepositoryCreate, db: AsyncSession = Depends(get_db)):
    """Connect a new repository. Validates URL, creates mirror, starts ingestion.
    If already connected, returns the existing repo and re-triggers ingestion if needed.
    """
    # Validate URL with SSRF protection
    validation = validate_repo_url(req.url)
    if not validation.is_valid:
        raise HTTPException(status_code=400, detail=validation.error)

    # Check if already connected
    existing = await db.execute(
        select(Repository).where(Repository.url == req.url)
    )
    existing_repo = existing.scalar_one_or_none()
    if existing_repo:
        # Re-trigger ingestion if previous job failed, is stale, or never persisted data
        from prism.models import AnalysisJob, FileEntry, JobStatus
        job_result = await db.execute(
            select(AnalysisJob)
            .where(AnalysisJob.repository_id == existing_repo.id)
            .order_by(AnalysisJob.created_at.desc())
            .limit(1)
        )
        last_job = job_result.scalar_one_or_none()

        # Check if any FileEntry records exist for the latest index version
        iv_result = await db.execute(
            select(IndexVersion)
            .where(IndexVersion.repository_id == existing_repo.id)
            .order_by(IndexVersion.created_at.desc())
            .limit(1)
        )
        last_iv = iv_result.scalar_one_or_none()
        has_file_entries = False
        if last_iv:
            fe_result = await db.execute(
                select(FileEntry).where(FileEntry.index_version_id == last_iv.id).limit(1)
            )
            has_file_entries = fe_result.scalar_one_or_none() is not None

        needs_retry = (
            last_job is None
            or last_job.status in (JobStatus.FAILED, JobStatus.QUEUED)
            or (last_iv is not None and last_iv.status == IndexStatus.COMPLETED and not has_file_entries)
        )
        if needs_retry:
            await create_and_enqueue_job(
                repository_id=existing_repo.id,
                job_type="initial_ingestion",
            )
        return RepositoryResponse.model_validate(existing_repo)

    # Determine provider
    provider = req.provider or validation.provider
    branch = req.branch or "main"

    # Create repository record
    repo = Repository(
        url=req.url,
        provider=provider,
        full_name=validation.full_name,
        default_branch=branch,
        description=req.description,
    )
    db.add(repo)
    await db.commit()
    await db.refresh(repo)

    # Create default branch record
    db_branch = Branch(
        repository_id=repo.id,
        name=branch,
        is_default=True,
    )
    db.add(db_branch)
    await db.commit()

    # Start initial ingestion job
    job_id = await create_and_enqueue_job(
        repository_id=repo.id,
        job_type="initial_ingestion",
    )

    logger.info("repository_connected", repo_id=repo.id, url=req.url)

    return RepositoryResponse.model_validate(repo)


# ── List repositories ────────────────────────────────────────


@router.get("", response_model=RepositoryListResponse)
async def list_repositories(db: AsyncSession = Depends(get_db)):
    """List all connected repositories."""
    result = await db.execute(
        select(Repository).where(Repository.is_active == True).order_by(Repository.created_at.desc())
    )
    repos = result.scalars().all()
    return RepositoryListResponse(
        repositories=[RepositoryResponse.model_validate(r) for r in repos],
        total=len(repos),
    )


# ── Get repository ──────────────────────────────────────────


@router.get("/{repo_id}", response_model=RepositoryResponse)
async def get_repository(repo_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single repository by ID."""
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return RepositoryResponse.model_validate(repo)


# ── Repository overview ─────────────────────────────────────


@router.get("/{repo_id}/overview", response_model=RepositoryOverviewResponse)
async def get_repository_overview(repo_id: str, db: AsyncSession = Depends(get_db)):
    """Get a full repository overview: languages, symbols, graph data, recent commits."""
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Get latest completed index version
    iv_result = await db.execute(
        select(IndexVersion)
        .where(IndexVersion.repository_id == repo_id)
        .where(IndexVersion.status == IndexStatus.COMPLETED)
        .order_by(IndexVersion.created_at.desc())
        .limit(1)
    )
    index_version = iv_result.scalar_one_or_none()

    # Get commits
    commits_result = await db.execute(
        select(Commit)
        .where(Commit.repository_id == repo_id)
        .order_by(Commit.committed_at.desc().nulls_last())
        .limit(10)
    )
    commits = commits_result.scalars().all()

    # Get file entries for language stats
    languages: dict[str, dict] = {}
    freq_data: list[dict] = []
    total_files = 0
    total_symbols = 0
    total_relationships = 0

    if index_version:
        # Load all FileEntry records once and build a lookup map
        files_result = await db.execute(
            select(FileEntry).where(FileEntry.index_version_id == index_version.id)
        )
        files = files_result.scalars().all()
        total_files = len(files)

        # Build file_entry_id → language map to avoid N+1 queries
        file_lang_map: dict[str, str | None] = {}
        for fe in files:
            file_lang_map[fe.id] = fe.language
            if fe.language:
                if fe.language not in languages:
                    languages[fe.language] = {"files": 0, "symbols": 0}
                languages[fe.language]["files"] += 1

        # Load all symbols once and count per language using the map
        syms_result = await db.execute(
            select(Symbol).where(Symbol.index_version_id == index_version.id)
        )
        symbols = syms_result.scalars().all()
        total_symbols = len(symbols)

        for sym in symbols:
            lang = file_lang_map.get(sym.file_entry_id)
            if lang:
                if lang not in languages:
                    languages[lang] = {"files": 0, "symbols": 0}
                languages[lang]["symbols"] += 1

        # Count relationships
        from prism.models import Relationship as RelModel
        rel_count_result = await db.execute(
            select(RelModel).where(RelModel.index_version_id == index_version.id)
        )
        total_relationships = len(rel_count_result.scalars().all())

        # Build file change frequency from commit history
        file_changes: dict[str, dict] = {}
        for commit in commits:
            for fpath in (commit.files_changed or []):
                if fpath not in file_changes:
                    file_changes[fpath] = {"count": 0, "last_modified": None}
                file_changes[fpath]["count"] += 1
                ts = commit.committed_at
                if ts and (file_changes[fpath]["last_modified"] is None or ts > file_changes[fpath]["last_modified"]):
                    file_changes[fpath]["last_modified"] = ts

        # Get reference counts from symbols
        for fpath, data in sorted(file_changes.items(), key=lambda x: x[1]["count"], reverse=True)[:15]:
            ref_count = sum(1 for s in symbols if s.name and fpath.split("/")[-1].split(".")[0] in (s.name or ""))
            status = "insufficient_evidence"
            if ref_count == 0 and data["count"] < 2:
                status = "possibly_unused"
            elif ref_count > 0:
                status = "active"

            freq_data.append({
                "file_path": fpath,
                "change_count": data["count"],
                "last_modified": data["last_modified"],
                "reference_count": ref_count,
                "status": status,
            })

    # Build language stats
    total_files_for_pct = sum(d["files"] for d in languages.values()) or 1
    lang_stats = [
        LanguageStat(
            language=lang,
            file_count=d["files"],
            symbol_count=d["symbols"],
            percentage=round(d["files"] / total_files_for_pct * 100, 1),
        )
        for lang, d in sorted(languages.items(), key=lambda x: x[1]["files"], reverse=True)
    ]

    return RepositoryOverviewResponse(
        repository=RepositoryResponse.model_validate(repo),
        commit_sha=index_version.commit_sha if index_version else None,
        default_branch=repo.default_branch,
        languages=lang_stats,
        total_files=total_files,
        total_symbols=total_symbols,
        total_relationships=total_relationships,
        frequently_changed=freq_data,
        recent_commits=[
            {
                "sha": c.sha[:12],
                "message": c.message[:100],
                "author": c.author_name,
                "committed_at": c.committed_at.isoformat() if c.committed_at else None,
            }
            for c in commits
        ],
        index_status=index_version.status.value if index_version else "pending",
        index_version=IndexVersionResponse.model_validate(index_version) if index_version else None,
    )


# ── Ingestion status ────────────────────────────────────────


@router.get("/{repo_id}/ingestion-status", response_model=IngestionStatusResponse)
async def get_ingestion_status(repo_id: str, db: AsyncSession = Depends(get_db)):
    """Get the current ingestion job status for a repository."""
    # Get latest job
    job_result = await db.execute(
        select(AnalysisJob)
        .where(AnalysisJob.repository_id == repo_id)
        .order_by(AnalysisJob.created_at.desc())
        .limit(1)
    )
    job = job_result.scalar_one_or_none()

    # Get latest index version
    iv_result = await db.execute(
        select(IndexVersion)
        .where(IndexVersion.repository_id == repo_id)
        .order_by(IndexVersion.created_at.desc())
        .limit(1)
    )
    index_version = iv_result.scalar_one_or_none()

    if not job and not index_version:
        raise HTTPException(status_code=404, detail="No ingestion job found for this repository.")

    return IngestionStatusResponse(
        repository_id=repo_id,
        job_id=job.id if job else "",
        job_type=job.job_type.value if job else "initial_ingestion",
        status=job.status.value if job else (index_version.status.value if index_version else "unknown"),
        progress=job.progress if job else (100.0 if index_version and index_version.status == IndexStatus.COMPLETED else 0.0),
        commit_sha=index_version.commit_sha if index_version else None,
        current_step="indexing" if index_version and index_version.status == IndexStatus.IN_PROGRESS else None,
        languages_detected=index_version.languages if index_version else {},
        files_indexed=index_version.files_indexed if index_version else 0,
        symbols_indexed=index_version.symbols_indexed if index_version else 0,
        errors=index_version.errors if index_version else [],
        warnings=index_version.warnings if index_version else [],
        error_message=job.error_message if job else None,
    )


# ── Commits ─────────────────────────────────────────────────


@router.get("/{repo_id}/commits")
async def list_commits(
    repo_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List recent commits with merge flags and PR linkage."""
    result = await db.execute(
        select(Commit)
        .where(Commit.repository_id == repo_id)
        .order_by(Commit.committed_at.desc().nulls_last())
        .limit(limit)
    )
    commits = result.scalars().all()

    # Build sha → PR map for merge commits
    from prism.models import PullRequest as PR
    pr_by_merge_sha: dict[str, dict] = {}
    pr_by_head_sha: dict[str, dict] = {}
    pr_result = await db.execute(
        select(PR).where(PR.repository_id == repo_id)
    )
    for pr in pr_result.scalars().all():
        row = {
            "id": pr.id,
            "pr_number": pr.pr_number,
            "title": pr.title,
            "state": pr.state,
            "review_state": pr.review_state,
            "html_url": f"https://github.com/{pr.head_branch}",  # placeholder
        }
        if pr.merge_commit_sha:
            pr_by_merge_sha[pr.merge_commit_sha] = row
        if pr.head_sha:
            pr_by_head_sha[pr.head_sha] = row

    commit_list = []
    for c in commits:
        # Detect PR linkage via merge_commit_sha or head_sha
        linked_pr = pr_by_merge_sha.get(c.sha) or pr_by_head_sha.get(c.sha)

        # Extract PR number from merge commit message if not already linked
        extracted_pr_num = None
        if not linked_pr and c.is_merge:
            import re
            m = re.search(r"Merge pull request #(\d+)", c.message)
            if not m:
                m = re.search(r"\(#(\d+)\)\s*$", c.message.split("\n")[0])
            if m:
                extracted_pr_num = int(m.group(1))

        commit_list.append({
            "id": c.id,
            "sha": c.sha,
            "short_sha": c.sha[:12],
            "message": c.message,
            "message_headline": c.message.split("\n")[0][:120],
            "author_name": c.author_name,
            "author_email": c.author_email,
            "committed_at": c.committed_at.isoformat() if c.committed_at else None,
            "stats_additions": c.stats_additions,
            "stats_deletions": c.stats_deletions,
            "files_changed": c.files_changed,
            "files_changed_count": len(c.files_changed) if isinstance(c.files_changed, list) else 0,
            "parent_shas": c.parent_shas or [],
            "is_merge": c.is_merge,
            "linked_pr": linked_pr,
            "extracted_pr_number": extracted_pr_num,
        })

    return {"commits": commit_list, "total": len(commit_list)}


# ── Code graph ──────────────────────────────────────────────


@router.get("/{repo_id}/graph", response_model=CodeGraphResponse)
async def get_code_graph(
    repo_id: str,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Get the code graph (nodes=symbols, edges=relationships)."""
    # Get latest index version
    iv_result = await db.execute(
        select(IndexVersion)
        .where(IndexVersion.repository_id == repo_id)
        .where(IndexVersion.status == IndexStatus.COMPLETED)
        .order_by(IndexVersion.created_at.desc())
        .limit(1)
    )
    index_version = iv_result.scalar_one_or_none()

    if not index_version:
        return CodeGraphResponse(nodes=[], edges=[])

    # Get symbols as nodes
    syms_result = await db.execute(
        select(Symbol)
        .where(Symbol.index_version_id == index_version.id)
        .order_by(Symbol.start_line)
        .limit(limit)
    )
    symbols = syms_result.scalars().all()

    # Get file entries for language info
    file_lang: dict[str, str] = {}
    files_result = await db.execute(
        select(FileEntry).where(FileEntry.index_version_id == index_version.id)
    )
    for fe in files_result.scalars().all():
        file_lang[fe.path] = fe.language or "unknown"

    nodes = []
    for sym in symbols:
        file_path = None
        # Find file path from file entry
        fe_result = await db.execute(
            select(FileEntry).where(FileEntry.id == sym.file_entry_id)
        )
        fe = fe_result.scalar_one_or_none()
        file_path = fe.path if fe else None

        nodes.append(GraphNode(
            id=sym.id,
            label=sym.name,
            type=sym.symbol_type.value,
            file_path=file_path,
            language=file_lang.get(file_path, "unknown") if file_path else None,
        ))

    # Get relationships as edges
    from prism.models import Relationship
    rels_result = await db.execute(
        select(Relationship)
        .where(Relationship.index_version_id == index_version.id)
        .limit(limit * 3)
    )
    rels = rels_result.scalars().all()

    edges = []
    for rel in rels:
        if rel.source_symbol_id and rel.target_symbol_id:
            edges.append(GraphEdge(
                source=rel.source_symbol_id,
                target=rel.target_symbol_id,
                relation_type=rel.relation_type.value,
                certainty=rel.certainty.value,
            ))

    return CodeGraphResponse(nodes=nodes, edges=edges)


# ── Start review ────────────────────────────────────────────


@router.post("/{repo_id}/reviews", status_code=202)
async def start_review(
    repo_id: str,
    req: ReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """Start a PR review analysis for a repository."""
    from prism.models import PullRequest

    # Verify repository exists
    result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Create or get pull request record
    pr = None
    if req.pr_number:
        pr_result = await db.execute(
            select(PullRequest).where(
                PullRequest.repository_id == repo_id,
                PullRequest.pr_number == req.pr_number,
            )
        )
        pr = pr_result.scalar_one_or_none()

        if not pr:
            pr = PullRequest(
                repository_id=repo_id,
                pr_number=req.pr_number,
                title=req.pr_title or "",
                author=req.pr_author,
                base_sha=req.base_sha,
                head_sha=req.head_sha,
                base_branch="",
                head_branch="",
                body=req.pr_body,
            )
            db.add(pr)
            await db.commit()
            await db.refresh(pr)
        else:
            pr.title = req.pr_title or pr.title
            pr.base_sha = req.base_sha
            pr.head_sha = req.head_sha
            await db.commit()

    pr_info = {
        "pr_number": req.pr_number,
        "pr_title": req.pr_title,
        "pr_author": req.pr_author,
        "pr_body": req.pr_body,
    }

    job_id = await create_and_enqueue_job(
        repository_id=repo_id,
        job_type="pr_analysis",
        pr_id=pr.id if pr else None,
        base_sha=req.base_sha,
        head_sha=req.head_sha,
        pr_info=pr_info,
    )

    return {
        "job_id": job_id,
        "pr_id": pr.id if pr else None,
        "status": "queued",
        "message": "Review analysis started. Poll the job endpoint for status.",
    }


# ── List pull requests ──────────────────────────────────────


@router.get("/{repo_id}/pull-requests")
async def list_pull_requests(repo_id: str, db: AsyncSession = Depends(get_db)):
    """List pull requests with review state and merge info. Syncs from GitHub if token configured."""
    from prism.models import PullRequest as PR
    from prism.integrations.github_api import get_github_client

    # Get repo for full_name
    repo_result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = repo_result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Optionally sync from GitHub API
    gh = get_github_client(repo.full_name)
    if gh.is_configured:
        try:
            gh_prs = await gh.list_prs(repo.full_name, state="all", per_page=50)
            for gh_pr in gh_prs:
                pr_result = await db.execute(
                    select(PR).where(
                        PR.repository_id == repo_id,
                        PR.pr_number == gh_pr.number,
                    )
                )
                pr_rec = pr_result.scalar_one_or_none()
                if pr_rec:
                    pr_rec.state = "merged" if gh_pr.merged else gh_pr.state
                    pr_rec.merged_at = (
                        _parse_gh_dt(gh_pr.merged_at) if gh_pr.merged_at else None
                    )
                    pr_rec.merge_commit_sha = gh_pr.merge_commit_sha
                    pr_rec.additions = gh_pr.additions
                    pr_rec.deletions = gh_pr.deletions
                    pr_rec.changed_files = gh_pr.changed_files
                    if gh_pr.review_state:
                        pr_rec.review_state = gh_pr.review_state
                else:
                    # New PR discovered from GitHub — create a local record
                    new_pr = PR(
                        repository_id=repo_id,
                        pr_number=gh_pr.number,
                        title=gh_pr.title or "",
                        author=gh_pr.author,
                        base_sha=gh_pr.base_sha,
                        head_sha=gh_pr.head_sha,
                        base_branch=gh_pr.base_branch,
                        head_branch=gh_pr.head_branch,
                        body=gh_pr.body,
                        state="merged" if gh_pr.merged else gh_pr.state,
                        merged_at=_parse_gh_dt(gh_pr.merged_at) if gh_pr.merged_at else None,
                        merge_commit_sha=gh_pr.merge_commit_sha,
                        additions=gh_pr.additions,
                        deletions=gh_pr.deletions,
                        changed_files=gh_pr.changed_files,
                        review_state=gh_pr.review_state,
                    )
                    db.add(new_pr)
            await db.commit()
        except Exception as e:
            logger.warning("github_pr_sync_failed", error=str(e))

    result = await db.execute(
        select(PR)
        .where(PR.repository_id == repo_id)
        .order_by(PR.created_at.desc())
    )
    prs = result.scalars().all()

    # Get review reports for review_state
    from prism.models import ReviewReport
    report_map: dict[str, str] = {}
    for pr in prs:
        rr = await db.execute(
            select(ReviewReport)
            .where(ReviewReport.pull_request_id == pr.id)
            .order_by(ReviewReport.created_at.desc())
            .limit(1)
        )
        r = rr.scalar_one_or_none()
        if r:
            report_map[pr.id] = r.review_state.value

    return {
        "pull_requests": [
            {
                "id": pr.id,
                "pr_number": pr.pr_number,
                "title": pr.title,
                "author": pr.author,
                "base_sha": pr.base_sha[:12] if pr.base_sha else None,
                "head_sha": pr.head_sha[:12] if pr.head_sha else None,
                "base_branch": pr.base_branch,
                "head_branch": pr.head_branch,
                "state": pr.state,
                "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
                "merge_commit_sha": pr.merge_commit_sha[:12] if pr.merge_commit_sha else None,
                "additions": pr.additions,
                "deletions": pr.deletions,
                "changed_files": pr.changed_files,
                "review_state": report_map.get(pr.id) or pr.review_state,
                "github_review_state": pr.review_state,
                "created_at": pr.created_at.isoformat(),
                "github_configured": gh.is_configured,
            }
            for pr in prs
        ],
        "total": len(prs),
        "github_configured": gh.is_configured,
    }


# ── Approve PR ──────────────────────────────────────────────


@router.post("/{repo_id}/pull-requests/{pr_id}/approve")
async def approve_pull_request(
    repo_id: str,
    pr_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Submit an approving review on GitHub for a PR.

    Only allowed when:
    - GITHUB_TOKEN is configured
    - The PR's PRISM review_state is READY_FOR_POLICY_REVIEW
    - No blocking findings exist for this PR

    Returns a clear error otherwise — PRISM never bypasses policy.
    """
    from prism.models import PullRequest as PR, ReviewReport, Finding

    repo_result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = repo_result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    pr_result = await db.execute(select(PR).where(PR.id == pr_id, PR.repository_id == repo_id))
    pr = pr_result.scalar_one_or_none()
    if not pr:
        raise HTTPException(status_code=404, detail="Pull request not found")

    # Check PRISM review state
    rr_result = await db.execute(
        select(ReviewReport)
        .where(ReviewReport.pull_request_id == pr_id)
        .order_by(ReviewReport.created_at.desc())
        .limit(1)
    )
    report = rr_result.scalar_one_or_none()

    if not report:
        raise HTTPException(
            status_code=422,
            detail="No PRISM analysis exists for this PR. Run a security review first.",
        )

    # Block if there are any blocking findings
    blocking = await db.execute(
        select(Finding).where(
            Finding.review_report_id == report.id,
            Finding.is_blocking == True,
        )
    )
    if blocking.scalars().first():
        raise HTTPException(
            status_code=422,
            detail="Cannot approve: blocking security findings exist. Resolve them first.",
        )

    # Only approve when policy clears it
    allowed_states = {"ready_for_policy_review", "review_required"}
    if report.review_state.value not in allowed_states:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot approve: PR review state is '{report.review_state.value}'. "
                   f"Only {allowed_states} are eligible for approval.",
        )

    from prism.integrations.github_api import get_github_client
    gh = get_github_client(repo.full_name)

    if not gh.is_configured:
        raise HTTPException(
            status_code=422,
            detail="GITHUB_TOKEN is not configured. Add it to your .env file to enable PR approvals.",
        )

    approval_body = (
        f"**PRISM Security Review — {report.review_state.value.upper().replace('_', ' ')}**\n\n"
        f"{report.recommended_action or 'Analysis complete.'}\n\n"
        f"Analysis run at commit `{report.commit_sha[:12]}`. "
        f"Model: `{report.llm_model or 'fallback'}`."
    )

    result = await gh.approve_pr(repo.full_name, pr.pr_number, body=approval_body)

    if result.success:
        # Update local review_state on PR record
        pr.review_state = "APPROVED"
        await db.commit()
        # Log audit event
        from prism.models import AuditEvent
        db.add(AuditEvent(
            repository_id=repo_id,
            actor="prism",
            action="pr_approved",
            details={"pr_number": pr.pr_number, "pr_id": pr_id},
        ))
        await db.commit()

    return {
        "success": result.success,
        "message": result.message,
        "html_url": result.html_url,
        "pr_number": pr.pr_number,
    }


# ── Merge PR ────────────────────────────────────────────────


@router.post("/{repo_id}/pull-requests/{pr_id}/merge")
async def merge_pull_request(
    repo_id: str,
    pr_id: str,
    merge_method: str = "squash",
    db: AsyncSession = Depends(get_db),
):
    """Merge a PR via GitHub API.

    Only allowed when:
    - GITHUB_TOKEN is configured with contents:write + pull_requests:write
    - PR review_state is READY_FOR_POLICY_REVIEW
    - No blocking findings exist
    - PR is open (not already merged)
    """
    from prism.models import PullRequest as PR, ReviewReport, Finding

    repo_result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = repo_result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    pr_result = await db.execute(select(PR).where(PR.id == pr_id, PR.repository_id == repo_id))
    pr = pr_result.scalar_one_or_none()
    if not pr:
        raise HTTPException(status_code=404, detail="Pull request not found")

    if pr.state == "merged":
        raise HTTPException(status_code=422, detail="PR is already merged.")

    rr_result = await db.execute(
        select(ReviewReport)
        .where(ReviewReport.pull_request_id == pr_id)
        .order_by(ReviewReport.created_at.desc())
        .limit(1)
    )
    report = rr_result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=422, detail="Run a PRISM security review first.")

    blocking = await db.execute(
        select(Finding).where(
            Finding.review_report_id == report.id,
            Finding.is_blocking == True,
        )
    )
    if blocking.scalars().first():
        raise HTTPException(status_code=422, detail="Cannot merge: blocking findings exist.")

    if report.review_state.value != "ready_for_policy_review":
        raise HTTPException(
            status_code=422,
            detail=f"Cannot merge: state is '{report.review_state.value}'. "
                   "Only 'ready_for_policy_review' is eligible.",
        )

    from prism.integrations.github_api import get_github_client
    gh = get_github_client(repo.full_name)
    if not gh.is_configured:
        raise HTTPException(status_code=422, detail="GITHUB_TOKEN not configured.")

    result = await gh.merge_pr(
        repo.full_name,
        pr.pr_number,
        commit_title=f"[PRISM] {pr.title}",
        commit_message=f"Merged after PRISM security review. Analysis: {report.review_state.value}.",
        merge_method=merge_method,
    )

    if result.success:
        pr.state = "merged"
        pr.merge_commit_sha = result.merge_commit_sha
        from datetime import datetime as _dt, timezone as _tz
        pr.merged_at = _dt.now(_tz.utc)
        await db.commit()
        from prism.models import AuditEvent
        db.add(AuditEvent(
            repository_id=repo_id,
            actor="prism",
            action="pr_merged",
            details={"pr_number": pr.pr_number, "method": merge_method},
        ))
        await db.commit()

    return {
        "success": result.success,
        "message": result.message,
        "merge_commit_sha": result.merge_commit_sha,
        "pr_number": pr.pr_number,
    }


def _parse_gh_dt(s: str | None):
    """Parse a GitHub ISO timestamp to a datetime."""
    if not s:
        return None
    from datetime import datetime as _dt
    try:
        return _dt.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# ── Get review report ───────────────────────────────────────


@router.get("/{repo_id}/reviews/{pr_id}")
async def get_review_report(repo_id: str, pr_id: str, db: AsyncSession = Depends(get_db)):
    """Get the latest review report for a pull request."""
    from prism.models import ReviewReport
    result = await db.execute(
        select(ReviewReport)
        .where(ReviewReport.pull_request_id == pr_id)
        .where(ReviewReport.repository_id == repo_id)
        .order_by(ReviewReport.created_at.desc())
        .limit(1)
    )
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="No review report found for this PR.")

    # Get findings
    from prism.models import Finding, EvidenceRef
    findings_result = await db.execute(
        select(Finding).where(Finding.review_report_id == report.id)
    )
    findings = findings_result.scalars().all()

    return {
        "id": report.id,
        "pull_request_id": report.pull_request_id,
        "repository_id": report.repository_id,
        "commit_sha": report.commit_sha,
        "base_sha": report.base_sha,
        "review_state": report.review_state.value,
        "change_summary": report.change_summary,
        "functional_purpose": report.functional_purpose,
        "affected_components": report.affected_components,
        "potential_security_impacts": report.potential_security_impacts,
        "executive_summary": report.executive_summary,
        "technical_evidence": report.technical_evidence,
        "findings": [
            {
                "id": f.id,
                "title": f.title,
                "description": f.description,
                "severity": f.severity.value,
                "confidence": f.confidence.value,
                "file_path": f.file_path,
                "line_range": f.line_range,
                "category": f.category,
                "rule_id": f.rule_id,
                "scanner_source": f.scanner_source,
                "is_blocking": f.is_blocking,
            }
            for f in findings
        ],
        "uncertainty": report.uncertainty,
        "analysis_coverage": report.analysis_coverage,
        "recommended_action": report.recommended_action,
        "required_checks": report.required_checks,
        "llm_model": report.llm_model,
        "is_stale": report.is_stale,
        "created_at": report.created_at.isoformat(),
    }


