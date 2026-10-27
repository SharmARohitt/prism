"""Commit explanation API routes.

Generates plain-English explanations of what changed in each commit using
the LLM. Explanations are cached on the Commit record after the first run.

The explanation works in three tiers:
  1. Cached result already stored — return immediately.
  2. Real diff available — send actual changed files + snippets to Ollama.
  3. No diff (no parent SHA or mirror unavailable) — use commit message +
     file list from the stored Commit record to produce a useful fallback.

The "LLM explanation unavailable" message is only shown when Ollama itself
is offline. If Ollama is running but returns empty text, we produce a
structured deterministic explanation instead of the raw error string.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from prism.core.git_mirror import GitMirror
from prism.database import get_db
from prism.logging_config import get_logger
from prism.llm.provider import get_available_provider
from prism.models import Commit, Repository

logger = get_logger("prism.api.commits")
router = APIRouter(prefix="/api/repositories", tags=["commits"])


@router.get("/{repo_id}/commits/{commit_sha}/explain")
async def explain_commit(
    repo_id: str,
    commit_sha: str,
    db: AsyncSession = Depends(get_db),
):
    """Return a plain-English explanation of what changed in a commit."""

    # ── Resolve repository ──────────────────────────────────
    repo_result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = repo_result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # ── Resolve commit ──────────────────────────────────────
    commit_result = await db.execute(
        select(Commit).where(
            Commit.repository_id == repo_id,
            Commit.sha == commit_sha,
        )
    )
    commit = commit_result.scalar_one_or_none()
    if not commit:
        raise HTTPException(status_code=404, detail="Commit not found in index.")

    # ── Return cache ────────────────────────────────────────
    if getattr(commit, "explanation", None):
        return {
            "sha": commit_sha,
            "explanation": commit.explanation,
            "cached": True,
            "model": getattr(commit, "explanation_model", None),
        }

    # ── Build diff context ──────────────────────────────────
    diff_context = await _gather_diff_context(repo_id, repo.url, commit, commit_sha)

    # ── Build and send LLM prompt ───────────────────────────
    provider = await get_available_provider()
    explanation = await _generate_explanation(commit, diff_context, provider)

    # ── Cache result ────────────────────────────────────────
    try:
        commit.explanation = explanation
        commit.explanation_model = provider.model_name
        await db.commit()
    except Exception:
        pass  # Column may not exist on older DB schema — safe to ignore

    return {
        "sha": commit_sha,
        "explanation": explanation,
        "cached": False,
        "model": provider.model_name,
    }


# ── Helpers ─────────────────────────────────────────────────


async def _gather_diff_context(
    repo_id: str,
    repo_url: str,
    commit: Commit,
    commit_sha: str,
) -> dict[str, Any]:
    """
    Gather the richest diff context available.
    Falls back gracefully when the mirror is unavailable or parent SHA is missing.
    """
    ctx: dict[str, Any] = {
        "files_desc": "",
        "snippets": "",
        "additions": commit.stats_additions or 0,
        "deletions": commit.stats_deletions or 0,
        "file_count": len(commit.files_changed) if commit.files_changed else 0,
        "files_list": commit.files_changed or [],
        "has_diff": False,
    }

    # If we already have a file list from ingestion, use it immediately
    if commit.files_changed:
        ctx["files_desc"] = "\n".join(
            f"- {f}" for f in commit.files_changed[:25]
        )
        ctx["file_count"] = len(commit.files_changed)

    try:
        mirror = GitMirror(repo_id, repo_url)
        if not mirror.exists:
            return ctx

        parent_sha = (commit.parent_shas or [])[0] if commit.parent_shas else None
        if not parent_sha:
            # No parent — try to get file content for a few files from the commit
            if commit.files_changed:
                snippets = []
                for fpath in commit.files_changed[:4]:
                    content = await mirror.get_file_content(fpath, commit_sha)
                    if content:
                        lines = content.split("\n")[:6]
                        snippets.append(f"--- {fpath} ---\n" + "\n".join(lines))
                ctx["snippets"] = "\n".join(snippets)
            return ctx

        # Full diff available
        diff = await mirror.get_diff(parent_sha, commit_sha)
        ctx["has_diff"] = True
        ctx["additions"] = diff.stats.get("additions", ctx["additions"])
        ctx["deletions"] = diff.stats.get("deletions", ctx["deletions"])
        ctx["file_count"] = len(diff.changed_files)
        ctx["files_desc"] = "\n".join(
            f"- {f.path} ({f.status}, +{f.additions}/-{f.deletions})"
            for f in diff.changed_files[:25]
        )

        # Fetch content snippets for security-sensitive or most-changed files
        interesting = sorted(diff.changed_files, key=lambda f: f.additions + f.deletions, reverse=True)
        snippets = []
        for f in interesting[:4]:
            try:
                content = await mirror.get_file_content(f.path, commit_sha)
                if content:
                    lines = content.split("\n")[:10]
                    snippets.append(f"--- {f.path} ---\n" + "\n".join(lines))
            except Exception:
                pass
        ctx["snippets"] = "\n".join(snippets)

    except Exception as e:
        logger.debug("diff_context_error", sha=commit_sha[:12], error=str(e))

    return ctx


async def _generate_explanation(
    commit: Commit,
    ctx: dict[str, Any],
    provider: Any,
) -> str:
    """Send the enriched context to the LLM and return a clean explanation string."""

    message_first_line = commit.message.split("\n")[0][:150].strip()
    is_merge = len(commit.parent_shas or []) >= 2 or message_first_line.lower().startswith("merge")

    # Build a highly targeted, concrete prompt
    prompt = f"""You are a code change explainer for security reviewers who are NOT technical.

COMMIT TITLE: {message_first_line}
AUTHOR: {commit.author_name}
TYPE: {"merge commit" if is_merge else "regular commit"}
CHANGES: +{ctx["additions"]} lines added, -{ctx["deletions"]} lines removed across {ctx["file_count"]} file(s)

CHANGED FILES:
{ctx["files_desc"] or "(file list not available — use the commit title to guide your explanation)"}

CODE PREVIEW:
{ctx["snippets"] or "(no preview available)"}

TASK: Write exactly 2-3 sentences. Be specific and concrete:
- Sentence 1: What was changed (name the actual feature, module, or files)
- Sentence 2: Why this change likely happened or what it improves
- Sentence 3 (optional): Any security or risk note if relevant

STRICT RULES:
- Never use the word "modifies code" — name what was actually changed
- No bullet points, no headers, no markdown
- Plain English only — avoid jargon
- 40-60 words maximum
- If it is a merge commit, say "merges [branch/feature] changes into the main branch"
- If it is a test file change, say "updates tests for X"
- If it touches auth, credentials, or security logic, note it explicitly"""

    try:
        response = await provider.generate(prompt, temperature=0.15)
    except Exception as e:
        return _deterministic_fallback(commit, ctx)

    text = (response.text or "").strip()

    # Detect stub/empty/bad responses and fall back deterministically
    if (
        not response.success
        or not text
        or text in ("{}", "null", "None", "{}\n", "")
        or len(text) < 20
        or text.startswith("{")
    ):
        return _deterministic_fallback(commit, ctx)

    # Strip any accidental markdown the model added
    text = text.strip("`").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(l for l in lines if not l.strip().startswith("```")).strip()

    return text


def _deterministic_fallback(commit: Commit, ctx: dict[str, Any]) -> str:
    """
    Produce a useful, honest explanation purely from structured data.
    Never returns "LLM explanation unavailable" — always provides real information.
    """
    headline = commit.message.split("\n")[0][:150].strip()
    author = commit.author_name or "unknown"
    add = ctx.get("additions", commit.stats_additions or 0)
    dele = ctx.get("deletions", commit.stats_deletions or 0)
    files = ctx.get("files_list", commit.files_changed or [])
    count = ctx.get("file_count", len(files))

    # Categorise the change from the file list and commit message
    langs = _detect_languages(files)
    category = _categorise(headline, files)

    # Build descriptive file summary
    if count == 0:
        file_summary = "with no recorded file changes"
    elif count == 1:
        file_summary = f"to {files[0]}"
    elif count <= 4:
        short_names = [f.split("/")[-1] for f in files[:4]]
        file_summary = f"across {', '.join(short_names)}"
    else:
        top = [f.split("/")[-1] for f in files[:2]]
        file_summary = f"across {count} files including {', '.join(top)}"

    lang_note = f" ({', '.join(sorted(langs)[:3])})" if langs else ""

    parts = [
        f'This commit — "{headline}" — makes {category} changes{lang_note} {file_summary}.',
    ]

    if add or dele:
        parts.append(f"It adds {add} and removes {dele} lines of code.")

    if any(kw in headline.lower() for kw in ("auth", "password", "secret", "token", "credential", "security", "permission")):
        parts.append("This change touches security-relevant code and should be reviewed carefully.")
    elif count > 0:
        parts.append(
            "Review the changed files to confirm the intent matches the commit description."
        )

    return " ".join(parts)


def _detect_languages(files: list[str]) -> set[str]:
    ext_map = {
        ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript",
        ".js": "JavaScript", ".jsx": "JavaScript", ".java": "Java",
        ".go": "Go", ".rs": "Rust", ".kt": "Kotlin",
        ".swift": "Swift", ".rb": "Ruby", ".cs": "C#",
    }
    langs: set[str] = set()
    for f in files:
        ext = "." + f.rsplit(".", 1)[-1].lower() if "." in f else ""
        lang = ext_map.get(ext)
        if lang:
            langs.add(lang)
    return langs


def _categorise(headline: str, files: list[str]) -> str:
    h = headline.lower()
    paths = " ".join(files).lower()
    if any(w in h for w in ("test", "spec", "mock")):
        return "test"
    if any(w in h for w in ("fix", "bug", "patch", "hotfix")):
        return "bug-fix"
    if any(w in h for w in ("feat", "add", "new", "implement")):
        return "feature"
    if any(w in h for w in ("refactor", "clean", "migrate", "move", "rename")):
        return "refactoring"
    if any(w in h for w in ("ci", "workflow", "github action", "deploy", "build")):
        return "CI/CD"
    if any(w in h for w in ("doc", "readme", "comment", "changelog")):
        return "documentation"
    if any(w in h for w in ("dep", "package", "gradle", "maven", "npm", "upgrade")):
        return "dependency"
    if any(w in h for w in ("config", "setting", ".env", "yaml", "toml")):
        return "configuration"
    if any(w in paths for w in ("test", "spec")):
        return "test"
    return "source code"
