"""MCP (Model Context Protocol) tool layer.

Exposes read-only, permission-aware repository intelligence tools.
The LLM uses these to request specific context rather than receiving
the entire repository. All tools enforce repository-level authorization
and branch/commit scope.

These are PRISM tool contracts, not assumed third-party APIs.
"""

from __future__ import annotations

from typing import Any, Protocol

from prism.core.git_mirror import GitMirror, detect_language
from prism.core.indexer import CodeIndexer, _is_security_sensitive
from prism.logging_config import get_logger
from prism.models import RelationType

logger = get_logger("prism.mcp")


class ToolContext:
    """Holds the authorized context for tool execution.

    Enforces that the LLM can only access the repository, branch, and commit
    it was authorized for — independent of model requests.
    """

    def __init__(
        self,
        mirror: GitMirror,
        repository_id: str,
        commit_sha: str,
        allowed_branch: str | None = None,
    ):
        self.mirror = mirror
        self.repository_id = repository_id
        self.commit_sha = commit_sha
        self.allowed_branch = allowed_branch

    def validate_commit(self, commit_sha: str | None) -> str:
        """Ensure the requested commit matches the authorized scope."""
        if commit_sha and commit_sha != self.commit_sha:
            raise PermissionError(
                f"Tool access restricted to commit {self.commit_sha}. "
                f"Requested commit {commit_sha} is outside the authorized scope."
            )
        return commit_sha or self.commit_sha


class McpTool(Protocol):
    """Protocol for MCP tools."""
    name: str
    description: str

    async def execute(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]: ...


# ── Tool implementations ────────────────────────────────────


class GetRepositoryOverviewTool:
    name = "get_repository_overview"
    description = "Get a high-level overview of the repository: languages, file count, structure."

    async def execute(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        structure = await ctx.mirror.analyze_structure(ctx.commit_sha)
        return {
            "commit_sha": structure.commit_sha,
            "file_count": len(structure.file_paths),
            "languages": structure.languages,
            "build_files": structure.build_files,
            "test_files": structure.test_files,
            "doc_files": structure.doc_files,
            "ci_files": structure.ci_files,
        }


class GetRepositoryStatusTool:
    name = "get_repository_status"
    description = "Get the current status of the repository mirror and indexing."

    async def execute(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        head_sha = await ctx.mirror.get_head_sha(ctx.allowed_branch)
        return {
            "repository_id": ctx.repository_id,
            "commit_sha": head_sha,
            "mirror_exists": ctx.mirror.exists,
            "branch": ctx.allowed_branch,
        }


class GetCommitDiffTool:
    name = "get_commit_diff"
    description = "Get the diff between two commits (base and head). Returns changed files with stats."

    async def execute(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        base_sha = arguments.get("base_sha", "")
        head_sha = ctx.validate_commit(arguments.get("head_sha"))
        if not base_sha:
            raise ValueError("base_sha is required")
        diff = await ctx.mirror.get_diff(base_sha, head_sha)
        return {
            "base_sha": diff.base_sha,
            "head_sha": diff.head_sha,
            "changed_files": [
                {
                    "path": f.path,
                    "status": f.status,
                    "additions": f.additions,
                    "deletions": f.deletions,
                }
                for f in diff.changed_files
            ],
            "stats": diff.stats,
        }


class GetChangedSymbolsTool:
    name = "get_changed_symbols"
    description = "Get symbols that changed between two commits."

    async def execute(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        base_sha = arguments.get("base_sha", "")
        head_sha = ctx.validate_commit(arguments.get("head_sha"))
        if not base_sha:
            raise ValueError("base_sha is required")

        diff = await ctx.mirror.get_diff(base_sha, head_sha)
        changed_symbols = []

        for cf in diff.changed_files:
            if cf.status in ("added", "modified"):
                content = await ctx.mirror.get_file_content(cf.path, head_sha)
                if content:
                    indexed = await CodeIndexer().index_file(cf.path, content, ctx.mirror)
                    for sym in indexed.symbols:
                        changed_symbols.append({
                            "name": sym.name,
                            "type": sym.symbol_type.value,
                            "file": sym.file_path,
                            "lines": [sym.start_line, sym.end_line],
                            "signature": sym.signature,
                        })

        return {
            "base_sha": base_sha,
            "head_sha": head_sha,
            "changed_symbols": changed_symbols,
            "count": len(changed_symbols),
        }


class GetSymbolDefinitionTool:
    name = "get_symbol_definition"
    description = "Get the definition (source code) of a specific symbol at a commit."

    async def execute(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        file_path = arguments.get("file_path", "")
        symbol_name = arguments.get("symbol_name", "")
        commit_sha = ctx.validate_commit(arguments.get("commit_sha"))

        if not file_path or not symbol_name:
            raise ValueError("file_path and symbol_name are required")

        content = await ctx.mirror.get_file_content(file_path, commit_sha)
        if not content:
            return {"found": False, "error": "File not found at this commit."}

        indexed = await CodeIndexer().index_file(file_path, content, ctx.mirror)
        for sym in indexed.symbols:
            if sym.name == symbol_name:
                lines = content.split("\n")
                definition = "\n".join(lines[max(0, sym.start_line - 1):sym.end_line])
                return {
                    "found": True,
                    "name": sym.name,
                    "type": sym.symbol_type.value,
                    "file": file_path,
                    "lines": [sym.start_line, sym.end_line],
                    "signature": sym.signature,
                    "definition": definition,
                    "docstring": sym.docstring,
                    "is_security_sensitive": _is_security_sensitive(sym.name, sym.signature),
                }
        return {"found": False, "error": f"Symbol '{symbol_name}' not found in {file_path}."}


class GetCallersAndCalleesTool:
    name = "get_callers_and_callees"
    description = "Get callers and callees of a symbol. Returns relationships with certainty labels."

    async def execute(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        file_path = arguments.get("file_path", "")
        symbol_name = arguments.get("symbol_name", "")
        commit_sha = ctx.validate_commit(arguments.get("commit_sha"))

        content = await ctx.mirror.get_file_content(file_path, commit_sha)
        if not content:
            return {"callers": [], "callees": [], "note": "File not found."}

        indexed = await CodeIndexer().index_file(file_path, content, ctx.mirror)

        callees = []
        for sym in indexed.symbols:
            if sym.name == symbol_name:
                for rel in indexed.relationships:
                    if rel.source_symbol == symbol_name and rel.relation_type == RelationType.CALLS:
                        callees.append({
                            "target": rel.target_symbol,
                            "line": rel.line_number,
                            "certainty": rel.certainty.value,
                        })

        return {
            "symbol": symbol_name,
            "file": file_path,
            "callers": [],  # Would require cross-file index lookup
            "callees": callees,
            "note": "Callers require a cross-file index. This is a known limitation in the current version.",
        }


class GetDependencyPathTool:
    name = "get_dependency_path"
    description = "Get the dependency/import path for a file."

    async def execute(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        file_path = arguments.get("file_path", "")
        commit_sha = ctx.validate_commit(arguments.get("commit_sha"))

        content = await ctx.mirror.get_file_content(file_path, commit_sha)
        if not content:
            return {"imports": [], "note": "File not found."}

        indexed = await CodeIndexer().index_file(file_path, content, ctx.mirror)
        imports = []
        for rel in indexed.relationships:
            if rel.relation_type == RelationType.IMPORTS:
                imports.append({
                    "target": rel.target_symbol,
                    "line": rel.line_number,
                    "certainty": rel.certainty.value,
                })

        return {"file": file_path, "imports": imports}
        # No dependency_path key to match expected format


class GetRelatedTestsTool:
    name = "get_related_tests"
    description = "Find test files related to a given source file."

    async def execute(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        source_file = arguments.get("file_path", "")
        commit_sha = ctx.validate_commit(arguments.get("commit_sha"))

        structure = await ctx.mirror.analyze_structure(commit_sha)
        base_name = source_file.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        related = []
        for test_file in structure.test_files:
            if base_name in test_file or test_file.replace("test_", "").replace("_test", "") == base_name:
                related.append(test_file)

        return {
            "source_file": source_file,
            "related_tests": related,
            "count": len(related),
            "note": "Test detection is heuristic. Some tests may not be detected." if not related else "",
        }


class GetExistingSecurityFindingsTool:
    name = "get_existing_security_findings"
    description = "Get existing security findings from PRISM or integrated scanners for a commit."

    async def execute(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        commit_sha = ctx.validate_commit(arguments.get("commit_sha"))
        return {
            "commit_sha": commit_sha,
            "findings": [],
            "scanners_configured": [],
            "note": "No scanner findings available. Configure Coverity or Black Duck integration to populate this data.",
        }


class GetAnalysisCoverageTool:
    name = "get_analysis_coverage"
    description = "Get the analysis coverage report for a review — what was checked and what remains."

    async def execute(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "files_analyzed": arguments.get("files_count", 0),
            "symbols_analyzed": arguments.get("symbols_count", 0),
            "scanners_run": False,
            "tests_found": arguments.get("tests_count", 0),
            "complete": False,
            "incomplete_items": ["scanner_results"],
            "note": "Coverage depends on the review run. This is a placeholder.",
        }


class GetEvidenceForFindingTool:
    name = "get_evidence_for_finding"
    description = "Get the evidence supporting a specific finding — code snippets, line ranges, commit refs."

    async def execute(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
        file_path = arguments.get("file_path", "")
        line_start = arguments.get("line_start", 1)
        line_end = arguments.get("line_end", line_start)
        commit_sha = ctx.validate_commit(arguments.get("commit_sha"))

        if not file_path:
            return {"evidence": [], "note": "file_path required"}

        content = await ctx.mirror.get_file_content(file_path, commit_sha)
        if not content:
            return {"evidence": [], "note": "File not found at this commit."}

        lines = content.split("\n")
        snippet = "\n".join(lines[max(0, line_start - 1):line_end])

        return {
            "evidence": [
                {
                    "file_path": file_path,
                    "line_range": [line_start, line_end],
                    "commit_sha": commit_sha,
                    "code_snippet": snippet,
                    "source_type": "source",
                }
            ],
            "note": "Evidence retrieved from source code at the specified commit.",
        }


# ── Tool registry ───────────────────────────────────────────


def get_tool_registry() -> dict[str, McpTool]:
    """Return the registry of available MCP tools."""
    tools = [
        GetRepositoryOverviewTool(),
        GetRepositoryStatusTool(),
        GetCommitDiffTool(),
        GetChangedSymbolsTool(),
        GetSymbolDefinitionTool(),
        GetCallersAndCalleesTool(),
        GetDependencyPathTool(),
        GetRelatedTestsTool(),
        GetExistingSecurityFindingsTool(),
        GetAnalysisCoverageTool(),
        GetEvidenceForFindingTool(),
    ]
    return {t.name: t for t in tools}


def list_tool_contracts() -> list[dict[str, Any]]:
    """List all tool contracts for documentation/API exposure."""
    registry = get_tool_registry()
    return [
        {
            "name": name,
            "description": tool.description,
        }
        for name, tool in registry.items()
    ]


async def execute_tool(
    tool_name: str,
    ctx: ToolContext,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Execute a named MCP tool with the given context and arguments."""
    registry = get_tool_registry()
    if tool_name not in registry:
        raise ValueError(f"Unknown tool: {tool_name}. Available: {list(registry.keys())}")

    tool = registry[tool_name]
    logger.info("executing_mcp_tool", tool=tool_name, repo=ctx.repository_id)
    return await tool.execute(ctx, arguments)
