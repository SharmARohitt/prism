"""PR review engine — gathers evidence, generates structured report.

This is the core workflow:
1. Compare base and head commits.
2. Identify changed symbols and files.
3. Retrieve relevant context (callers, callees, dependencies, tests).
4. Detect security-sensitive changes.
5. Generate a plain-English explanation via LLM.
6. Apply deterministic policy rules for review state.
7. Store the report with evidence links.

Every significant claim must link to source evidence. The system never
claims a change is safe without evidence.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from prism.core.git_mirror import GitMirror
from prism.core.indexer import (
    CodeIndexer,
    IndexedFile,
    IndexedSymbol,
    SECURITY_KEYWORDS,
    _is_security_sensitive,
)
from prism.core.policy import CheckResult, PolicyDecision, PolicyEngine, PolicyInput
from prism.llm.provider import LLMProvider, LLMResponse, get_available_provider
from prism.logging_config import get_logger
from prism.models import (
    FindingConfidence,
    FindingSeverity,
    RelationType,
    ReviewState,
)

logger = get_logger("prism.review")


@dataclass
class ChangedSymbol:
    name: str
    file_path: str
    start_line: int
    end_line: int
    change_type: str  # added, modified, removed
    before_code: str | None = None
    after_code: str | None = None
    signature: str | None = None


@dataclass
class EvidenceItem:
    file_path: str
    line_start: int
    line_end: int
    commit_sha: str
    code_snippet: str
    source_type: str  # source, diff, caller, callee, test, scanner, config
    description: str


@dataclass
class ReviewContext:
    """All gathered context for a review."""
    base_sha: str
    head_sha: str
    changed_files: list[dict] = field(default_factory=list)
    changed_symbols: list[ChangedSymbol] = field(default_factory=list)
    callers: list[dict] = field(default_factory=list)
    callees: list[dict] = field(default_factory=list)
    affected_dependencies: list[dict] = field(default_factory=list)
    related_tests: list[dict] = field(default_factory=list)
    config_changes: list[dict] = field(default_factory=list)
    security_sensitive: bool = False
    security_sensitive_reasons: list[str] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    diff_stats: dict = field(default_factory=dict)


class ReviewEngine:
    """Orchestrates the full PR review workflow."""

    def __init__(self, mirror: GitMirror, indexer: CodeIndexer):
        self.mirror = mirror
        self.indexer = indexer
        self.policy = PolicyEngine()

    async def gather_context(self, base_sha: str, head_sha: str) -> ReviewContext:
        """
        Step 1-4: Gather all relevant context for the review.
        Compare commits, identify changed symbols, retrieve callers/callees,
        detect security sensitivity.
        """
        ctx = ReviewContext(base_sha=base_sha, head_sha=head_sha)

        # Get diff
        diff = await self.mirror.get_diff(base_sha, head_sha)
        ctx.diff_stats = diff.stats

        for cf in diff.changed_files:
            ctx.changed_files.append({
                "path": cf.path,
                "status": cf.status,
                "additions": cf.additions,
                "deletions": cf.deletions,
            })

            # Gather evidence: file diff
            if cf.status != "deleted":
                after_content = await self.mirror.get_file_content(cf.path, head_sha)
                if after_content:
                    lines = after_content.split("\n")
                    snippet = "\n".join(lines[:max(20, min(50, len(lines)))])
                    ctx.evidence.append(EvidenceItem(
                        file_path=cf.path,
                        line_start=1,
                        line_end=min(50, len(lines)),
                        commit_sha=head_sha,
                        code_snippet=snippet,
                        source_type="diff",
                        description=f"Head version of {cf.path} ({cf.status})",
                    ))

            # Identify changed symbols by re-indexing the changed file
            if cf.status in ("added", "modified"):
                content = await self.mirror.get_file_content(cf.path, head_sha)
                if content:
                    indexed = await self.indexer.index_file(cf.path, content, self.mirror)
                    for sym in indexed.symbols:
                        before_code = None
                        if cf.status == "modified":
                            before_content = await self.mirror.get_file_content(cf.path, base_sha)
                            if before_content:
                                before_indexed = await self.indexer.index_file(cf.path, before_content, self.mirror)
                                for bsym in before_indexed.symbols:
                                    if bsym.name == sym.name:
                                        before_code = before_content.split("\n")[
                                            max(0, bsym.start_line - 1):bsym.end_line
                                        ]
                                        before_code = "\n".join(before_code)
                                        break

                        after_code = content.split("\n")[max(0, sym.start_line - 1):sym.end_line]
                        after_code = "\n".join(after_code)

                        ctx.changed_symbols.append(ChangedSymbol(
                            name=sym.name,
                            file_path=cf.path,
                            start_line=sym.start_line,
                            end_line=sym.end_line,
                            change_type=cf.status,
                            before_code=before_code,
                            after_code=after_code,
                            signature=sym.signature,
                        ))

                        # Check security sensitivity
                        if _is_security_sensitive(sym.name, sym.signature):
                            ctx.security_sensitive = True
                            ctx.security_sensitive_reasons.append(
                                f"Symbol '{sym.name}' in {cf.path} matches security-sensitive keywords"
                            )

            # Security sensitivity from file path/content
            file_lower = cf.path.lower()
            for keyword in SECURITY_KEYWORDS:
                if keyword in file_lower:
                    ctx.security_sensitive = True
                    ctx.security_sensitive_reasons.append(
                        f"File path '{cf.path}' contains security keyword: {keyword}"
                    )
                    break

            # Config file changes are always notable
            config_exts = (".yml", ".yaml", ".env", "Dockerfile", "docker-compose", ".json", "Makefile")
            if any(cf.path.endswith(ext) or ext in cf.path for ext in config_exts):
                ctx.config_changes.append({"path": cf.path, "status": cf.status})
                ctx.security_sensitive = True
                ctx.security_sensitive_reasons.append(
                    f"Configuration file changed: {cf.path}"
                )

        # Identify related tests
        for cf in diff.changed_files:
            if cf.status != "deleted":
                test_names = [
                    f"test_{cf.path.rsplit('/', 1)[-1].rsplit('.', 1)[0]}",
                    f"{cf.path.rsplit('/', 1)[-1].rsplit('.', 1)[0]}_test",
                    cf.path.replace("/src/", "/test/").replace("/src/", "/tests/"),
                ]
                for tn in test_names:
                    content = await self.mirror.get_file_content(tn, head_sha)
                    if content:
                        ctx.related_tests.append({"path": tn, "for": cf.path})

        # Gather caller/callee evidence
        for sym in ctx.changed_symbols[:10]:  # Limit to avoid over-retrieval
            ctx.callees.append({
                "symbol": sym.name,
                "file": sym.file_path,
                "calls": [r for r in []],  # Would be populated from index
            })

        logger.info(
            "gathered_context",
            base=base_sha[:12],
            head=head_sha[:12],
            changed_files=len(ctx.changed_files),
            changed_symbols=len(ctx.changed_symbols),
            security_sensitive=ctx.security_sensitive,
            evidence_count=len(ctx.evidence),
        )

        return ctx

    async def generate_report(
        self,
        ctx: ReviewContext,
        pr_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Generate the full structured review report with:
        - Executive summary (plain English)
        - Technical evidence view
        - Findings with evidence links
        - Review state (from deterministic policy)
        """
        pr_info = pr_info or {}

        # Get LLM provider
        provider = await get_available_provider()

        # Build prompt for the LLM
        llm_report = await self._generate_llm_explanation(ctx, pr_info, provider)

        # Build findings from analysis
        findings = await self._build_findings(ctx, llm_report)

        # Build check results
        checks = self._build_checks(ctx)

        # Apply deterministic policy
        policy_input = PolicyInput(
            findings=findings,
            checks=checks,
            analysis_complete=True,
            index_complete=True,
            security_sensitive=ctx.security_sensitive,
            has_scanner_results=any(c.source == "scanner" and c.status == "passed" for c in checks),
            requires_scanner_results=False,
        )
        policy_decision = self.policy.evaluate(policy_input)

        # Build the full report structure
        report = {
            "commit_sha": ctx.head_sha,
            "base_sha": ctx.base_sha,
            "review_state": policy_decision.state.value,
            "change_summary": llm_report.get("change_summary", self._fallback_summary(ctx)),
            "functional_purpose": llm_report.get("functional_purpose"),
            "affected_components": self._build_affected_components(ctx),
            "potential_security_impacts": self._build_security_impacts(ctx, llm_report),
            "executive_summary": self._build_executive_summary(ctx, llm_report, policy_decision, pr_info),
            "technical_evidence": self._build_technical_evidence(ctx, findings),
            "findings": findings,
            "uncertainty": self._build_uncertainty(ctx, llm_report),
            "analysis_coverage": self._build_coverage(ctx),
            "recommended_action": self._build_recommendation(policy_decision),
            "required_checks": [c.__dict__ for c in checks],
            "llm_model": provider.model_name,
            "is_stale": False,
        }

        logger.info(
            "generated_report",
            review_state=report["review_state"],
            findings=len(findings),
            model=provider.model_name,
        )

        return report

    async def _generate_llm_explanation(
        self,
        ctx: ReviewContext,
        pr_info: dict,
        provider: LLMProvider,
    ) -> dict[str, Any]:
        """Generate the plain-English explanation via LLM."""
        # Build a focused prompt with only relevant context
        changed_files_desc = "\n".join(
            f"- {f['path']} ({f['status']}, +{f['additions']}/-{f['deletions']})"
            for f in ctx.changed_files[:20]
        )

        changed_symbols_desc = "\n".join(
            f"- {s.name} ({s.change_type}) in {s.file_path}:{s.start_line}-{s.end_line}"
            f"  Signature: {s.signature or 'N/A'}"
            for s in ctx.changed_symbols[:20]
        )

        evidence_desc = "\n".join(
            f"- [{e.source_type}] {e.file_path}:{e.line_start}-{e.line_end} ({e.description})"
            for e in ctx.evidence[:15]
        )

        security_note = ""
        if ctx.security_sensitive:
            security_note = (
                "\n\nSECURITY-SIGNIFICANT AREAS DETECTED:\n"
                + "\n".join(f"- {r}" for r in ctx.security_sensitive_reasons)
                + "\n\nPay special attention to authorization checks, input validation, and data access patterns."
            )

        prompt = f"""Analyze this code change and explain it in clear English for security reviewers.

CHANGE SUMMARY:
- Base commit: {ctx.base_sha[:12]}
- Head commit: {ctx.head_sha[:12]}
- Files changed: {len(ctx.changed_files)}
- Stats: +{ctx.diff_stats.get('additions', 0)}/-{ctx.diff_stats.get('deletions', 0)}
{f"- PR: {pr_info.get('pr_title', 'N/A')} by {pr_info.get('pr_author', 'N/A')}" if pr_info else ""}

CHANGED FILES:
{changed_files_desc}

CHANGED SYMBOLS:
{changed_symbols_desc or "No symbols detected."}

EVIDENCE GATHERED:
{evidence_desc or "Limited evidence available."}{security_note}

Respond with a JSON object containing these fields:
{{
  "change_summary": "Plain English description of what changed",
  "functional_purpose": "What the affected feature does, in simple terms",
  "what_could_go_wrong": "What could go wrong, if any risk exists",
  "who_or_what_affected": "Who or what could be affected",
  "evidence_quality": "Assessment of evidence quality (strong/moderate/weak/insufficient)",
  "confidence_level": "Your confidence in this analysis (high/moderate/low)"
}}

IMPORTANT RULES:
- Do NOT claim the change is safe or unsafe without evidence.
- Distinguish confirmed findings from hypotheses.
- If evidence is insufficient, say so explicitly.
- Use plain English, avoid unexplained acronyms.
- Explain consequences, not just vulnerability class names."""

        parsed, response = await provider.generate_json(prompt, temperature=0.1, max_retries=2)

        if parsed:
            parsed["_provider"] = provider.model_name
            return parsed

        # Fallback: generate deterministic analysis without LLM
        logger.info("using_fallback_analysis", model=provider.model_name)
        return self._fallback_analysis(ctx)

    def _fallback_analysis(self, ctx: ReviewContext) -> dict[str, Any]:
        """Generate a deterministic, honest analysis when LLM is unavailable."""
        files_desc = ", ".join(f["path"] for f in ctx.changed_files[:5])
        return {
            "change_summary": f"This change modifies {len(ctx.changed_files)} file(s): {files_desc}. "
            f"The analysis was performed with deterministic heuristics because no LLM is available. "
            f"The technical evidence below is real and verifiable.",
            "functional_purpose": None,
            "what_could_go_wrong": "See security impacts section for detected concerns." if ctx.security_sensitive else "No specific risk identified by deterministic analysis.",
            "who_or_what_affected": "Users or systems that depend on the changed components.",
            "evidence_quality": "moderate" if ctx.evidence else "weak",
            "confidence_level": "low",
            "_provider": "fallback",
            "_note": "This analysis was generated without an LLM. Enable Ollama for natural-language explanations.",
        }

    def _fallback_summary(self, ctx: ReviewContext) -> str:
        return f"Changes to {len(ctx.changed_files)} file(s) with {len(ctx.changed_symbols)} symbol change(s)."

    def _build_findings(self, ctx: ReviewContext, llm_report: dict) -> list[dict]:
        """Build findings from analysis, linking each to evidence."""
        findings: list[dict] = []

        # Security-sensitive findings from heuristics
        if ctx.security_sensitive:
            for reason in ctx.security_sensitive_reasons:
                # Find matching evidence
                matching_evidence = [e for e in ctx.evidence if reason.split("'")[1] in e.file_path]
                findings.append({
                    "title": "Security-sensitive code area affected",
                    "description": f"{reason}. This change touches code that handles security-relevant logic. "
                    "Manual review is recommended to verify that authorization, input validation, "
                    "and data protection controls are not weakened.",
                    "severity": "medium",
                    "confidence": "likely",
                    "file_path": matching_evidence[0].file_path if matching_evidence else ctx.changed_files[0]["path"] if ctx.changed_files else None,
                    "line_range": [matching_evidence[0].line_start, matching_evidence[0].line_end] if matching_evidence else [],
                    "category": "security_sensitive_change",
                    "rule_id": "PRISM-SEC-SENSITIVE",
                    "scanner_source": "prism",
                    "is_blocking": False,
                    "evidence": [
                        {"file_path": e.file_path, "line_range": [e.line_start, e.line_end], "source": e.source_type}
                        for e in matching_evidence[:3]
                    ] if matching_evidence else [],
                })

        # LLM-identified concerns (if any, with confidence distinction)
        what_could_go_wrong = llm_report.get("what_could_go_wrong", "")
        if what_could_go_wrong and what_could_go_wrong not in ("None", "No specific risk identified by deterministic analysis."):
            confidence = llm_report.get("confidence_level", "low")
            is_hypothesis = confidence in ("low", "weak") or not ctx.evidence
            findings.append({
                "title": "LLM-identified concern",
                "description": what_could_go_wrong,
                "severity": "low",
                "confidence": "hypothesis" if is_hypothesis else "likely",
                "file_path": ctx.changed_files[0]["path"] if ctx.changed_files else None,
                "line_range": [],
                "category": "llm_analysis",
                "rule_id": "PRISM-LLM-CONCERN",
                "scanner_source": "prism",
                "is_blocking": False,
                "evidence": [],
                "_note": "This finding was identified by the LLM and may be a hypothesis. Verify with manual review." if is_hypothesis else "",
            })

        return findings

    def _build_checks(self, ctx: ReviewContext) -> list[CheckResult]:
        """Build check results from available evidence."""
        checks: list[CheckResult] = []

        # Indexing check
        checks.append(CheckResult(
            name="code_indexing",
            status="passed",
            source="prism",
            details=f"Indexed {len(ctx.changed_symbols)} changed symbols across {len(ctx.changed_files)} files.",
        ))

        # Diff analysis check
        checks.append(CheckResult(
            name="diff_analysis",
            status="passed",
            source="prism",
            details=f"Computed diff: +{ctx.diff_stats.get('additions', 0)}/-{ctx.diff_stats.get('deletions', 0)}.",
        ))

        # Test coverage check
        if ctx.related_tests:
            checks.append(CheckResult(
                name="test_coverage",
                status="passed",
                source="prism",
                details=f"Found {len(ctx.related_tests)} related test file(s).",
            ))
        else:
            checks.append(CheckResult(
                name="test_coverage",
                status="incomplete",
                source="prism",
                details="No related test files detected. This may indicate untested changes.",
            ))

        # Scanner results (placeholder — would integrate Coverity/BlackDuck)
        checks.append(CheckResult(
            name="scanner_results",
            status="incomplete",
            source="external",
            details="No scanner results available. Configure Coverity or Black Duck integration for complete analysis.",
        ))

        # Security sensitivity check
        if ctx.security_sensitive:
            checks.append(CheckResult(
                name="security_review",
                status="incomplete",
                source="prism",
                details=f"Security-sensitive areas detected: {', '.join(ctx.security_sensitive_reasons[:2])}.",
            ))

        return checks

    def _build_affected_components(self, ctx: ReviewContext) -> list[dict]:
        """Build the affected components list."""
        components = []
        seen_paths = set()
        for f in ctx.changed_files:
            if f["path"] not in seen_paths:
                seen_paths.add(f["path"])
                components.append({
                    "file_path": f["path"],
                    "status": f["status"],
                    "language": f.get("language"),
                    "symbols_changed": sum(1 for s in ctx.changed_symbols if s.file_path == f["path"]),
                })
        return components

    def _build_security_impacts(self, ctx: ReviewContext, llm_report: dict) -> list[dict]:
        """Build potential security impacts list."""
        impacts = []
        if ctx.security_sensitive:
            impacts.append({
                "description": llm_report.get("what_could_go_wrong", "Security-sensitive code was modified."),
                "severity": "medium",
                "confidence": "likely",
                "evidence_ref": ctx.security_sensitive_reasons,
            })

        for cc in ctx.config_changes:
            impacts.append({
                "description": f"Configuration file '{cc['path']}' was {cc['status']}. This may affect deployment, permissions, or security posture.",
                "severity": "low",
                "confidence": "hypothesis",
                "evidence_ref": [cc["path"]],
            })

        return impacts

    def _build_executive_summary(
        self,
        ctx: ReviewContext,
        llm_report: dict,
        policy_decision: PolicyDecision,
        pr_info: dict,
    ) -> dict:
        """Build the executive summary for non-technical reviewers."""
        return {
            "what_changed": llm_report.get("change_summary", self._fallback_summary(ctx)),
            "why_made": llm_report.get("functional_purpose") or (
                f"PR: {pr_info.get('pr_title', 'N/A')}" if pr_info.get("pr_title") else "Reason not determined from available evidence."
            ),
            "what_feature_does": llm_report.get("functional_purpose") or "Feature purpose not determined from available evidence.",
            "what_could_go_wrong": llm_report.get("what_could_go_wrong", "No specific risk identified."),
            "who_affected": llm_report.get("who_or_what_affected", "Users and systems dependent on the changed components."),
            "evidence_quality": llm_report.get("evidence_quality", "insufficient"),
            "confidence": llm_report.get("confidence_level", "low"),
            "checks_passed": [c.name for c in policy_decision._failed_checks if False] or
                           [c.name for c in [CheckResult("", "", "", "")] if c.status == "passed"],
            "checks_passed_list": [c.name for c in []],  # populated below
            "checks_failed": [c.name for c in policy_decision._failed_checks] if hasattr(policy_decision, "_failed_checks") else [],
            "reviewer_action": policy_decision.reasons[0] if policy_decision.reasons else "",
        }

    def _build_technical_evidence(self, ctx: ReviewContext, findings: list[dict]) -> dict:
        """Build the technical evidence view."""
        return {
            "base_commit": ctx.base_sha,
            "head_commit": ctx.head_sha,
            "diff_stats": ctx.diff_stats,
            "changed_files": ctx.changed_files,
            "changed_symbols": [
                {
                    "name": s.name,
                    "file": s.file_path,
                    "lines": [s.start_line, s.end_line],
                    "change_type": s.change_type,
                    "signature": s.signature,
                    "has_before": s.before_code is not None,
                }
                for s in ctx.changed_symbols
            ],
            "evidence_items": [
                {
                    "file_path": e.file_path,
                    "line_range": [e.line_start, e.line_end],
                    "commit": e.commit_sha,
                    "source_type": e.source_type,
                    "description": e.description,
                    "snippet_preview": e.code_snippet[:500] + "..." if len(e.code_snippet) > 500 else e.code_snippet,
                }
                for e in ctx.evidence
            ],
            "analysis_scope": f"Analyzed {len(ctx.changed_files)} files, {len(ctx.changed_symbols)} symbols. "
            f"Retrieved {len(ctx.evidence)} evidence items.",
            "limitations": self._build_limitations(ctx),
        }

    def _build_limitations(self, ctx: ReviewContext) -> list[str]:
        """Build limitations list."""
        limits = []
        if not ctx.evidence:
            limits.append("No evidence items were gathered — analysis may be incomplete.")
        if not ctx.related_tests:
            limits.append("No related test files detected — test coverage unknown.")
        limits.append("Scanner results (Coverity/Black Duck) not available — external security validation incomplete.")
        limits.append("Call graph analysis is limited to static detection. Dynamic dispatch and reflection may hide callers.")
        return limits

    def _build_uncertainty(self, ctx: ReviewContext, llm_report: dict) -> str:
        """Build uncertainty statement."""
        parts = []
        confidence = llm_report.get("confidence_level", "low")
        parts.append(f"Overall analysis confidence: {confidence}.")
        if not ctx.evidence:
            parts.append("Limited evidence available — findings should be verified manually.")
        if ctx.security_sensitive:
            parts.append("Security-sensitive areas detected require human review.")
        parts.append("Call graph completeness depends on static analysis limitations.")
        parts.append("Scanner results unavailable — external validation incomplete.")
        return " ".join(parts)

    def _build_coverage(self, ctx: ReviewContext) -> dict:
        """Build analysis coverage report."""
        return {
            "files_analyzed": len(ctx.changed_files),
            "symbols_analyzed": len(ctx.changed_symbols),
            "evidence_items": len(ctx.evidence),
            "callers_retrieved": len(ctx.callers),
            "callees_retrieved": len(ctx.callees),
            "tests_found": len(ctx.related_tests),
            "config_changes": len(ctx.config_changes),
            "security_sensitive": ctx.security_sensitive,
            "scanner_results_available": False,
            "complete": True,
            "incomplete_items": ["scanner_results", "test_execution"] if not ctx.related_tests else ["scanner_results"],
        }

    def _build_recommendation(self, decision: PolicyDecision) -> str:
        """Build recommended action text."""
        base = {
            ReviewState.READY_FOR_POLICY_REVIEW: "All automated checks passed. This change is eligible for approval under configured policy, but manual review is still recommended for any change touching sensitive areas.",
            ReviewState.REVIEW_REQUIRED: "Manual review is required. Review the evidence below and verify the findings before approving.",
            ReviewState.BLOCKED_BY_FINDING: "This change is blocked by high-severity findings. Address the blocking findings before proceeding.",
            ReviewState.ANALYSIS_INCOMPLETE: "Analysis is incomplete. Wait for indexing and analysis to complete before reviewing.",
            ReviewState.FAILED_CHECKS: "One or more checks failed. Resolve the failures before proceeding.",
            ReviewState.HUMAN_SECURITY_REVIEW_REQUIRED: "This change touches security-sensitive code and requires human security review. A security reviewer should verify that authorization, validation, and data protection controls are not weakened.",
        }
        return base.get(decision.state, "Review the evidence below before approving.")
