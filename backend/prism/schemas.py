"""Pydantic schemas for API request/response validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from prism.models import (
    FindingConfidence,
    FindingSeverity,
    IndexStatus,
    JobStatus,
    JobType,
    RelationCertainty,
    RelationType,
    ReviewState,
    SymbolType,
)


# ── Repository ──────────────────────────────────────────────


class RepositoryCreate(BaseModel):
    url: str = Field(..., description="Git repository URL (https, git, ssh, or file)")
    provider: str | None = Field(None, description="Git provider (auto-detected if omitted)")
    branch: str | None = Field(None, description="Branch to track (defaults to repo default)")
    description: str | None = None


class RepositoryResponse(BaseModel):
    id: str
    url: str
    provider: str
    full_name: str
    default_branch: str
    mirror_path: str | None
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RepositoryListResponse(BaseModel):
    repositories: list[RepositoryResponse]
    total: int


# ── Index / Ingestion ───────────────────────────────────────


class IndexVersionResponse(BaseModel):
    id: str
    repository_id: str
    commit_sha: str
    status: str
    languages: dict[str, int]
    files_indexed: int
    symbols_indexed: int
    relationships_indexed: int
    files_unsupported: list[str]
    errors: list[str]
    warnings: list[str]
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class IngestionStatusResponse(BaseModel):
    repository_id: str
    job_id: str
    job_type: str
    status: str
    progress: float
    commit_sha: str | None
    current_step: str | None
    languages_detected: dict[str, int]
    files_indexed: int
    symbols_indexed: int
    errors: list[str]
    warnings: list[str]
    error_message: str | None


# ── Repository Overview ─────────────────────────────────────


class LanguageStat(BaseModel):
    language: str
    file_count: int
    symbol_count: int
    percentage: float


class SymbolResponse(BaseModel):
    id: str
    name: str
    qualified_name: str | None
    symbol_type: str
    file_path: str
    start_line: int
    end_line: int
    signature: str | None
    docstring: str | None

    model_config = {"from_attributes": True}


class RelationshipResponse(BaseModel):
    id: str
    source_symbol_name: str | None
    target_symbol_name: str | None
    source_file_path: str | None
    target_file_path: str | None
    relation_type: str
    certainty: str
    line_number: int | None


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    file_path: str | None
    language: str | None
    change_count: int = 0
    last_modified: datetime | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    relation_type: str
    certainty: str


class CodeGraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class FileChangeFrequency(BaseModel):
    file_path: str
    change_count: int
    last_modified: datetime | None
    reference_count: int = 0
    status: str = "insufficient_evidence"


class RepositoryOverviewResponse(BaseModel):
    repository: RepositoryResponse
    commit_sha: str | None
    default_branch: str
    languages: list[LanguageStat]
    total_files: int
    total_symbols: int
    total_relationships: int
    frequently_changed: list[FileChangeFrequency]
    recent_commits: list[dict]
    index_status: str
    index_version: IndexVersionResponse | None


# ── Pull Request ────────────────────────────────────────────


class PullRequestResponse(BaseModel):
    id: str
    pr_number: int
    title: str
    author: str | None
    base_sha: str
    head_sha: str
    base_branch: str
    head_branch: str
    body: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PullRequestListResponse(BaseModel):
    pull_requests: list[PullRequestResponse]
    total: int


class ReviewRequest(BaseModel):
    base_sha: str
    head_sha: str
    pr_number: int | None = None
    pr_title: str | None = None
    pr_author: str | None = None
    pr_body: str | None = None


# ── Review Report ───────────────────────────────────────────


class FindingResponse(BaseModel):
    id: str
    title: str
    description: str
    severity: str
    confidence: str
    file_path: str | None
    line_range: list[int]
    category: str | None
    rule_id: str | None
    scanner_source: str
    is_blocking: bool
    evidence: list[dict] = []

    model_config = {"from_attributes": True}


class CheckResult(BaseModel):
    name: str
    status: str
    source: str
    details: str | None = None


class ReviewReportResponse(BaseModel):
    id: str
    pull_request_id: str
    repository_id: str
    commit_sha: str
    base_sha: str
    review_state: str
    change_summary: str
    functional_purpose: str | None
    affected_components: list[dict]
    potential_security_impacts: list[dict]
    executive_summary: dict
    technical_evidence: dict
    findings: list[FindingResponse]
    uncertainty: str | None
    analysis_coverage: dict
    recommended_action: str | None
    required_checks: list[CheckResult]
    llm_model: str | None
    is_stale: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Commits ─────────────────────────────────────────────────


class CommitResponse(BaseModel):
    id: str
    sha: str
    message: str
    author_name: str
    author_email: str | None
    committed_at: datetime | None
    stats_additions: int
    stats_deletions: int
    files_changed: list[str]

    model_config = {"from_attributes": True}


class CommitListResponse(BaseModel):
    commits: list[CommitResponse]
    total: int


# ── Job ─────────────────────────────────────────────────────


class AnalysisJobResponse(BaseModel):
    id: str
    repository_id: str
    job_type: str
    status: str
    commit_sha: str | None
    progress: float
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


# ── Webhook ─────────────────────────────────────────────────


class WebhookEvent(BaseModel):
    event_type: str
    repository_url: str
    repository_full_name: str
    action: str | None = None
    pr_number: int | None = None
    pr_title: str | None = None
    pr_author: str | None = None
    pr_body: str | None = None
    base_sha: str | None = None
    head_sha: str | None = None
    base_branch: str | None = None
    head_branch: str | None = None
    commit_sha: str | None = None
    ref: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class WebhookResponse(BaseModel):
    accepted: bool
    message: str
    event_type: str | None = None


# ── MCP Tools ────────────────────────────────────────────────


class McpToolRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class McpToolResponse(BaseModel):
    tool_name: str
    success: bool
    result: dict[str, Any] | None = None
    error: str | None = None


# ── Settings ────────────────────────────────────────────────


class LlmSettingsResponse(BaseModel):
    provider: str
    model: str
    base_url: str
    is_available: bool = False
    model_info: dict[str, Any] = {}


class IntegrationStatus(BaseModel):
    name: str
    type: str
    configured: bool
    status: str = "not_configured"
    details: dict[str, Any] = {}


class SettingsResponse(BaseModel):
    llm: LlmSettingsResponse
    integrations: list[IntegrationStatus]
    database_type: str


# ── Health ──────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    llm_provider: str
    llm_model: str
    llm_available: bool = False


# ── Changed Symbols (for incremental processing) ────────────


class ChangedFile(BaseModel):
    path: str
    status: str  # added, modified, deleted, renamed
    old_path: str | None = None
    additions: int = 0
    deletions: int = 0
    content_hash: str | None = None
    old_content_hash: str | None = None


class ChangedSymbolsResponse(BaseModel):
    changed_files: list[ChangedFile]
    added_symbols: list[str]
    modified_symbols: list[str]
    removed_symbols: list[str]
    reuse_count: int
    rebuild_count: int
