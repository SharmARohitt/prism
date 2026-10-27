"""Tests for Git mirror management."""

import asyncio
from pathlib import Path

import pytest

from prism.core.git_mirror import (
    ChangedFile,
    GitMirror,
    detect_language,
    compute_content_hash,
)


class TestDetectLanguage:
    def test_python(self):
        assert detect_language("src/app.py") == "python"

    def test_no_language(self):
        assert detect_language("README") is None


class TestComputeContentHash:
    def test_string_hash(self):
        h = compute_content_hash("hello")
        assert len(h) == 64

    def test_bytes_hash(self):
        h = compute_content_hash(b"hello")
        assert len(h) == 64

    def test_consistent_hash(self):
        assert compute_content_hash("hello") == compute_content_hash("hello")

    def test_different_inputs_different_hash(self):
        assert compute_content_hash("hello") != compute_content_hash("world")


class TestGitMirror:
    """Test Git mirror operations with a local test repository."""

    def test_mirror_path_property(self, mock_git_repo):
        mirror = GitMirror("test-repo-id", mock_git_repo, Path(mock_git_repo) / "mirror")
        assert mirror.mirror_path == Path(mock_git_repo) / "mirror"

    def test_exists_false_for_nonexistent(self, tmp_path):
        mirror = GitMirror("nonexistent", str(tmp_path / "fake"), tmp_path / "fake-mirror")
        assert not mirror.exists

    @pytest.mark.asyncio
    async def test_clone_and_get_head_sha(self, mock_git_repo):
        """Test cloning a repository and getting the HEAD SHA."""
        mirror_dir = mock_git_repo + "-mirror"
        mirror = GitMirror("test-clone", mock_git_repo, Path(mirror_dir))

        # Clone happens on first access
        sha = await mirror.get_head_sha()
        assert len(sha) == 40  # Full SHA-1 hex

        assert mirror.exists

    @pytest.mark.asyncio
    async def test_get_commit_info(self, mock_git_repo):
        """Test getting commit metadata."""
        mirror_dir = mock_git_repo + "-mirror"
        mirror = GitMirror("test-commit", mock_git_repo, Path(mirror_dir))

        sha = await mirror.get_head_sha()
        info = await mirror.get_commit_info(sha)

        assert info["sha"] == sha
        assert info["message"] == "Initial commit"
        assert info["author_name"] == "Test User"
        assert info["stats_additions"] >= 1

    @pytest.mark.asyncio
    async def test_analyze_structure(self, mock_git_repo):
        """Test repository structure analysis."""
        mirror_dir = mock_git_repo + "-mirror"
        mirror = GitMirror("test-structure", mock_git_repo, Path(mirror_dir))

        sha = await mirror.get_head_sha()
        structure = await mirror.analyze_structure(sha)

        assert structure.commit_sha == sha
        assert "app.py" in structure.file_paths
        assert "python" in structure.languages
        assert structure.languages["python"] >= 1

    @pytest.mark.asyncio
    async def test_get_file_content(self, mock_git_repo):
        """Test reading file content at a commit."""
        mirror_dir = mock_git_repo + "-mirror"
        mirror = GitMirror("test-content", mock_git_repo, Path(mirror_dir))

        sha = await mirror.get_head_sha()
        content = await mirror.get_file_content("app.py", sha)
        assert content is not None
        assert "hello" in content.lower()

    @pytest.mark.asyncio
    async def test_get_file_content_nonexistent(self, mock_git_repo):
        """Test reading a non-existent file returns None."""
        mirror_dir = mock_git_repo + "-mirror"
        mirror = GitMirror("test-missing", mock_git_repo, Path(mirror_dir))

        content = await mirror.get_file_content("nonexistent.py", "HEAD")
        assert content is None

    @pytest.mark.asyncio
    async def test_get_recent_commits(self, mock_git_repo):
        """Test getting recent commit history."""
        mirror_dir = mock_git_repo + "-mirror"
        mirror = GitMirror("test-history", mock_git_repo, Path(mirror_dir))

        commits = await mirror.get_recent_commits(limit=10)
        assert len(commits) >= 1
        assert commits[0]["message"] == "Initial commit"

    @pytest.mark.asyncio
    async def test_get_file_content_lines(self, mock_git_repo):
        """Test reading specific line ranges."""
        mirror_dir = mock_git_repo + "-mirror"
        mirror = GitMirror("test-lines", mock_git_repo, Path(mirror_dir))

        lines = await mirror.get_file_content_lines("app.py", 1, 3, "HEAD")
        assert len(lines) <= 3

    @pytest.mark.asyncio
    async def test_get_default_branch(self, mock_git_repo):
        """Test detecting the default branch."""
        mirror_dir = mock_git_repo + "-mirror"
        mirror = GitMirror("test-branch", mock_git_repo, Path(mirror_dir))

        branch = await mirror.get_default_branch()
        assert branch in ("master", "main")
