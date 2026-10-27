"""Deterministic policy rules for review state determination.

Review states are computed by explicit rules, NOT by free-form model responses.
This ensures that safety decisions are auditable and consistent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from prism.models import FindingSeverity, ReviewState


@dataclass
class CheckResult:
    name: str
    status: str  # passed, failed, incomplete, unknown
    source: str
    details: str | None = None


@dataclass
class PolicyInput:
    """All inputs needed to compute a review state."""
    findings: list[dict] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    analysis_complete: bool = True
    index_complete: bool = True
    security_sensitive: bool = False
    has_scanner_results: bool = False
    requires_scanner_results: bool = False


@dataclass
class PolicyDecision:
    state: ReviewState
    reasons: list[str]
    blocking_findings: list[dict]
    failed_checks: list[CheckResult]
    incomplete_checks: list[CheckResult]


class PolicyEngine:
    """Computes review states from explicit, deterministic rules."""

    def evaluate(self, inp: PolicyInput) -> PolicyDecision:
        """
        Apply rules in priority order. The first matching rule wins.

        Priority:
        1. ANALYSIS_INCOMPLETE — if indexing or analysis isn't done, we can't say anything.
        2. FAILED_CHECKS — if CI/tests/scanners failed, that takes precedence.
        3. BLOCKED_BY_FINDING — if there's a blocking finding with confirmed evidence.
        4. HUMAN_SECURITY_REVIEW_REQUIRED — if change is security-sensitive and needs human review.
        5. REVIEW_REQUIRED — default state for any change.
        6. READY_FOR_POLICY_REVIEW — only when all checks pass and no concerns.
        """
        reasons: list[str] = []
        blocking_findings = []
        failed_checks = []
        incomplete_checks = []

        # 1. Analysis incomplete
        if not inp.index_complete:
            return PolicyDecision(
                ReviewState.ANALYSIS_INCOMPLETE,
                ["Indexing has not completed for this commit."],
                [], [], [],
            )
        if not inp.analysis_complete:
            return PolicyDecision(
                ReviewState.ANALYSIS_INCOMPLETE,
                ["Code analysis has not completed for this change."],
                [], [], [],
            )

        # Categorize checks
        for check in inp.checks:
            if check.status == "failed":
                failed_checks.append(check)
            elif check.status in ("incomplete", "unknown", "missing"):
                incomplete_checks.append(check)

        # Check required checks
        if inp.requires_scanner_results and not inp.has_scanner_results:
            incomplete_checks.append(CheckResult(
                name="scanner_results",
                status="incomplete",
                source="policy",
                details="Required scanner results are not available.",
            ))

        # 2. Failed checks
        if failed_checks:
            reasons.append(f"{len(failed_checks)} check(s) failed: " + ", ".join(c.name for c in failed_checks))
            return PolicyDecision(
                ReviewState.FAILED_CHECKS,
                reasons,
                [],
                failed_checks,
                incomplete_checks,
            )

        # 3. Blocking findings (confirmed or likely, high/critical severity)
        for f in inp.findings:
            severity = f.get("severity", "info")
            confidence = f.get("confidence", "hypothesis")
            is_blocking = f.get("is_blocking", False)

            # Auto-block on confirmed critical/high findings
            if severity in ("critical", "high") and confidence in ("confirmed", "likely"):
                blocking_findings.append(f)

        if blocking_findings:
            titles = [f.get("title", "unknown") for f in blocking_findings]
            reasons.append(f"Blocked by {len(blocking_findings)} high-severity finding(s): " + ", ".join(titles))
            return PolicyDecision(
                ReviewState.BLOCKED_BY_FINDING,
                reasons,
                blocking_findings,
                [],
                incomplete_checks,
            )

        # 4. Security-sensitive changes require human review
        if inp.security_sensitive:
            reasons.append("This change touches security-sensitive code areas and requires human security review.")
            if incomplete_checks:
                reasons.append(f"{len(incomplete_checks)} check(s) remain incomplete.")
            return PolicyDecision(
                ReviewState.HUMAN_SECURITY_REVIEW_REQUIRED,
                reasons,
                [],
                [],
                incomplete_checks,
            )

        # 5. Incomplete checks (but not failed)
        if incomplete_checks:
            reasons.append(f"{len(incomplete_checks)} check(s) are incomplete: " + ", ".join(c.name for c in incomplete_checks))
            return PolicyDecision(
                ReviewState.REVIEW_REQUIRED,
                reasons,
                [],
                [],
                incomplete_checks,
            )

        # 6. All clear
        if not inp.findings:
            return PolicyDecision(
                ReviewState.READY_FOR_POLICY_REVIEW,
                ["All required checks passed. No findings detected. "
                 "Note: this does not guarantee the change is safe — only that automated checks are complete."],
                [], [], [],
            )

        # Has findings but none blocking
        low_findings = [f for f in inp.findings if f.get("severity") in ("low", "info")]
        if low_findings:
            reasons.append(f"{len(low_findings)} low-severity finding(s) detected. Manual review recommended.")
            return PolicyDecision(
                ReviewState.REVIEW_REQUIRED,
                reasons,
                [],
                [],
                incomplete_checks,
            )

        return PolicyDecision(
            ReviewState.READY_FOR_POLICY_REVIEW,
            ["All checks passed."],
            [], [], [],
        )


policy_engine = PolicyEngine()
