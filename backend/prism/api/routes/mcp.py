"""MCP tools API routes.

Exposes the MCP tool registry and allows tool execution through the API.
All tools are read-only and enforce repository/commit scope.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from prism.logging_config import get_logger
from prism.mcp.tools import ToolContext, execute_tool, list_tool_contracts
from prism.schemas import McpToolRequest, McpToolResponse

logger = get_logger("prism.api.mcp")
router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/tools")
async def list_tools():
    """List all available MCP tools and their contracts."""
    return {"tools": list_tool_contracts()}


@router.post("/tools/execute", response_model=McpToolResponse)
async def execute_mcp_tool(req: McpToolRequest):
    """Execute a specific MCP tool.

    The repository_id and commit_sha in the arguments define the authorized scope.
    Tools enforce this scope independently of the model's requests.
    """
    args = req.arguments
    repository_id = args.get("repository_id", "")
    commit_sha = args.get("commit_sha", "HEAD")
    branch = args.get("branch")

    if not repository_id:
        raise HTTPException(status_code=400, detail="repository_id is required in arguments.")

    # Get the Git mirror for this repository
    from prism.core.git_mirror import GitMirror
    from prism.config import get_settings
    mirror = GitMirror(repository_id, "", get_settings().git_mirror_path / repository_id)

    if not mirror.exists:
        raise HTTPException(status_code=404, detail="Repository mirror not found. Ensure ingestion has completed.")

    # Create the authorized tool context
    ctx = ToolContext(
        mirror=mirror,
        repository_id=repository_id,
        commit_sha=commit_sha,
        allowed_branch=branch,
    )

    try:
        result = await execute_tool(req.tool_name, ctx, args)
        return McpToolResponse(
            tool_name=req.tool_name,
            success=True,
            result=result,
        )
    except PermissionError as e:
        return McpToolResponse(
            tool_name=req.tool_name,
            success=False,
            error=f"Permission denied: {e}",
        )
    except ValueError as e:
        return McpToolResponse(
            tool_name=req.tool_name,
            success=False,
            error=str(e),
        )
    except Exception as e:
        logger.error("mcp_tool_error", tool=req.tool_name, error=str(e))
        return McpToolResponse(
            tool_name=req.tool_name,
            success=False,
            error=f"Tool execution failed: {e}",
        )
