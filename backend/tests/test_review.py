"""Tests for the review workflow and deterministic policy engine."""

import pytest

from prism.core.policy import (
    CheckResult,
    PolicyDecision,
    PolicyEngine,
    PolicyInput,
    ReviewState,
)


class TestPolicyEngine:
    """Test the deterministic review state computation."""

    def setup_method(self):
        self.engine = PolicyEngine()

    def test_analysis_incomplete_when_index_not_done(self):
        inp = PolicyInput(index_complete=False, analysis_complete=True)
        decision = self.engine.evaluate(inp)
        assert decision.state == ReviewState.ANALYSIS_INCOMPLETE
        assert "Indexing has not completed" in decision.reasons[0]

    def test_analysis_incomplete_when_analysis_not_done(self):
        inp = PolicyInput(index_complete=True, analysis_complete=False)
        decision = self.engine.evaluate(inp)
        assert decision.state == ReviewState.ANALYSIS_INCOMPLETE
        assert "Code analysis has not completed" in decision.reasons[0]

    def test_failed_checks_takes_priority(self):
        inp = PolicyInput(
            index_complete=True,
            analysis_complete=True,
            checks=[
                CheckResult(name="ci", status="failed", source="ci"),
                CheckResult(name="lint", status="passed", source="ci"),
            ],
        )
        decision = self.engine.evaluate(inp)
        assert decision.state == ReviewState.FAILED_CHECKS
        assert len(decision.failed_checks) == 1
        assert decision.failed_checks[0].name == "ci"

    def test_blocking_finding_blocks_review(self):
        inp = PolicyInput(
            index_complete=True,
            analysis_complete=True,
            findings=[
                {
                    "title": "SQL Injection",
                    "severity": "high",
                    "confidence": "confirmed",
                    "is_blocking": True,
                },
            ],
        )
        decision = self.engine.evaluate(inp)
        assert decision.state == ReviewState.BLOCKED_BY_FINDING
        assert len(decision.blocking_findings) == 1

    def test_hypothesis_high_severity_does_not_block(self):
        """A hypothesis (unconfirmed) high-severity finding should not block."""
        inp = PolicyInput(
            index_complete=True,
            analysis_complete=True,
            findings=[
                {
                    "title": "Possible issue",
                    "severity": "high",
                    "confidence": "hypothesis",
                    "is_blocking": False,
                },
            ],
        )
        decision = self.engine.evaluate(inp)
        assert decision.state == ReviewState.READY_FOR_POLICY_REVIEW

    def test_security_sensitive_requires_human_review(self):
        inp = PolicyInput(
            index_complete=True,
            analysis_complete=True,
            security_sensitive=True,
        )
        decision = self.engine.evaluate(inp)
        assert decision.state == ReviewState.HUMAN_SECURITY_REVIEW_REQUIRED

    def test_security_sensitive_with_incomplete_checks(self):
        inp = PolicyInput(
            index_complete=True,
            analysis_complete=True,
            security_sensitive=True,
            checks=[
                CheckResult(name="scanner", status="incomplete", source="external"),
            ],
        )
        decision = self.engine.evaluate(inp)
        assert decision.state == ReviewState.HUMAN_SECURITY_REVIEW_REQUIRED
        assert len(decision.incomplete_checks) == 1

    def test_incomplete_checks_require_review(self):
        inp = PolicyInput(
            index_complete=True,
            analysis_complete=True,
            checks=[
                CheckResult(name="scanner", status="incomplete", source="external"),
            ],
        )
        decision = self.engine.evaluate(inp)
        assert decision.state == ReviewState.REVIEW_REQUIRED
        assert len(decision.incomplete_checks) == 1

    def test_all_clear_ready_for_policy_review(self):
        inp = PolicyInput(
            index_complete=True,
            analysis_complete=True,
            checks=[
                CheckResult(name="ci", status="passed", source="ci"),
                CheckResult(name="tests", status="passed", source="test"),
            ],
        )
        decision = self.engine.evaluate(inp)
        assert decision.state == ReviewState.READY_FOR_POLICY_REVIEW

    def test_low_severity_findings_require_review(self):
        inp = PolicyInput(
            index_complete=True,
            analysis_complete=True,
            findings=[
                {
                    "title": "Minor issue",
                    "severity": "low",
                    "confidence": "likely",
                    "is_blocking": False,
                },
            ],
        )
        decision = self.engine.evaluate(inp)
        assert decision.state == ReviewState.REVIEW_REQUIRED

    def test_required_scanner_results_missing(self):
        inp = PolicyInput(
            index_complete=True,
            analysis_complete=True,
            requires_scanner_results=True,
            has_scanner_results=False,
        )
        decision = self.engine.evaluate(inp)
        # Scanner results are required but missing → incomplete check
        assert decision.state == ReviewState.REVIEW_REQUIRED
        assert any(c.name == "scanner_results" for c in decision.incomplete_checks)

    def test_priority_order_failed_before_blocked(self):
        """Failed checks take priority over blocking findings."""
        inp = PolicyInput(
            index_complete=True,
            analysis_complete=True,
            checks=[
                CheckResult(name="ci", status="failed", source="ci"),
            ],
            findings=[
                {
                    "title": "Critical",
                    "severity": "critical",
                    "confidence": "confirmed",
                    "is_blocking": True,
                },
            ],
        )
        decision = self.engine.evaluate(inp)
        assert decision.state == ReviewState.FAILED_CHECKS

    def test_blocked_before_security_sensitive(self):
        """Blocking findings take priority over security-sensitive flag."""
        inp = PolicyInput(
            index_complete=True,
            analysis_complete=True,
            security_sensitive=True,
            findings=[
                {
                    "title": "Critical",
                    "severity": "high",
                    "confidence": "confirmed",
                    "is_blocking": True,
                },
            ],
        )
        decision = self.engine.evaluate(inp)
        assert decision.state == ReviewState.BLOCKED_BY_FINDING
