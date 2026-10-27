"""GitHub REST API client using a Personal Access Token (PAT).

This module provides outbound GitHub API calls for:
- Fetching PR metadata (state, merge status, additions/deletions)
- Fetching recent PRs for a repository
- Submitting an approving review on a PR
- Merging a PR

Authentication:
  Set GITHUB_TOKEN in your .env file with a PAT that has:
    - pull_requests:read  — to fetch PR metadata
    - pull_requests:write — to approve or merge

Privacy:
  No source code is sent to GitHub. Only PR metadata requests and approval
  actions are made. The PAT is never logged.

If GITHUB_TOKEN is not set, all methods return "not configured" gracefully.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from prism.config import get_settings
from prism.logging_config import get_logger

logger = get_logger("prism.github_api")

GITHUB_API = "https://api.github.com"


@dataclass
class PRMetadata:
    number: int
    title: str
    state: str            # open | closed
    merged: bool
    merged_at: str | None
    merge_commit_sha: str | None
    author: str | None
    base_branch: str
    head_branch: str
    base_sha: str
    head_sha: str
    additions: int
    deletions: int
    changed_files: int
    body: str | None
    html_url: str
    draft: bool
    mergeable: bool | None
    review_state: str | None   # APPROVED | CHANGES_REQUESTED | COMMENTED | PENDING | None


@dataclass
class ApproveResult:
    success: bool
    message: str
    html_url: str | None = None


@dataclass
class MergeResult:
    success: bool
    message: str
    merge_commit_sha: str | None = None


class GitHubAPIClient:
    """Thin async GitHub REST API v3 client."""

    def __init__(self, token: str | None = None, full_name: str = ""):
        settings = get_settings()
        self._token = token or settings.github_token
        self._full_name = full_name
        self._configured = bool(self._token)

    @property
    def is_configured(self) -> bool:
        return self._configured

    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise RuntimeError("GITHUB_TOKEN not configured.")
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get_pr(self, repo_full_name: str, pr_number: int) -> PRMetadata | None:
        """Fetch metadata for a single PR."""
        if not self._configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f"{GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}",
                    headers=self._headers(),
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                d = resp.json()

                # Get current review state for this PR
                review_state = await self._get_review_state(client, repo_full_name, pr_number)

                return PRMetadata(
                    number=d["number"],
                    title=d["title"],
                    state=d["state"],          # "open" | "closed"
                    merged=d.get("merged", False),
                    merged_at=d.get("merged_at"),
                    merge_commit_sha=d.get("merge_commit_sha"),
                    author=d.get("user", {}).get("login"),
                    base_branch=d["base"]["ref"],
                    head_branch=d["head"]["ref"],
                    base_sha=d["base"]["sha"],
                    head_sha=d["head"]["sha"],
                    additions=d.get("additions", 0),
                    deletions=d.get("deletions", 0),
                    changed_files=d.get("changed_files", 0),
                    body=d.get("body"),
                    html_url=d["html_url"],
                    draft=d.get("draft", False),
                    mergeable=d.get("mergeable"),
                    review_state=review_state,
                )
        except httpx.HTTPStatusError as e:
            logger.warning("github_pr_fetch_failed", pr=pr_number, status=e.response.status_code)
            return None
        except Exception as e:
            logger.warning("github_pr_fetch_error", pr=pr_number, error=str(e))
            return None

    async def list_prs(
        self,
        repo_full_name: str,
        state: str = "all",
        per_page: int = 50,
    ) -> list[PRMetadata]:
        """List recent PRs for a repository (open, closed, or all)."""
        if not self._configured:
            return []
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f"{GITHUB_API}/repos/{repo_full_name}/pulls",
                    headers=self._headers(),
                    params={"state": state, "per_page": per_page, "sort": "updated", "direction": "desc"},
                )
                resp.raise_for_status()
                prs = []
                for d in resp.json():
                    prs.append(PRMetadata(
                        number=d["number"],
                        title=d["title"],
                        state=d["state"],
                        merged=d.get("merged_at") is not None,
                        merged_at=d.get("merged_at"),
                        merge_commit_sha=d.get("merge_commit_sha"),
                        author=d.get("user", {}).get("login"),
                        base_branch=d["base"]["ref"],
                        head_branch=d["head"]["ref"],
                        base_sha=d["base"]["sha"],
                        head_sha=d["head"]["sha"],
                        additions=d.get("additions", 0),
                        deletions=d.get("deletions", 0),
                        changed_files=d.get("changed_files", 0),
                        body=d.get("body"),
                        html_url=d["html_url"],
                        draft=d.get("draft", False),
                        mergeable=d.get("mergeable"),
                        review_state=None,
                    ))
                return prs
        except Exception as e:
            logger.warning("github_list_prs_error", repo=repo_full_name, error=str(e))
            return []

    async def _get_review_state(
        self,
        client: httpx.AsyncClient,
        repo_full_name: str,
        pr_number: int,
    ) -> str | None:
        """Get the current overall review decision for a PR (most recent submitted review)."""
        try:
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}/reviews",
                headers=self._headers(),
                params={"per_page": 50},
            )
            if resp.status_code != 200:
                return None
            reviews = resp.json()
            if not reviews:
                return None
            # Latest submitted review state wins (APPROVED / CHANGES_REQUESTED)
            for review in reversed(reviews):
                state = review.get("state", "")
                if state in ("APPROVED", "CHANGES_REQUESTED"):
                    return state
            return "PENDING"
        except Exception:
            return None

    async def approve_pr(
        self,
        repo_full_name: str,
        pr_number: int,
        body: str = "Approved via PRISM security review.",
    ) -> ApproveResult:
        """Submit an approving review on a PR.

        Requires GITHUB_TOKEN with pull_requests:write scope.
        PRISM only submits an APPROVE after the review_state is READY_FOR_POLICY_REVIEW.
        """
        if not self._configured:
            return ApproveResult(
                success=False,
                message="GITHUB_TOKEN is not configured. Add it to your .env file to enable PR approvals.",
            )
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}/reviews",
                    headers=self._headers(),
                    json={"body": body, "event": "APPROVE"},
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    return ApproveResult(
                        success=True,
                        message=f"PR #{pr_number} approved successfully.",
                        html_url=data.get("html_url") or f"https://github.com/{repo_full_name}/pull/{pr_number}",
                    )
                error = resp.json().get("message", resp.text)
                return ApproveResult(
                    success=False,
                    message=f"GitHub returned {resp.status_code}: {error}",
                )
        except Exception as e:
            return ApproveResult(success=False, message=str(e))

    async def merge_pr(
        self,
        repo_full_name: str,
        pr_number: int,
        commit_title: str | None = None,
        commit_message: str | None = None,
        merge_method: str = "squash",  # merge | squash | rebase
    ) -> MergeResult:
        """Merge a PR via the GitHub API.

        Requires GITHUB_TOKEN with pull_requests:write and contents:write scopes.
        PRISM only merges when review_state is READY_FOR_POLICY_REVIEW and
        no blocking findings exist.
        """
        if not self._configured:
            return MergeResult(
                success=False,
                message="GITHUB_TOKEN is not configured. Add it to your .env file to enable PR merging.",
            )
        try:
            payload: dict[str, str] = {"merge_method": merge_method}
            if commit_title:
                payload["commit_title"] = commit_title
            if commit_message:
                payload["commit_message"] = commit_message

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.put(
                    f"{GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}/merge",
                    headers=self._headers(),
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return MergeResult(
                        success=True,
                        message=data.get("message", f"PR #{pr_number} merged."),
                        merge_commit_sha=data.get("sha"),
                    )
                error = resp.json().get("message", resp.text)
                return MergeResult(success=False, message=f"GitHub {resp.status_code}: {error}")
        except Exception as e:
            return MergeResult(success=False, message=str(e))


def get_github_client(repo_full_name: str = "") -> GitHubAPIClient:
    """Factory — returns a client configured from env vars."""
    settings = get_settings()
    return GitHubAPIClient(token=settings.github_token, full_name=repo_full_name)
