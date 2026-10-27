"""SQLAlchemy ORM models for the PRISM data model.

All entities are associated with a repository and commit/index version so
that stale context is never presented as current state.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from prism.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex


# ── Enums ──────────────────────────────────────────────────────


class RepoProvider(str, enum.Enum):
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    LOCAL = "local"
    OTHER = "other"


class IndexStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class JobType(str, enum.Enum):
    INITIAL_INGESTION = "initial_ingestion"
    INCREMENTAL_INDEX = "incremental_index"
    PR_ANALYSIS = "pr_analysis"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SymbolType(str, enum.Enum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    INTERFACE = "interface"
    VARIABLE = "variable"
    IMPORT = "import"
    ENDPOINT = "endpoint"


class RelationType(str, enum.Enum):
    IMPORTS = "imports"
    CALLS = "calls"
    REFERENCES = "references"
    IMPLEMENTS = "implements"
    DEPENDS_ON = "depends_on"
    EXPOSES_API = "exposes_api"
    TESTED_BY = "tested_by"
    AFFECTED_BY = "affected_by"
    PROTECTED_BY = "protected_by"


class RelationCertainty(str, enum.Enum):
    STATICALLY_VERIFIED = "statically_verified"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class FindingSeverity(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingConfidence(str, enum.Enum):
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    HYPOTHESIS = "hypothesis"


class ReviewState(str, enum.Enum):
    READY_FOR_POLICY_REVIEW = "ready_for_policy_review"
    REVIEW_REQUIRED = "review_required"
    BLOCKED_BY_FINDING = "blocked_by_finding"
    ANALYSIS_INCOMPLETE = "analysis_incomplete"
    FAILED_CHECKS = "failed_checks"
    HUMAN_SECURITY_REVIEW_REQUIRED = "human_security_review_required"


class ScannerType(str, enum.Enum):
    COVERITY = "coverity"
    BLACKDUCK = "blackduck"
    PRISM = "prism"
    CI_CHECK = "ci_check"
    TEST = "test"


# ── Models ─────────────────────────────────────────────────────


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    provider: Mapped[RepoProvider] = mapped_column(Enum(RepoProvider), nullable=False)
    full_name: Mapped[str] = mapped_column(String(512), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(256), default="main")
    mirror_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    branches: Mapped[list[Branch]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    commits: Mapped[list[Commit]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    index_versions: Mapped[list[IndexVersion]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    jobs: Mapped[list[AnalysisJob]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    pull_requests: Mapped[list[PullRequest]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    scanner_results: Mapped[list[ScannerResult]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="repository", cascade="all, delete-orphan")


class Branch(Base):
    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("repository_id", "name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    head_commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="branches")


class Commit(Base):
    __tablename__ = "commits"
    __table_args__ = (UniqueConstraint("repository_id", "sha"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    sha: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author_name: Mapped[str] = mapped_column(String(256), default="")
    author_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    parent_shas: Mapped[list] = mapped_column(JSON, default=list)
    is_merge: Mapped[bool] = mapped_column(Boolean, default=False)
    stats_additions: Mapped[int] = mapped_column(Integer, default=0)
    stats_deletions: Mapped[int] = mapped_column(Integer, default=0)
    files_changed: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    repository: Mapped[Repository] = relationship(back_populates="commits")


class IndexVersion(Base):
    __tablename__ = "index_versions"
    __table_args__ = (UniqueConstraint("repository_id", "commit_sha"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[IndexStatus] = mapped_column(Enum(IndexStatus), default=IndexStatus.PENDING)
    languages: Mapped[dict] = mapped_column(JSON, default=dict)
    files_indexed: Mapped[int] = mapped_column(Integer, default=0)
    symbols_indexed: Mapped[int] = mapped_column(Integer, default=0)
    relationships_indexed: Mapped[int] = mapped_column(Integer, default=0)
    files_unsupported: Mapped[list] = mapped_column(JSON, default=list)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    repository: Mapped[Repository] = relationship(back_populates="index_versions")


class FileEntry(Base):
    __tablename__ = "file_entries"
    __table_args__ = (
        UniqueConstraint("index_version_id", "path"),
        Index("ix_file_entries_hash", "content_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    index_version_id: Mapped[str] = mapped_column(ForeignKey("index_versions.id"), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    is_supported: Mapped[bool] = mapped_column(Boolean, default=True)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)


class Symbol(Base):
    __tablename__ = "symbols"
    __table_args__ = (
        Index("ix_symbols_name", "name"),
        Index("ix_symbols_file", "file_entry_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    file_entry_id: Mapped[str] = mapped_column(ForeignKey("file_entries.id"), nullable=False)
    index_version_id: Mapped[str] = mapped_column(ForeignKey("index_versions.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    qualified_name: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    symbol_type: Mapped[SymbolType] = mapped_column(Enum(SymbolType), nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    docstring: Mapped[str | None] = mapped_column(Text, nullable=True)


class Relationship(Base):
    __tablename__ = "relationships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    index_version_id: Mapped[str] = mapped_column(ForeignKey("index_versions.id"), nullable=False)
    source_symbol_id: Mapped[str | None] = mapped_column(ForeignKey("symbols.id"), nullable=True)
    target_symbol_id: Mapped[str | None] = mapped_column(ForeignKey("symbols.id"), nullable=True)
    source_file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    target_file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    relation_type: Mapped[RelationType] = mapped_column(Enum(RelationType), nullable=False)
    certainty: Mapped[RelationCertainty] = mapped_column(
        Enum(RelationCertainty), default=RelationCertainty.STATICALLY_VERIFIED
    )
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PullRequest(Base):
    __tablename__ = "pull_requests"
    __table_args__ = (UniqueConstraint("repository_id", "pr_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(1024), default="")
    author: Mapped[str | None] = mapped_column(String(256), nullable=True)
    base_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    head_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(256), default="")
    head_branch: Mapped[str] = mapped_column(String(256), default="")
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ── Extended fields ──────────────────────────────────────────────
    state: Mapped[str] = mapped_column(String(32), default="open")       # open | closed | merged
    merged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    merge_commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    changed_files: Mapped[int] = mapped_column(Integer, default=0)
    # review_state mirrors the PRISM analysis result for quick display
    review_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    repository: Mapped[Repository] = relationship(back_populates="pull_requests")
    review_reports: Mapped[list[ReviewReport]] = relationship(back_populates="pull_request", cascade="all, delete-orphan")


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    job_type: Mapped[JobType] = mapped_column(Enum(JobType), nullable=False)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.QUEUED)
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pr_id: Mapped[str | None] = mapped_column(ForeignKey("pull_requests.id"), nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="jobs")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    review_report_id: Mapped[str | None] = mapped_column(ForeignKey("review_reports.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[FindingSeverity] = mapped_column(Enum(FindingSeverity), default=FindingSeverity.INFO)
    confidence: Mapped[FindingConfidence] = mapped_column(Enum(FindingConfidence), default=FindingConfidence.HYPOTHESIS)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    line_range: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str | None] = mapped_column(String(256), nullable=True)
    rule_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    scanner_source: Mapped[str] = mapped_column(String(64), default="prism")
    is_blocking: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    review_report: Mapped[ReviewReport | None] = relationship(back_populates="findings")


class EvidenceRef(Base):
    __tablename__ = "evidence_refs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    finding_id: Mapped[str | None] = mapped_column(ForeignKey("findings.id"), nullable=True)
    review_report_id: Mapped[str | None] = mapped_column(ForeignKey("review_reports.id"), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    code_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), default="source")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    review_report: Mapped[ReviewReport | None] = relationship(back_populates="evidence")


class ReviewReport(Base):
    __tablename__ = "review_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    pull_request_id: Mapped[str] = mapped_column(ForeignKey("pull_requests.id"), nullable=False)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    base_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    review_state: Mapped[ReviewState] = mapped_column(Enum(ReviewState), default=ReviewState.ANALYSIS_INCOMPLETE)
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    functional_purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    affected_components: Mapped[list] = mapped_column(JSON, default=list)
    potential_security_impacts: Mapped[list] = mapped_column(JSON, default=list)
    executive_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    technical_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    uncertainty: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_checks: Mapped[list] = mapped_column(JSON, default=list)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    index_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    pull_request: Mapped[PullRequest] = relationship(back_populates="review_reports")
    findings: Mapped[list[Finding]] = relationship(back_populates="review_report", cascade="all, delete-orphan")
    evidence: Mapped[list[EvidenceRef]] = relationship(back_populates="review_report", cascade="all, delete-orphan")


class ScannerResult(Base):
    __tablename__ = "scanner_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    scanner_type: Mapped[ScannerType] = mapped_column(Enum(ScannerType), nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(64), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    repository: Mapped[Repository] = relationship(back_populates="scanner_results")


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repository_id: Mapped[str | None] = mapped_column(ForeignKey("repositories.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    required_checks: Mapped[list] = mapped_column(JSON, default=list)
    block_on_severity: Mapped[FindingSeverity] = mapped_column(
        Enum(FindingSeverity), default=FindingSeverity.HIGH
    )
    require_scanner_results: Mapped[bool] = mapped_column(Boolean, default=False)
    escalate_security_sensitive: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repository_id: Mapped[str | None] = mapped_column(ForeignKey("repositories.id"), nullable=True)
    actor: Mapped[str] = mapped_column(String(256), default="system")
    action: Mapped[str] = mapped_column(String(256), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    repository: Mapped[Repository] = relationship(back_populates="audit_events")
