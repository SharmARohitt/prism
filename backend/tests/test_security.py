"""Tests for security utilities: URL validation, SSRF protection."""

import pytest

from prism.core.security import (
    detect_provider,
    redact_secret,
    validate_repo_url,
)


class TestValidateRepoUrl:
    """Test repository URL validation with SSRF protection."""

    def test_valid_github_url(self):
        result = validate_repo_url("https://github.com/owner/repo")
        assert result.is_valid
        assert result.provider == "github"
        assert result.full_name == "owner/repo"

    def test_valid_github_url_with_git_extension(self):
        result = validate_repo_url("https://github.com/owner/repo.git")
        assert result.is_valid
        assert result.provider == "github"
        assert result.full_name == "owner/repo"

    def test_valid_gitlab_url(self):
        result = validate_repo_url("https://gitlab.com/owner/repo")
        assert result.is_valid
        assert result.provider == "gitlab"

    def test_valid_bitbucket_url(self):
        result = validate_repo_url("https://bitbucket.org/owner/repo")
        assert result.is_valid
        assert result.provider == "bitbucket"

    def test_empty_url_rejected(self):
        result = validate_repo_url("")
        assert not result.is_valid
        assert "empty" in result.error.lower()

    def test_whitespace_url_rejected(self):
        result = validate_repo_url("   ")
        assert not result.is_valid

    def test_invalid_scheme_rejected(self):
        result = validate_repo_url("ftp://example.com/repo")
        assert not result.is_valid
        assert "scheme" in result.error.lower()

    def test_localhost_blocked_by_default(self):
        result = validate_repo_url("http://127.0.0.1/myrepo")
        # 127.0.0.1 is in blocked hosts
        assert not result.is_valid
        assert "ssrf" in result.error.lower() or "internal" in result.error.lower()

    def test_localhost_allowed_when_flag_set(self):
        result = validate_repo_url("http://127.0.0.1/myrepo", allow_local=True)
        assert result.is_valid

    def test_file_url_allowed_with_flag(self):
        result = validate_repo_url("file:///path/to/repo", allow_local=True)
        assert result.is_valid
        assert result.provider == "local"

    def test_ssh_github_url(self):
        result = validate_repo_url("git@github.com:owner/repo.git")
        assert result.is_valid
        assert result.provider == "github"

    def test_metadata_endpoint_blocked(self):
        result = validate_repo_url("http://169.254.169.254/latest/meta-data/")
        assert not result.is_valid
        assert "metadata" in result.error.lower() or "ssrf" in result.error.lower()


class TestDetectProvider:
    def test_github(self):
        assert detect_provider("https://github.com/owner/repo") == "github"

    def test_gitlab(self):
        assert detect_provider("https://gitlab.com/owner/repo") == "gitlab"

    def test_bitbucket(self):
        assert detect_provider("https://bitbucket.org/owner/repo") == "bitbucket"

    def test_local(self):
        assert detect_provider("file:///path/to/repo") == "local"

    def test_other(self):
        assert detect_provider("https://custom-git.example.com/repo") == "other"


class TestRedactSecret:
    def test_none_value(self):
        assert redact_secret(None) == "[none]"

    def test_short_value(self):
        assert redact_secret("abc") == "[REDACTED]"

    def test_long_value_shows_prefix(self):
        result = redact_secret("very-long-secret-token-value")
        assert result.startswith("very")
        assert "[REDACTED]" in result

    def test_empty_string(self):
        assert redact_secret("") == "[none]"
