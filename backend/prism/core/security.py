"""Security utilities: URL validation, SSRF protection, secret handling."""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from prism.logging_config import get_logger

logger = get_logger("prism.security")

# Internal / metadata-service IP ranges to block (SSRF protection)
_BLOCKED_HOSTS = {
    "169.254.169.254",  # AWS metadata
    "metadata.google.internal",  # GCP metadata
    "metadata.azure.com",  # Azure metadata
    "0.0.0.0",
    "localhost",
    "127.0.0.1",
    "::1",
}

# Private IP ranges
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # IPv6 private
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]

# Allowed Git URL schemes
_ALLOWED_SCHEMES = {"https", "http", "git", "ssh", "file"}

# GitHub/GitLab URL patterns for provider detection
_GITHUB_RE = re.compile(r"(?:github\.com)[:/](.+?)/(.+?)(?:\.git)?/?$", re.IGNORECASE)
_GITLAB_RE = re.compile(r"(?:gitlab\.com)[:/](.+?)/(.+?)(?:\.git)?/?$", re.IGNORECASE)
_BITBUCKET_RE = re.compile(r"(?:bitbucket\.org)[:/](.+?)/(.+?)(?:\.git)?/?$", re.IGNORECASE)


@dataclass
class RepoUrlValidation:
    is_valid: bool
    provider: str
    full_name: str
    error: str | None = None


def _is_ip_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        for network in _PRIVATE_NETWORKS:
            if ip in network:
                return True
    except ValueError:
        return False
    return False


def _resolve_host(hostname: str) -> list[str]:
    """Resolve hostname to IP addresses."""
    try:
        _, _, addresses = socket.gethostbyname_ex(hostname)
        return addresses
    except socket.gaierror:
        return []


def validate_repo_url(url: str, allow_local: bool = False) -> RepoUrlValidation:
    """
    Validate a Git repository URL with SSRF protection.

    Args:
        url: The repository URL to validate.
        allow_local: If True, allow localhost / file:// URLs (for testing).

    Returns:
        RepoUrlValidation with validity, provider, and full name.
    """
    if not url or not url.strip():
        return RepoUrlValidation(False, "unknown", "", "URL is empty")

    # Handle SSH-style URLs: git@github.com:owner/repo.git
    ssh_match = re.match(r"^(?:[\w.-]+)@([\w.-]+):(.+?)(?:\.git)?/?$", url)
    if ssh_match and "://" not in url:
        host = ssh_match.group(1)
        path = ssh_match.group(2)

        # Extract full_name from path
        path_parts = [p for p in path.split("/") if p]
        if len(path_parts) >= 2:
            full_name = f"{path_parts[0]}/{path_parts[1]}"
        else:
            full_name = path

        provider = "other"
        if "github.com" in host:
            provider = "github"
        elif "gitlab.com" in host:
            provider = "gitlab"
        elif "bitbucket.org" in host:
            provider = "bitbucket"

        # SSRF check for SSH URLs too
        if not allow_local:
            if host.lower() in _BLOCKED_HOSTS:
                return RepoUrlValidation(
                    False, provider, full_name,
                    f"Blocked: host '{host}' is an internal/metadata endpoint (SSRF protection)."
                )

        return RepoUrlValidation(True, provider, full_name)

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme not in _ALLOWED_SCHEMES:
        return RepoUrlValidation(
            False, "unknown", "",
            f"URL scheme '{scheme}' not allowed. Use https, git, ssh, or file."
        )

    # Provider detection and name extraction
    provider = "other"
    full_name = ""

    if scheme in ("http", "https", "git", "ssh"):
        host = parsed.hostname or ""
        path = parsed.path.strip("/")

        # Extract full_name from path
        path_parts = [p for p in path.split("/") if p and p != "repos"]
        if len(path_parts) >= 2:
            full_name = f"{path_parts[0]}/{path_parts[1].removesuffix('.git')}"

        if "github.com" in host:
            provider = "github"
        elif "gitlab.com" in host:
            provider = "gitlab"
        elif "bitbucket.org" in host:
            provider = "bitbucket"

        # SSRF check: block internal IPs unless explicitly allowed
        if not allow_local:
            if host.lower() in _BLOCKED_HOSTS:
                return RepoUrlValidation(
                    False, provider, full_name,
                    f"Blocked: host '{host}' is an internal/metadata endpoint (SSRF protection)."
                )

            resolved = _resolve_host(host)
            for ip_str in resolved:
                if _is_ip_blocked(ip_str):
                    return RepoUrlValidation(
                        False, provider, full_name,
                        f"Blocked: host '{host}' resolves to private IP {ip_str} (SSRF protection)."
                    )
    elif scheme == "file":
        provider = "local"
        full_name = parsed.path.strip("/").replace("\\", "/")
        if not allow_local:
            # Allow file:// for local testing but log a warning
            logger.warning("file_url_used", url="file://...", message="Local file URL used — ensure this is intentional")

    if not full_name:
        # Fall back to host/path
        full_name = parsed.path.strip("/") or url

    return RepoUrlValidation(True, provider, full_name)


def detect_provider(url: str) -> str:
    """Quick provider detection without full validation."""
    if _GITHUB_RE.search(url):
        return "github"
    if _GITLAB_RE.search(url):
        return "gitlab"
    if _BITBUCKET_RE.search(url):
        return "bitbucket"
    if url.startswith("file://") or url.startswith("/"):
        return "local"
    return "other"


def redact_secret(value: str | None) -> str:
    """Redact a secret value for logging, keeping only a prefix."""
    if not value:
        return "[none]"
    if len(value) <= 8:
        return "[REDACTED]"
    return value[:4] + "...[REDACTED]"
