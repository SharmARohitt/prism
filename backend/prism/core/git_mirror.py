"""Git mirror management — persistent on-disk mirrors with incremental fetch.

The mirror is created once and reused for every subsequent commit/PR analysis.
We fetch missing objects into the existing mirror rather than cloning again.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import git
from git import Repo
from git.objects import Commit as GitCommit
from git.objects import Tree as GitTree

from prism.config import get_settings
from prism.logging_config import get_logger

logger = get_logger("prism.git")


@dataclass
class ChangedFile:
    path: str
    status: str  # added, modified, deleted, renamed
    old_path: str | None = None
    additions: int = 0
    deletions: int = 0
    content_hash: str | None = None
    old_content_hash: str | None = None


@dataclass
class DiffResult:
    base_sha: str
    head_sha: str
    changed_files: list[ChangedFile] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


@dataclass
class RepoStructure:
    commit_sha: str
    file_paths: list[str] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    build_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    doc_files: list[str] = field(default_factory=list)
    ci_files: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)
    manifest_files: list[str] = field(default_factory=list)


# ── Language detection ────────────────────────────────────

LANG_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".sh": "shell",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".json": "json",
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".md": "markdown",
}

BUILD_FILES = {
    "package.json", "tsconfig.json", "pyproject.toml", "setup.py", "setup.cfg",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
    "Makefile", "CMakeLists.txt", "requirements.txt", "Gemfile",
}

CI_DIRS = {".github/workflows", ".gitlab/ci", ".circleci"}
CI_FILES = {"Jenkinsfile", ".travis.yml", "azure-pipelines.yml"}

TEST_PATTERNS = {"test_", "_test.", ".test.", ".spec.", "tests/", "/test/"}
DOC_PATTERNS = {"README", "CHANGELOG", "ARCHITECTURE", "CONTRIBUTING", "docs/"}
CONFIG_PATTERNS = {".env", "config", "docker-compose", "Dockerfile", ".dockerignore"}


def detect_language(file_path: str) -> str | None:
    """Detect language from file extension."""
    ext = Path(file_path).suffix.lower()
    return LANG_EXTENSIONS.get(ext)


def compute_content_hash(content: str | bytes) -> str:
    """Compute SHA-256 content hash."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


class GitMirror:
    """Manages a persistent Git mirror for a single repository."""

    def __init__(self, repo_id: str, url: str, mirror_dir: Path | None = None):
        self.repo_id = repo_id
        self.url = url
        self.mirror_dir = mirror_dir or (get_settings().git_mirror_path / repo_id)
        self._repo: Repo | None = None

    @property
    def mirror_path(self) -> Path:
        return self.mirror_dir

    @property
    def exists(self) -> bool:
        return self.mirror_dir.exists() and (self.mirror_dir / ".git").exists()

    def _get_repo(self) -> Repo:
        if self._repo is None:
            if not self.exists:
                self._init_mirror()
            self._repo = Repo(str(self.mirror_dir))
        return self._repo

    def _init_mirror(self) -> None:
        """Clone the repository into the persistent mirror."""
        self.mirror_dir.parent.mkdir(parents=True, exist_ok=True)
        logger.info("cloning_repository", repo_id=self.repo_id, url=self.url, path=str(self.mirror_dir))
        self._repo = Repo.clone_from(self.url, str(self.mirror_dir), depth=1)
        # Unshallow to get full history (can be slow for large repos)
        # For incremental processing we need the full graph
        try:
            self._repo.git.fetch("--unshallow")
        except git.GitCommandError:
            # Already a full clone
            pass

    async def fetch(self) -> str:
        """Fetch latest objects into the existing mirror. Returns current HEAD SHA."""
        repo = await asyncio.to_thread(self._get_repo)
        origin = repo.remotes.origin
        await asyncio.to_thread(origin.fetch, "+refs/heads/*:refs/remotes/origin/*")
        logger.info("fetched_repository", repo_id=self.repo_id)
        return await self.get_head_sha()

    async def fetch_commits(self, base_sha: str, head_sha: str) -> None:
        """Fetch specific commits if missing (for PR processing)."""
        repo = await asyncio.to_thread(self._get_repo)
        origin = repo.remotes.origin
        # Fetch the specific commit range
        try:
            await asyncio.to_thread(origin.fetch, f"{base_sha}:{base_sha}")
        except Exception:
            pass
        try:
            await asyncio.to_thread(origin.fetch, f"{head_sha}:{head_sha}")
        except Exception:
            pass

    async def get_head_sha(self, branch: str | None = None) -> str:
        """Get the SHA of HEAD or a specific branch."""
        repo = await asyncio.to_thread(self._get_repo)
        if branch:
            ref = f"origin/{branch}"
            try:
                return repo.commit(ref).hexsha
            except Exception:
                pass
        return repo.head.commit.hexsha

    async def get_default_branch(self) -> str:
        """Detect the default branch from the remote."""
        repo = await asyncio.to_thread(self._get_repo)
        try:
            # Try common default branch names
            for name in ("main", "master"):
                if f"origin/{name}" in [ref.name for ref in repo.refs]:
                    return name
            # Fall back to HEAD's symbolic ref
            result = repo.git.symbolic_ref("refs/remotes/origin/HEAD")
            return result.replace("refs/remotes/origin/", "")
        except Exception:
            return "main"

    async def get_commit_info(self, sha: str) -> dict[str, Any]:
        """Get commit metadata: message, author, date, parents, stats."""
        repo = await asyncio.to_thread(self._get_repo)
        commit = repo.commit(sha)
        stats = commit.stats

        return {
            "sha": commit.hexsha,
            "message": commit.message.strip(),
            "author_name": commit.author.name or "",
            "author_email": commit.author.email,
            "committed_at": commit.committed_datetime.isoformat() if commit.committed_datetime else None,
            "parent_shas": [p.hexsha for p in commit.parents],
            "stats_additions": stats.total["insertions"],
            "stats_deletions": stats.total["deletions"],
            "files_changed": list(stats.files.keys()),
        }

    async def get_recent_commits(self, branch: str | None = None, limit: int = 20) -> list[dict]:
        """Get recent commit history."""
        repo = await asyncio.to_thread(self._get_repo)
        ref = f"origin/{branch}" if branch else "HEAD"
        commits = []
        for commit in repo.iter_commits(ref, max_count=limit):
            commits.append({
                "sha": commit.hexsha,
                "message": commit.message.strip().split("\n")[0],
                "author_name": commit.author.name or "",
                "committed_at": commit.committed_datetime.isoformat() if commit.committed_datetime else None,
                "files_changed": len(commit.stats.files),
            })
        return commits

    async def get_diff(self, base_sha: str, head_sha: str) -> DiffResult:
        """Compare two commit trees and identify changed files."""
        repo = await asyncio.to_thread(self._get_repo)

        base_commit = repo.commit(base_sha)
        head_commit = repo.commit(head_sha)

        result = DiffResult(base_sha=base_sha, head_sha=head_sha)

        # Get the diff between the two trees
        diffs = base_commit.diff(head_commit, create_patch=False)

        total_add = 0
        total_del = 0

        for diff_item in diffs:
            change_type = diff_item.change_type  # A=added, M=modified, D=deleted, R=renamed
            file_path = diff_item.b_path or diff_item.a_path

            status_map = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed", "T": "modified"}
            status = status_map.get(change_type, "modified")

            additions = 0
            deletions = 0
            content_hash = None

            try:
                diff_stat = repo.git.diff("--numstat", f"{base_sha}..{head_sha}", "--", file_path)
                if diff_stat.strip():
                    parts = diff_stat.strip().split("\t")
                    if len(parts) >= 2:
                        additions = int(parts[0]) if parts[0] != "-" else 0
                        deletions = int(parts[1]) if parts[1] != "-" else 0
            except Exception:
                pass

            # Get content hash for the head version
            if status != "deleted":
                try:
                    blob = head_commit.tree[file_path]
                    content = blob.data_stream.read()
                    content_hash = compute_content_hash(content)
                except (KeyError, Exception):
                    pass

            old_content_hash = None
            if status == "modified" or status == "deleted":
                try:
                    blob = base_commit.tree[file_path]
                    content = blob.data_stream.read()
                    old_content_hash = compute_content_hash(content)
                except (KeyError, Exception):
                    pass

            result.changed_files.append(ChangedFile(
                path=file_path,
                status=status,
                old_path=diff_item.a_path if diff_item.a_path != diff_item.b_path else None,
                additions=additions,
                deletions=deletions,
                content_hash=content_hash,
                old_content_hash=old_content_hash,
            ))
            total_add += additions
            total_del += deletions

        result.stats = {
            "additions": total_add,
            "deletions": total_del,
            "files_changed": len(result.changed_files),
        }

        logger.info(
            "computed_diff",
            base=base_sha[:12],
            head=head_sha[:12],
            files_changed=len(result.changed_files),
        )
        return result

    async def get_file_content(self, file_path: str, commit_sha: str = "HEAD") -> str | None:
        """Get file content at a specific commit."""
        repo = await asyncio.to_thread(self._get_repo)
        try:
            commit = repo.commit(commit_sha)
            blob = commit.tree[file_path]
            return blob.data_stream.read().decode("utf-8", errors="replace")
        except (KeyError, Exception):
            return None

    async def get_file_content_lines(self, file_path: str, start: int, end: int, commit_sha: str = "HEAD") -> list[str]:
        """Get specific line range of a file."""
        content = await self.get_file_content(file_path, commit_sha)
        if content is None:
            return []
        lines = content.split("\n")
        return lines[max(0, start - 1):end]

    async def analyze_structure(self, commit_sha: str | None = None) -> RepoStructure:
        """Inspect repository structure: files, languages, build/CI/docs."""
        repo = await asyncio.to_thread(self._get_repo)
        sha = commit_sha or repo.head.commit.hexsha
        commit = repo.commit(sha)
        tree = commit.tree

        structure = RepoStructure(commit_sha=sha)

        for blob in tree.traverse():
            if blob.type == "blob":
                path = str(blob.path)
                structure.file_paths.append(path)

                lang = detect_language(path)
                if lang:
                    structure.languages[lang] = structure.languages.get(lang, 0) + 1

                basename = Path(path).name
                dirname = str(Path(path).parent).replace("\\", "/")

                if basename in BUILD_FILES:
                    structure.build_files.append(path)
                if any(path.startswith(ci_dir) or ci_dir in path for ci_dir in CI_DIRS) or basename in CI_FILES:
                    structure.ci_files.append(path)
                if any(p in path.lower() for p in TEST_PATTERNS):
                    structure.test_files.append(path)
                if any(p in path.upper() for p in DOC_PATTERNS) or path.endswith(".md"):
                    structure.doc_files.append(path)
                if any(p in path.lower() for p in CONFIG_PATTERNS) or basename.startswith("."):
                    structure.config_files.append(path)
                if basename in ("package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml"):
                    structure.manifest_files.append(path)

        logger.info(
            "analyzed_structure",
            commit=sha[:12],
            files=len(structure.file_paths),
            languages=structure.languages,
        )
        return structure

    async def get_commit_history(self, branch: str | None = None, limit: int = 50) -> list[dict]:
        """Get commit history with full stats for persistence.

        Returns parent_shas (enabling merge commit detection), addition/deletion
        counts, and the list of changed file paths.
        """
        repo = await asyncio.to_thread(self._get_repo)
        ref = f"origin/{branch}" if branch else "HEAD"
        commits = []
        for commit in repo.iter_commits(ref, max_count=limit):
            # Accessing commit.stats triggers a git diff — acceptable for ingestion
            stats = commit.stats
            commits.append({
                "sha": commit.hexsha,
                "message": commit.message.strip(),          # full message (first line used on display)
                "author_name": commit.author.name or "",
                "author_email": commit.author.email or "",
                "committed_at": commit.committed_datetime.isoformat() if commit.committed_datetime else None,
                "parent_shas": [p.hexsha for p in commit.parents],
                "is_merge": len(commit.parents) >= 2,
                "stats_additions": stats.total["insertions"],
                "stats_deletions": stats.total["deletions"],
                "files_changed": list(stats.files.keys()),  # file path strings
            })
        return commits

    def cleanup(self) -> None:
        """Remove the mirror directory."""
        if self.mirror_dir.exists():
            shutil.rmtree(self.mirror_dir, ignore_errors=True)
        self._repo = None
