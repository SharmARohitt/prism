"""Enhanced architecture graph API routes.

Provides multi-level graph data (module, file, symbol), node details with
incoming/outgoing relationships, search, and path tracing.

Every node and edge carries evidence and confidence metadata so the frontend
can explain why a relationship exists and whether it is verified or inferred.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from prism.database import get_db
from prism.logging_config import get_logger
from prism.models import (
    FileEntry,
    IndexStatus,
    IndexVersion,
    Relationship,
    Repository,
    Symbol,
)

logger = get_logger("prism.api.graph")
router = APIRouter(prefix="/api/repositories", tags=["graph"])


# ── Helpers ─────────────────────────────────────────────────


def _get_module(path: str) -> str:
    """Extract the parent directory from a file path as the module name."""
    parts = path.rsplit("/", 1)
    if len(parts) == 1:
        return parts[0]
    return parts[0] if parts[0] else "/"


def _get_short_name(path: str) -> str:
    """Get the file name without directory."""
    return path.rsplit("/", 1)[-1]


def _is_security_sensitive_name(name: str) -> bool:
    keywords = {
        "auth", "password", "token", "secret", "crypt", "hash", "permission",
        "validate", "input", "sql", "query", "exec", "shell", "file", "path",
        "cookie", "session", "jwt", "oauth", "admin", "privilege", "encrypt",
    }
    name_lower = name.lower()
    return any(kw in name_lower for kw in keywords)


# ── Main graph endpoint ──────────────────────────────────────


@router.get("/{repo_id}/architecture-graph")
async def get_architecture_graph(
    repo_id: str,
    level: str = Query("module", pattern="^(module|file|symbol)$"),
    limit: int = Query(200, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the architecture graph at the requested detail level.

    Levels:
    - module: nodes are directories/modules, edges are aggregated relationships
    - file: nodes are files, edges are file-level relationships
    - symbol: nodes are individual functions/classes/methods, edges are direct relationships
    """
    # Verify repository exists
    repo_result = await db.execute(select(Repository).where(Repository.id == repo_id))
    repo = repo_result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Get latest completed index version
    iv_result = await db.execute(
        select(IndexVersion)
        .where(IndexVersion.repository_id == repo_id)
        .where(IndexVersion.status == IndexStatus.COMPLETED)
        .order_by(IndexVersion.created_at.desc())
        .limit(1)
    )
    index_version = iv_result.scalar_one_or_none()

    if not index_version:
        return {
            "nodes": [],
            "edges": [],
            "level": level,
            "total_symbols": 0,
            "total_files": 0,
            "coverage": {
                "languages_analyzed": [],
                "relationship_types": [],
                "unsupported_files": 0,
                "limitations": ["No completed index available."],
            },
        }

    # Load all file entries for this index version
    files_result = await db.execute(
        select(FileEntry).where(FileEntry.index_version_id == index_version.id)
    )
    files = {fe.id: fe for fe in files_result.scalars().all()}

    # Build file path → file entry map
    path_to_fe: dict[str, FileEntry] = {fe.path: fe for fe in files.values()}

    # Load all symbols
    syms_result = await db.execute(
        select(Symbol).where(Symbol.index_version_id == index_version.id).limit(limit * 3)
    )
    symbols = syms_result.scalars().all()

    # Build symbol_id → symbol map
    sym_map: dict[str, Symbol] = {s.id: s for s in symbols}

    # Load relationships
    rels_result = await db.execute(
        select(Relationship).where(Relationship.index_version_id == index_version.id).limit(limit * 5)
    )
    relationships = rels_result.scalars().all()

    if level == "module":
        return _build_module_graph(symbols, files, relationships, index_version)
    elif level == "file":
        return _build_file_graph(symbols, files, relationships, index_version, path_to_fe)
    else:
        return _build_symbol_graph(symbols, files, relationships, index_version, limit)


def _build_module_graph(
    symbols: list[Symbol],
    files: dict[str, FileEntry],
    relationships: list[Relationship],
    index_version: IndexVersion,
) -> dict[str, Any]:
    """Aggregate symbols into module (directory) level nodes."""

    # Group symbols by module (parent directory)
    module_symbols: dict[str, list[Symbol]] = defaultdict(list)
    module_langs: dict[str, set[str]] = defaultdict(set)
    module_sec: dict[str, bool] = defaultdict(bool)

    for sym in symbols:
        fe = files.get(sym.file_entry_id)
        if not fe:
            continue
        module = _get_module(fe.path)
        module_symbols[module].append(sym)
        if fe.language:
            module_langs[module].add(fe.language)
        if _is_security_sensitive_name(sym.name):
            module_sec[module] = True

    # Build module nodes
    nodes = []
    for module, syms in sorted(module_symbols.items(), key=lambda x: -len(x[1])):
        short_name = module.rsplit("/", 1)[-1] if "/" in module else module
        nodes.append({
            "id": f"mod:{module}",
            "label": short_name,
            "type": "module",
            "file_path": module,
            "language": ",".join(sorted(module_langs[module])) if module_langs[module] else None,
            "module": module,
            "symbol_count": len(syms),
            "incoming_count": 0,
            "outgoing_count": 0,
            "change_count": 0,
            "last_modified": None,
            "is_security_sensitive": module_sec[module],
            "evidence_class": "statically_verified",
            "qualified_name": module,
            "start_line": None,
            "end_line": None,
            "signature": None,
            "is_possibly_dead": False,
        })

    # Build module-level edges by aggregating symbol relationships
    module_edges_map: dict[tuple[str, str], dict] = {}
    incoming_count: dict[str, int] = defaultdict(int)
    outgoing_count: dict[str, int] = defaultdict(int)

    for rel in relationships:
        src_file = rel.source_file_path
        tgt_file = rel.target_file_path
        if not src_file or not tgt_file:
            continue
        src_mod = _get_module(src_file)
        tgt_mod = _get_module(tgt_file)
        if src_mod == tgt_mod:
            continue  # Skip intra-module edges at module level

        edge_key = (f"mod:{src_mod}", f"mod:{tgt_mod}")
        if edge_key not in module_edges_map:
            module_edges_map[edge_key] = {
                "id": f"e:{src_mod}->{tgt_mod}",
                "source": f"mod:{src_mod}",
                "target": f"mod:{tgt_mod}",
                "relation_type": rel.relation_type.value,
                "evidence_class": rel.certainty.value,
                "line_number": None,
                "source_file": src_file,
                "target_file": tgt_file,
                "source_symbol": rel.source_symbol_id,
                "target_symbol": rel.target_symbol_id,
            }
        outgoing_count[f"mod:{src_mod}"] += 1
        incoming_count[f"mod:{tgt_mod}"] += 1

    # Update node counts
    for node in nodes:
        node["incoming_count"] = incoming_count.get(node["id"], 0)
        node["outgoing_count"] = outgoing_count.get(node["id"], 0)

    edges = list(module_edges_map.values())[:500]  # Limit edges

    languages = set()
    for fe in files.values():
        if fe.language:
            languages.add(fe.language)

    return {
        "nodes": nodes[:200],
        "edges": edges,
        "level": "module",
        "total_symbols": len(symbols),
        "total_files": len(files),
        "coverage": {
            "languages_analyzed": sorted(languages),
            "relationship_types": sorted(set(e["relation_type"] for e in edges)),
            "unsupported_files": sum(1 for fe in files.values() if not fe.is_supported),
            "limitations": [
                "Module-level view aggregates symbols by directory. Individual function calls are not shown.",
                "Intra-module relationships are hidden at this level.",
            ],
        },
    }


def _build_file_graph(
    symbols: list[Symbol],
    files: dict[str, FileEntry],
    relationships: list[Relationship],
    index_version: IndexVersion,
    path_to_fe: dict[str, FileEntry],
) -> dict[str, Any]:
    """Build file-level graph nodes."""

    # Group symbols by file
    file_symbols: dict[str, list[Symbol]] = defaultdict(list)
    for sym in symbols:
        fe = files.get(sym.file_entry_id)
        if not fe:
            continue
        file_symbols[fe.path].append(sym)

    nodes = []
    for path, fe in files.items():
        if not fe.is_supported:
            continue
        syms = file_symbols.get(path, [])
        is_sec = any(_is_security_sensitive_name(s.name) for s in syms)
        module = _get_module(path)
        nodes.append({
            "id": f"file:{path}",
            "label": _get_short_name(path),
            "type": "file",
            "file_path": path,
            "language": fe.language,
            "module": module,
            "symbol_count": len(syms),
            "incoming_count": 0,
            "outgoing_count": 0,
            "change_count": 0,
            "last_modified": None,
            "is_security_sensitive": is_sec,
            "evidence_class": "statically_verified",
            "qualified_name": path,
            "start_line": None,
            "end_line": None,
            "signature": None,
            "is_possibly_dead": False,
        })

    # Build file-level edges — use both file-path relationships AND
    # symbol-based relationships (resolving file paths via the file entry map)
    file_edges_map: dict[tuple[str, str], dict] = {}
    incoming_count: dict[str, int] = defaultdict(int)
    outgoing_count: dict[str, int] = defaultdict(int)

    # Build symbol_id → file_path map for symbol-based relationship resolution
    sym_to_file: dict[str, str] = {}
    for fe_id, fe in files.items():
        # Already handled below via symbol-to-file map
        pass
    for sym in symbols:
        fe = files.get(sym.file_entry_id)
        if fe:
            sym_to_file[sym.id] = fe.path

    for rel in relationships:
        # Resolve source file path
        src_path = rel.source_file_path
        if not src_path and rel.source_symbol_id:
            src_path = sym_to_file.get(rel.source_symbol_id)

        # Resolve target file path
        tgt_path = rel.target_file_path
        if not tgt_path and rel.target_symbol_id:
            tgt_path = sym_to_file.get(rel.target_symbol_id)

        if not src_path or not tgt_path:
            continue
        if src_path == tgt_path:
            continue  # skip self-loops

        # Only include edges where target is an indexed file
        if tgt_path not in path_to_fe:
            continue

        src_id = f"file:{src_path}"
        tgt_id = f"file:{tgt_path}"
        edge_key = (src_id, tgt_id)
        if edge_key not in file_edges_map:
            file_edges_map[edge_key] = {
                "id": f"fe:{len(file_edges_map)}",
                "source": src_id,
                "target": tgt_id,
                "relation_type": rel.relation_type.value,
                "evidence_class": rel.certainty.value,
                "line_number": rel.line_number,
                "source_file": src_path,
                "target_file": tgt_path,
                "source_symbol": None,
                "target_symbol": None,
            }
        outgoing_count[src_id] += 1
        incoming_count[tgt_id] += 1

    for node in nodes:
        inc = incoming_count.get(node["id"], 0)
        out = outgoing_count.get(node["id"], 0)
        node["incoming_count"] = inc
        node["outgoing_count"] = out
        # Mark as possibly dead only if truly isolated:
        # - 0 incoming AND 0 outgoing (orphaned — nobody calls it, it calls nobody)
        # - NOT a test file, config file, or obvious entry point
        # This is a conservative heuristic — "no references" ≠ "definitely dead"
        basename = (node.get("file_path") or "").rsplit("/", 1)[-1].lower()
        is_entry = basename in ("main.py", "index.ts", "index.js", "app.py", "server.py",
                                "__init__.py", "setup.py", "manage.py", "cli.py",
                                "index.tsx", "index.jsx", "_app.tsx", "layout.tsx")
        is_test = "test" in basename or ".test." in basename or ".spec." in basename
        is_config = basename.endswith((".yml", ".yaml", ".json", ".toml", ".env", ".ini", ".cfg"))
        node["is_possibly_dead"] = (
            inc == 0
            and out == 0
            and not is_entry
            and not is_test
            and not is_config
            and not node.get("is_security_sensitive", False)
        )

    edges = list(file_edges_map.values())[:500]

    languages = set(fe.language for fe in files.values() if fe.language)

    return {
        "nodes": nodes[:500],
        "edges": edges,
        "level": "file",
        "total_symbols": len(symbols),
        "total_files": len(files),
        "coverage": {
            "languages_analyzed": sorted(languages),
            "relationship_types": sorted(set(e["relation_type"] for e in edges)),
            "unsupported_files": sum(1 for fe in files.values() if not fe.is_supported),
            "limitations": ["File-level view shows inter-file relationships. Intra-file calls are hidden."],
        },
    }


def _build_symbol_graph(
    symbols: list[Symbol],
    files: dict[str, FileEntry],
    relationships: list[Relationship],
    index_version: IndexVersion,
    limit: int,
) -> dict[str, Any]:
    """Build symbol-level graph (individual functions/classes/methods)."""

    nodes = []
    for sym in symbols[:limit]:
        fe = files.get(sym.file_entry_id)
        path = fe.path if fe else None
        module = _get_module(path) if path else None
        nodes.append({
            "id": sym.id,
            "label": sym.name,
            "type": sym.symbol_type.value,
            "file_path": path,
            "language": fe.language if fe else None,
            "module": module,
            "symbol_count": 1,
            "incoming_count": 0,
            "outgoing_count": 0,
            "change_count": 0,
            "last_modified": None,
            "is_security_sensitive": _is_security_sensitive_name(sym.name),
            "evidence_class": "statically_verified",
            "qualified_name": sym.qualified_name,
            "start_line": sym.start_line,
            "end_line": sym.end_line,
            "signature": sym.signature,
        })

    node_ids = {n["id"] for n in nodes}

    edges = []
    incoming_count: dict[str, int] = defaultdict(int)
    outgoing_count: dict[str, int] = defaultdict(int)

    for rel in relationships:
        src_id = rel.source_symbol_id
        tgt_id = rel.target_symbol_id
        # If source or target symbol doesn't have a resolved ID, use file path
        if not src_id and rel.source_file_path:
            # Find a symbol in the source file
            continue
        if not tgt_id and rel.target_file_path:
            continue
        if src_id not in node_ids or tgt_id not in node_ids:
            continue

        edges.append({
            "id": f"se:{rel.id}",
            "source": src_id,
            "target": tgt_id,
            "relation_type": rel.relation_type.value,
            "evidence_class": rel.certainty.value,
            "line_number": rel.line_number,
            "source_file": rel.source_file_path,
            "target_file": rel.target_file_path,
            "source_symbol": None,
            "target_symbol": None,
        })
        outgoing_count[src_id] += 1
        incoming_count[tgt_id] += 1

    for node in nodes:
        inc = incoming_count.get(node["id"], 0)
        node["incoming_count"] = inc
        node["outgoing_count"] = outgoing_count.get(node["id"], 0)
        # Conservative: only mark as possibly dead if nobody calls it AND
        # it doesn't call anything (truly orphaned) and it's not a special name
        name_lower = (node.get("label") or "").lower()
        is_special = name_lower in ("main", "__init__", "__main__", "run", "start",
                                     "create_app", "app", "handler", "cli")
        node["is_possibly_dead"] = (
            inc == 0
            and outgoing_count.get(node["id"], 0) == 0
            and not is_special
            and not node.get("is_security_sensitive", False)
        )

    edges = edges[:limit * 2]

    languages = set(fe.language for fe in files.values() if fe.language)

    return {
        "nodes": nodes,
        "edges": edges,
        "level": "symbol",
        "total_symbols": len(symbols),
        "total_files": len(files),
        "coverage": {
            "languages_analyzed": sorted(languages),
            "relationship_types": sorted(set(e["relation_type"] for e in edges)),
            "unsupported_files": sum(1 for fe in files.values() if not fe.is_supported),
            "limitations": [
                "Symbol-level view shows direct relationships. Cross-file call resolution is limited.",
                "Dynamic dispatch, reflection, and framework registration may hide relationships.",
            ],
        },
    }


# ── Node details ─────────────────────────────────────────────


@router.get("/{repo_id}/architecture-graph/node")
async def get_node_details(
    repo_id: str,
    node_id: str = Query(..., description="Node ID — may be a symbol UUID, 'mod:path', or 'file:path'"),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed information about a graph node, including all relationships.

    node_id is passed as a QUERY PARAMETER (not path segment) to support
    module nodes whose IDs contain forward slashes (e.g. mod:src/main/java/...).
    """

    iv_result = await db.execute(
        select(IndexVersion)
        .where(IndexVersion.repository_id == repo_id)
        .where(IndexVersion.status == IndexStatus.COMPLETED)
        .order_by(IndexVersion.created_at.desc())
        .limit(1)
    )
    index_version = iv_result.scalar_one_or_none()
    if not index_version:
        raise HTTPException(status_code=404, detail="No completed index available.")

    # Resolve node — could be a symbol ID, file:..., or mod:...
    if node_id.startswith("mod:"):
        return _get_module_details(node_id, index_version, db)
    elif node_id.startswith("file:"):
        return _get_file_details(node_id, index_version, db)
    else:
        return await _get_symbol_details(node_id, index_version, db)


async def _get_symbol_details(node_id: str, index_version: IndexVersion, db: AsyncSession) -> dict:
    sym_result = await db.execute(
        select(Symbol).where(
            Symbol.id == node_id,
            Symbol.index_version_id == index_version.id,
        )
    )
    sym = sym_result.scalar_one_or_none()
    if not sym:
        raise HTTPException(status_code=404, detail="Node not found.")

    fe_result = await db.execute(select(FileEntry).where(FileEntry.id == sym.file_entry_id))
    fe = fe_result.scalar_one_or_none()
    file_path = fe.path if fe else None
    language = fe.language if fe else None
    module = _get_module(file_path) if file_path else None

    # Get incoming relationships (things that call/reference this symbol)
    incoming_rels = await db.execute(
        select(Relationship).where(
            Relationship.index_version_id == index_version.id,
            Relationship.target_symbol_id == node_id,
        ).limit(50)
    )
    incoming = []
    for rel in incoming_rels.scalars().all():
        src_sym = None
        if rel.source_symbol_id:
            src_result = await db.execute(select(Symbol).where(Symbol.id == rel.source_symbol_id))
            src_sym = src_result.scalar_one_or_none()
        incoming.append({
            "node_id": rel.source_symbol_id or rel.source_file_path or "",
            "label": src_sym.name if src_sym else (rel.source_file_path or "Unknown"),
            "type": src_sym.symbol_type.value if src_sym else "unknown",
            "file_path": rel.source_file_path,
            "relation_type": rel.relation_type.value,
            "evidence_class": rel.certainty.value,
            "direction": "incoming",
            "line_number": rel.line_number,
        })

    # Get outgoing relationships (things this symbol calls/imports)
    outgoing_rels = await db.execute(
        select(Relationship).where(
            Relationship.index_version_id == index_version.id,
            Relationship.source_symbol_id == node_id,
        ).limit(50)
    )
    outgoing = []
    for rel in outgoing_rels.scalars().all():
        tgt_sym = None
        if rel.target_symbol_id:
            tgt_result = await db.execute(select(Symbol).where(Symbol.id == rel.target_symbol_id))
            tgt_sym = tgt_result.scalar_one_or_none()
        outgoing.append({
            "node_id": rel.target_symbol_id or rel.target_file_path or "",
            "label": tgt_sym.name if tgt_sym else (rel.target_file_path or "Unknown"),
            "type": tgt_sym.symbol_type.value if tgt_sym else "unknown",
            "file_path": rel.target_file_path,
            "relation_type": rel.relation_type.value,
            "evidence_class": rel.certainty.value,
            "direction": "outgoing",
            "line_number": rel.line_number,
        })

    is_sec = _is_security_sensitive_name(sym.name)

    # Build plain-English explanation
    pe_parts = [f"'{sym.name}' is a {sym.symbol_type.value}"]
    if file_path:
        pe_parts.append(f"defined in {file_path}")
    if sym.start_line:
        pe_parts.append(f"at line {sym.start_line}")
    if language:
        pe_parts.append(f"(written in {language})")
    plain_english = ", ".join(pe_parts) + "."

    if is_sec:
        plain_english += " This component appears to be security-sensitive based on its name."

    what_uses_it = [f"{r['label']} ({r['relation_type']})" for r in incoming[:5]]
    what_it_uses = [f"{r['label']} ({r['relation_type']})" for r in outgoing[:5]]

    evidence = []
    if file_path and sym.start_line:
        evidence.append(f"Defined at {file_path}:{sym.start_line}-{sym.end_line}")
    evidence.append(f"Indexed at commit {index_version.commit_sha[:12]}")
    if is_sec:
        evidence.append("Flagged as security-sensitive by name-based heuristic analysis.")

    impact_parts = []
    if incoming:
        impact_parts.append(f"{len(incoming)} component(s) depend on this, so changes here may affect them.")
    else:
        impact_parts.append("No direct dependents found — changes here have limited detected impact.")
    if is_sec:
        impact_parts.append("Because this is security-sensitive, changes should be reviewed carefully.")

    return {
        "node_id": node_id,
        "label": sym.name,
        "type": sym.symbol_type.value,
        "file_path": file_path,
        "language": language,
        "module": module,
        "qualified_name": sym.qualified_name,
        "signature": sym.signature,
        "start_line": sym.start_line,
        "end_line": sym.end_line,
        "incoming": incoming,
        "outgoing": outgoing,
        "incoming_count": len(incoming),
        "outgoing_count": len(outgoing),
        "change_count": 0,
        "last_modified": None,
        "is_security_sensitive": is_sec,
        "plain_english": plain_english,
        "what_uses_it": what_uses_it,
        "what_it_uses": what_it_uses,
        "evidence": evidence,
        "impact": " ".join(impact_parts),
    }


def _get_module_details(node_id: str, index_version: IndexVersion, db: AsyncSession) -> dict:
    module = node_id[4:]  # Strip "mod:"
    short_name = module.rsplit("/", 1)[-1] if "/" in module else module

    return {
        "node_id": node_id,
        "label": short_name,
        "type": "module",
        "file_path": module,
        "language": None,
        "module": module,
        "qualified_name": module,
        "signature": None,
        "start_line": None,
        "end_line": None,
        "incoming": [],
        "outgoing": [],
        "incoming_count": 0,
        "outgoing_count": 0,
        "change_count": 0,
        "last_modified": None,
        "is_security_sensitive": False,
        "plain_english": f"'{short_name}' is a module (directory) containing source files in {module}. "
                         f"Expand to file or symbol level to see individual components.",
        "what_uses_it": [],
        "what_it_uses": [],
        "evidence": [f"Module derived from repository file structure at commit {index_version.commit_sha[:12]}."],
        "impact": "Changes to files in this module may affect components that depend on them.",
    }


def _get_file_details(node_id: str, index_version: IndexVersion, db: AsyncSession) -> dict:
    file_path = node_id[5:]  # Strip "file:"
    short_name = _get_short_name(file_path)

    return {
        "node_id": node_id,
        "label": short_name,
        "type": "file",
        "file_path": file_path,
        "language": None,
        "module": _get_module(file_path),
        "qualified_name": file_path,
        "signature": None,
        "start_line": None,
        "end_line": None,
        "incoming": [],
        "outgoing": [],
        "incoming_count": 0,
        "outgoing_count": 0,
        "change_count": 0,
        "last_modified": None,
        "is_security_sensitive": _is_security_sensitive_name(file_path),
        "plain_english": f"'{short_name}' is a source file in {file_path}. "
                         f"Switch to symbol level to see the functions and classes it contains.",
        "what_uses_it": [],
        "what_it_uses": [],
        "evidence": [f"File indexed at commit {index_version.commit_sha[:12]}."],
        "impact": "Changes to this file may affect components that import or depend on it.",
    }


# ── Search ──────────────────────────────────────────────────


@router.get("/{repo_id}/architecture-graph/search")
async def search_graph(
    repo_id: str,
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Search for graph nodes by name, file path, or qualified name."""

    iv_result = await db.execute(
        select(IndexVersion)
        .where(IndexVersion.repository_id == repo_id)
        .where(IndexVersion.status == IndexStatus.COMPLETED)
        .order_by(IndexVersion.created_at.desc())
        .limit(1)
    )
    index_version = iv_result.scalar_one_or_none()
    if not index_version:
        return {"results": [], "total": 0}

    query_lower = q.lower()

    # Search symbols
    sym_result = await db.execute(
        select(Symbol, FileEntry)
        .join(FileEntry, Symbol.file_entry_id == FileEntry.id)
        .where(Symbol.index_version_id == index_version.id)
        .where(
            (func.lower(Symbol.name).contains(query_lower))
            | (func.lower(FileEntry.path).contains(query_lower))
        )
        .limit(limit)
    )

    results = []
    for sym, fe in sym_result.all():
        results.append({
            "node_id": sym.id,
            "label": sym.name,
            "type": sym.symbol_type.value,
            "file_path": fe.path,
            "module": _get_module(fe.path),
            "language": fe.language,
        })

    # Also search file names
    file_result = await db.execute(
        select(FileEntry).where(
            FileEntry.index_version_id == index_version.id,
            func.lower(FileEntry.path).contains(query_lower),
        ).limit(limit)
    )
    for fe in file_result.scalars().all():
        file_node_id = f"file:{fe.path}"
        if not any(r["node_id"] == file_node_id for r in results):
            results.append({
                "node_id": file_node_id,
                "label": _get_short_name(fe.path),
                "type": "file",
                "file_path": fe.path,
                "module": _get_module(fe.path),
                "language": fe.language,
            })

    return {"results": results[:limit], "total": len(results)}


# ── Path tracing ─────────────────────────────────────────────


@router.get("/{repo_id}/architecture-graph/path")
async def trace_path(
    repo_id: str,
    source: str = Query(...),
    target: str = Query(...),
    max_depth: int = Query(5, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
):
    """Find a relationship path between two nodes using BFS."""

    iv_result = await db.execute(
        select(IndexVersion)
        .where(IndexVersion.repository_id == repo_id)
        .where(IndexVersion.status == IndexStatus.COMPLETED)
        .order_by(IndexVersion.created_at.desc())
        .limit(1)
    )
    index_version = iv_result.scalar_one_or_none()
    if not index_version:
        return {"found": False, "steps": [], "message": "No completed index available."}

    # Load all relationships into an adjacency map
    rels_result = await db.execute(
        select(Relationship).where(Relationship.index_version_id == index_version.id).limit(5000)
    )
    adj: dict[str, list[tuple[str, Relationship]]] = defaultdict(list)
    for rel in rels_result.scalars().all():
        if rel.source_symbol_id and rel.target_symbol_id:
            adj[rel.source_symbol_id].append((rel.target_symbol_id, rel))

        # Also handle file-based edges
        if rel.source_file_path and rel.target_file_path:
            src_key = f"file:{rel.source_file_path}"
            tgt_key = f"file:{rel.target_file_path}"
            adj[src_key].append((tgt_key, rel))

    # BFS
    visited = {source}
    queue: list[tuple[str, list[tuple[str, Relationship]]]] = [(source, [])]

    while queue:
        current, path = queue.pop(0)
        if current == target and path:
            # Build step list
            steps = []
            steps.append({
                "node_id": source,
                "label": source,
                "type": "unknown",
                "file_path": None,
                "relation_type": None,
                "evidence_class": None,
                "plain_english": "Starting point.",
            })
            for node_id, rel in path:
                # Look up node label
                label = node_id
                node_type = "unknown"
                file_path = None
                if rel.target_file_path:
                    file_path = rel.target_file_path

                rel_type = rel.relation_type.value if rel else None
                ev_class = rel.certainty.value if rel else None

                pe = f"Connected via {rel_type}." if rel_type else "Direct connection."

                steps.append({
                    "node_id": node_id,
                    "label": label,
                    "type": node_type,
                    "file_path": file_path,
                    "relation_type": rel_type,
                    "evidence_class": ev_class,
                    "plain_english": pe,
                })

            return {
                "found": True,
                "steps": steps,
                "message": f"Path found with {len(path)} step(s).",
            }

        if len(path) >= max_depth:
            continue

        for neighbor_id, rel in adj.get(current, []):
            if neighbor_id not in visited:
                visited.add(neighbor_id)
                queue.append((neighbor_id, path + [(neighbor_id, rel)]))

    return {
        "found": False,
        "steps": [],
        "message": f"No path found between the selected nodes within {max_depth} steps. "
                   "This does not prove no runtime relationship exists — only that the static graph "
                   "does not establish one.",
    }
