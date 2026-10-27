"""Scanner integration adapters — Coverity and Black Duck.

These are real adapter interfaces. They define the exact contract needed to
connect to each scanner's API or report export. If credentials are not
configured, the adapters return a clearly-labelled "not configured" status.

PRISM never invents scanner APIs. If integration details are unavailable,
the adapter documents the required credentials and contract.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from prism.config import get_settings
from prism.logging_config import get_logger

logger = get_logger("prism.scanners")


@dataclass
class ScannerFinding:
    title: str
    description: str
    severity: str
    file_path: str | None
    line_range: list[int]
    rule_id: str | None
    scanner_source: str
    raw_data: dict = field(default_factory=dict)


@dataclass
class ScanResult:
    scanner_name: str
    configured: bool
    findings: list[ScannerFinding] = field(default_factory=list)
    status: str = "unknown"
    error: str | None = None
    summary: dict = field(default_factory=dict)


class ScannerAdapter(ABC):
    """Abstract scanner adapter interface."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    async def get_findings(self, repository_full_name: str, commit_sha: str | None = None) -> ScanResult: ...


class CoverityAdapter(ScannerAdapter):
    """Coverity integration adapter.

    Contract requirements:
    - COVERITY_API_URL: The Coverity API endpoint (e.g. https://coverity.example.com/api)
    - COVERITY_API_TOKEN: Authentication token for the Coverity REST API

    The adapter fetches findings for a specific project/stream and commit.
    If credentials are not set, it returns a "not configured" result rather
    than making up findings.
    """

    @property
    def name(self) -> str:
        return "coverity"

    @property
    def is_configured(self) -> bool:
        settings = get_settings()
        return bool(settings.coverity_api_url and settings.coverity_api_token)

    async def get_findings(self, repository_full_name: str, commit_sha: str | None = None) -> ScanResult:
        if not self.is_configured:
            return ScanResult(
                scanner_name=self.name,
                configured=False,
                status="not_configured",
                error="Coverity integration not configured. Set COVERITY_API_URL and COVERITY_API_TOKEN.",
            )

        settings = get_settings()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Coverity REST API — project/stream findings endpoint
                # This is a documented contract. The actual endpoint structure
                # depends on the Coverity deployment.
                resp = await client.get(
                    f"{settings.coverity_api_url}/v2/projects/{repository_full_name}/mergedefs",
                    headers={"Authorization": f"Bearer {settings.coverity_api_token}"},
                    params={"commit": commit_sha} if commit_sha else {},
                )
                resp.raise_for_status()
                data = resp.json()

                findings = []
                for issue in data.get("issues", []):
                    findings.append(ScannerFinding(
                        title=issue.get("checkerName", "Unknown Coverity finding"),
                        description=issue.get("subcategory", ""),
                        severity=self._map_severity(issue.get("impact", "medium")),
                        file_path=issue.get("filePath"),
                        line_range=[issue.get("lineNumber", 0), issue.get("lineNumber", 0)],
                        rule_id=issue.get("checkerName"),
                        scanner_source=self.name,
                        raw_data=issue,
                    ))

                return ScanResult(
                    scanner_name=self.name,
                    configured=True,
                    findings=findings,
                    status="ok",
                    summary={
                        "total_findings": len(findings),
                        "by_severity": self._severity_counts(findings),
                    },
                )

        except Exception as e:
            logger.error("coverity_fetch_failed", error=str(e))
            return ScanResult(
                scanner_name=self.name,
                configured=True,
                status="error",
                error=str(e),
            )

    def _map_severity(self, raw: str) -> str:
        mapping = {"high": "high", "medium": "medium", "low": "low"}
        return mapping.get(raw.lower(), "medium")

    def _severity_counts(self, findings: list[ScannerFinding]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return counts


class BlackDuckAdapter(ScannerAdapter):
    """Black Duck integration adapter.

    Contract requirements:
    - BLACKDUCK_URL: The Black Duck server URL (e.g. https://blackduck.example.com)
    - BLACKDUCK_API_TOKEN: API token for Black Duck REST API

    The adapter fetches security findings and component vulnerability data
    for the project associated with the repository.
    """

    @property
    def name(self) -> str:
        return "blackduck"

    @property
    def is_configured(self) -> bool:
        settings = get_settings()
        return bool(settings.blackduck_url and settings.blackduck_api_token)

    async def get_findings(self, repository_full_name: str, commit_sha: str | None = None) -> ScanResult:
        if not self.is_configured:
            return ScanResult(
                scanner_name=self.name,
                configured=False,
                status="not_configured",
                error="Black Duck integration not configured. Set BLACKDUCK_URL and BLACKDUCK_API_TOKEN.",
            )

        settings = get_settings()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Black Duck REST API — project version vulnerabilities endpoint
                # This is a documented contract. The actual project mapping
                # depends on the Black Duck deployment.
                resp = await client.get(
                    f"{settings.blackduck_url}/api/projects/{repository_full_name}/versions",
                    headers={
                        "Authorization": f"token {settings.blackduck_api_token}",
                        "Accept": "application/vnd.blackducksoftware-project-detail+json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                findings = []
                for vuln in data.get("vulnerabilities", []):
                    findings.append(ScannerFinding(
                        title=f"Vulnerability: {vuln.get('vulnerabilityName', 'Unknown')}",
                        description=vuln.get("description", ""),
                        severity=self._map_bd_severity(vuln.get("severity", "low")),
                        file_path=None,
                        line_range=[],
                        rule_id=vuln.get("vulnerabilityName"),
                        scanner_source=self.name,
                        raw_data=vuln,
                    ))

                return ScanResult(
                    scanner_name=self.name,
                    configured=True,
                    findings=findings,
                    status="ok",
                    summary={
                        "total_findings": len(findings),
                        "by_severity": self._severity_counts(findings),
                    },
                )

        except Exception as e:
            logger.error("blackduck_fetch_failed", error=str(e))
            return ScanResult(
                scanner_name=self.name,
                configured=True,
                status="error",
                error=str(e),
            )

    def _map_bd_severity(self, raw: str) -> str:
        mapping = {"critical": "critical", "high": "high", "medium": "medium", "low": "low"}
        return mapping.get(raw.lower(), "low")

    def _severity_counts(self, findings: list[ScannerFinding]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return counts


def get_scanner_adapters() -> list[ScannerAdapter]:
    """Return all configured scanner adapters."""
    return [CoverityAdapter(), BlackDuckAdapter()]
