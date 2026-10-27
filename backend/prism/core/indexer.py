"""Tree-sitter based code indexing engine.

Extracts symbols (functions, classes, methods), imports, calls, and references
from source files. Index entries are content-hash keyed for incremental reuse.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Any

from prism.core.git_mirror import GitMirror, detect_language
from prism.logging_config import get_logger
from prism.models import RelationCertainty, RelationType, SymbolType

logger = get_logger("prism.indexer")

# ── Tree-sitter setup ─────────────────────────────────────

_TSLang: Any = None  # tree-sitter module
_TS_AVAILABLE = False

# Language package imports — individual packages for Python 3.13+ compatibility
_LANGUAGE_MODULES: dict[str, Any] = {}

try:
    import tree_sitter  # type: ignore # noqa: F401
    _TS_AVAILABLE = True

    # Try importing each language package
    _lang_imports = {
        "python": "tree_sitter_python",
        "javascript": "tree_sitter_javascript",
        "typescript": "tree_sitter_typescript",
        "java": "tree_sitter_java",
        "go": "tree_sitter_go",
        "rust": "tree_sitter_rust",
        "ruby": "tree_sitter_ruby",
        "c": "tree_sitter_c",
        "cpp": "tree_sitter_cpp",
        "shell": "tree_sitter_bash",
    }

    for lang_name, module_name in _lang_imports.items():
        try:
            _LANGUAGE_MODULES[lang_name] = __import__(module_name)
        except ImportError:
            pass

except ImportError:
    logger.warning("tree_sitter_not_available", message="Tree-sitter package not found")


def _get_parser_for_language(lang_name: str) -> Any | None:
    """Get a tree-sitter parser for the given language."""
    if not _TS_AVAILABLE:
        return None
    lang_map = {
        "python": "python",
        "javascript": "javascript",
        "typescript": "typescript",
        "java": "java",
        "go": "go",
        "rust": "rust",
        "ruby": "ruby",
        "c": "c",
        "cpp": "cpp",
        "csharp": "csharp",
        "php": "php",
        "shell": "shell",
    }
    ts_name = lang_map.get(lang_name)
    if not ts_name:
        return None

    # For typescript, the package has tsx and tsx variants
    if lang_name == "typescript":
        try:
            from tree_sitter_typescript import language_typescript
            from tree_sitter import Language, Parser
            lang = Language(language_typescript())
            parser = Parser()
            parser.language = lang
            return parser
        except Exception:
            return None

    module = _LANGUAGE_MODULES.get(ts_name)
    if module is None:
        return None

    try:
        # Each language package exposes a `language()` function
        from tree_sitter import Language, Parser
        if hasattr(module, "language"):
            lang = Language(module.language())
        elif hasattr(module, "language_python"):
            lang = Language(module.language_python())
        else:
            return None
        parser = Parser()
        parser.language = lang
        return parser
    except Exception as e:
        logger.debug("parser_setup_failed", language=lang_name, error=str(e))
        return None


# ── Node type queries ─────────────────────────────────────
# These map tree-sitter node types to PRISM symbol types.
# We use simple heuristics rather than per-language queries for resilience.

SYMBOL_NODE_TYPES = {
    "function_definition": SymbolType.FUNCTION,
    "function_declaration": SymbolType.FUNCTION,
    "method_definition": SymbolType.METHOD,
    "method_declaration": SymbolType.METHOD,
    "class_definition": SymbolType.CLASS,
    "class_declaration": SymbolType.CLASS,
    "interface_declaration": SymbolType.INTERFACE,
    "decorator_definition": SymbolType.FUNCTION,
    "arrow_function": SymbolType.FUNCTION,
    "generator_function_declaration": SymbolType.FUNCTION,
    "export_statement": SymbolType.MODULE,
    "lexical_declaration": SymbolType.VARIABLE,
}

IMPORT_NODE_TYPES = {
    "import_statement",
    "import_declaration",
    "import_from_statement",
    "use_statement",
    "package_declaration",
}

CALL_NODE_TYPES = {
    "call",
    "call_expression",
    "invocation",
}

# Security-sensitive keywords for risk detection
SECURITY_KEYWORDS = {
    "password", "passwd", "secret", "token", "apikey", "api_key",
    "auth", "authorize", "authentication", "permission", "rbac",
    "crypt", "hash", "salt", "cipher", "encrypt", "decrypt",
    "sql", "query", "execute", "raw_query",
    "file", "path", "open", "read", "write", "unlink",
    "shell", "exec", "system", "subprocess", "popen",
    "request", "http", "url", "fetch", "redirect",
    "cookie", "session", "jwt", "oauth",
    "privilege", "sudo", "admin", "root",
    "upload", "download", "serialize", "deserialize",
    "eval", "unsafe", "dangerous",
    "validate", "validation", "input", "sanitiz", "escape", "injection",
}


@dataclass
class IndexedSymbol:
    name: str
    qualified_name: str
    symbol_type: SymbolType
    start_line: int
    end_line: int
    signature: str | None
    content_hash: str
    docstring: str | None
    file_path: str


@dataclass
class IndexedRelationship:
    source_symbol: str | None
    target_symbol: str | None
    source_file_path: str
    target_file_path: str | None
    relation_type: RelationType
    certainty: RelationCertainty
    line_number: int


@dataclass
class IndexedFile:
    path: str
    content_hash: str
    language: str | None
    line_count: int
    is_supported: bool
    is_test: bool
    symbols: list[IndexedSymbol] = field(default_factory=list)
    relationships: list[IndexedRelationship] = field(default_factory=list)


@dataclass
class IndexResult:
    files: list[IndexedFile] = field(default_factory=list)
    total_symbols: int = 0
    total_relationships: int = 0
    unsupported: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ── Name extraction helpers ───────────────────────────────


def _extract_name(node: Any) -> str | None:
    """Extract a human-readable name from a tree-sitter node."""
    # Look for identifier children
    for child in node.children:
        if hasattr(child, "type") and child.type in ("identifier", "property_identifier", "type_identifier"):
            if hasattr(child, "text"):
                return child.text.decode("utf-8", errors="replace")
    # Look in named fields
    for field_name in ("name", "function_name", "class_name"):
        try:
            child = node.child_by_field_name(field_name)
            if child and hasattr(child, "text"):
                return child.text.decode("utf-8", errors="replace")
        except Exception:
            pass
    return None


def _get_text(node: Any, source_bytes: bytes) -> str:
    """Get text content of a node."""
    if hasattr(node, "text"):
        return node.text.decode("utf-8", errors="replace")
    start_byte = node.start_byte
    end_byte = node.end_byte
    return source_bytes[start_byte:end_byte].decode("utf-8", errors="replace")


def _extract_docstring(node: Any, source_bytes: bytes) -> str | None:
    """Extract docstring/comment immediately after a function/class."""
    for child in node.children:
        if hasattr(child, "type") and child.type in ("string", "string_literal", "expression_statement"):
            text = _get_text(child, source_bytes)
            if text.strip().startswith(('"', "'", '"""', "'''", "/*")):
                return text.strip().strip('"').strip("'").strip()
    return None


def _extract_calls(node: Any, source_bytes: bytes, file_path: str) -> list[IndexedRelationship]:
    """Extract function call relationships from a node's subtree."""
    relationships: list[IndexedRelationship] = []

    def _walk(n: Any):
        if hasattr(n, "type") and n.type in CALL_NODE_TYPES:
            func_name = _extract_name(n) or _get_name_from_call(n, source_bytes)
            if func_name:
                relationships.append(IndexedRelationship(
                    source_symbol=None,
                    target_symbol=func_name,
                    source_file_path=file_path,
                    target_file_path=None,
                    relation_type=RelationType.CALLS,
                    certainty=RelationCertainty.STATICALLY_VERIFIED,
                    line_number=n.start_point[0] + 1 if hasattr(n, "start_point") else None,
                ))
        if hasattr(n, "children"):
            for child in n.children:
                _walk(child)

    _walk(node)
    return relationships


def _get_name_from_call(node: Any, source_bytes: bytes) -> str | None:
    """Try to get function name from a call expression."""
    # Try function field
    for field_name in ("function", "callee"):
        try:
            child = node.child_by_field_name(field_name)
            if child and hasattr(child, "text"):
                return child.text.decode("utf-8", errors="replace")
        except Exception:
            pass
    # First identifier child
    for child in getattr(node, "children", []):
        if hasattr(child, "type") and child.type in ("identifier", "attribute", "member_expression"):
            return _get_text(child, source_bytes)
    return None


def _extract_imports(node: Any, source_bytes: bytes, file_path: str) -> list[IndexedRelationship]:
    """Extract import relationships."""
    relationships: list[IndexedRelationship] = []
    text = _get_text(node, source_bytes)

    # Simple regex-like extraction of imported names
    # This is intentionally conservative — we don't want false relationships
    lines = text.split("\n")
    for i, line in enumerate(lines):
        line = line.strip()
        # Python: from X import Y / import X
        # JS/TS: import { X } from Y / import X from Y / const X = require(Y)
        # Go: import "X"
        # Java: import X.Y
        target = None
        if line.startswith("from ") or line.startswith("import ") or line.startswith("require"):
            # Extract module/package path
            for sep in ("from ", "import ", "require("):
                if sep in line:
                    parts = line.split(sep)
                    if len(parts) > 1:
                        target = parts[-1].strip().strip("\"'();")
                        break
            if not target:
                # Just take the whole line as the import target
                target = line
        elif line.startswith("use "):
            target = line[4:].strip().strip(";\"'")

        if target:
            relationships.append(IndexedRelationship(
                source_symbol=None,
                target_symbol=target,
                source_file_path=file_path,
                target_file_path=None,
                relation_type=RelationType.IMPORTS,
                certainty=RelationCertainty.STATICALLY_VERIFIED,
                line_number=i + 1,
            ))

    return relationships


def _is_security_sensitive(name: str, signature: str | None = None) -> bool:
    """Check if a symbol name or signature suggests security sensitivity."""
    text = name.lower()
    if signature:
        text += " " + signature.lower()
    for keyword in SECURITY_KEYWORDS:
        if keyword in text:
            return True
    return False


# ── Indexing ──────────────────────────────────────────────


class CodeIndexer:
    """Indexes source files using Tree-sitter for symbol/relationship extraction."""

    async def index_file(
        self,
        file_path: str,
        content: str,
        mirror: GitMirror,
    ) -> IndexedFile:
        """Index a single file, extracting symbols and relationships."""
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        lines = content.split("\n")
        line_count = len(lines)
        lang = detect_language(file_path)
        is_test = any(p in file_path.lower() for p in ("test", "_test", ".test.", ".spec.", "tests/"))

        indexed = IndexedFile(
            path=file_path,
            content_hash=content_hash,
            language=lang,
            line_count=line_count,
            is_supported=lang is not None,
            is_test=is_test,
        )

        if lang is None:
            return indexed

        parser = _get_parser_for_language(lang)
        if parser is None:
            indexed.is_supported = False
            return indexed

        try:
            source_bytes = content.encode("utf-8")
            tree = parser.parse(source_bytes)
            root = tree.root_node

            # Walk the tree
            self._walk_tree(root, source_bytes, file_path, indexed)

        except Exception as e:
            indexed.is_supported = False
            logger.warning("parse_error", file=file_path, error=str(e))

        return indexed

    def _walk_tree(
        self,
        node: Any,
        source_bytes: bytes,
        file_path: str,
        indexed: IndexedFile,
        in_class: bool = False,
    ) -> None:
        """Walk tree-sitter AST and extract symbols/relationships."""
        node_type = getattr(node, "type", None)

        # Track class context for method detection
        new_in_class = in_class
        if node_type == "class_definition" or node_type == "class_declaration":
            new_in_class = True
        elif node_type in ("function_definition", "function_declaration") and not in_class:
            new_in_class = False

        # Symbol detection
        if node_type in SYMBOL_NODE_TYPES:
            name = _extract_name(node)
            if name:
                start_line = node.start_point[0] + 1 if hasattr(node, "start_point") else 1
                end_line = node.end_point[0] + 1 if hasattr(node, "end_point") else start_line
                signature = self._extract_signature(node, source_bytes)
                docstring = _extract_docstring(node, source_bytes)
                content_text = _get_text(node, source_bytes)
                sym_hash = hashlib.sha256(content_text.encode("utf-8")).hexdigest()

                # In Python, methods are function_definition nodes inside a class.
                # Adjust the symbol type if we're inside a class context.
                sym_type = SYMBOL_NODE_TYPES[node_type]
                if in_class and sym_type == SymbolType.FUNCTION:
                    sym_type = SymbolType.METHOD

                sym = IndexedSymbol(
                    name=name,
                    qualified_name=f"{file_path}:{name}" if "." not in name else name,
                    symbol_type=sym_type,
                    start_line=start_line,
                    end_line=end_line,
                    signature=signature,
                    content_hash=sym_hash,
                    docstring=docstring,
                    file_path=file_path,
                )
                indexed.symbols.append(sym)

                # Extract calls within this symbol's body
                calls = _extract_calls(node, source_bytes, file_path)
                for call in calls:
                    call.source_symbol = name
                    indexed.relationships.append(call)

        # Import detection
        if node_type in IMPORT_NODE_TYPES:
            imports = _extract_imports(node, source_bytes, file_path)
            indexed.relationships.extend(imports)

        # Recurse
        if hasattr(node, "children"):
            for child in node.children:
                self._walk_tree(child, source_bytes, file_path, indexed, new_in_class)

    def _extract_signature(self, node: Any, source_bytes: bytes) -> str | None:
        """Extract a function/method signature (first line or declaration)."""
        text = _get_text(node, source_bytes)
        # Take first line as signature approximation
        first_line = text.split("\n")[0].strip()
        if len(first_line) > 200:
            return first_line[:200] + "..."
        return first_line

    async def index_repository(
        self,
        mirror: GitMirror,
        commit_sha: str,
        file_paths: list[str] | None = None,
        reuse_hashes: dict[str, str] | None = None,
    ) -> IndexResult:
        """
        Index all supported files at a given commit.

        Args:
            mirror: Git mirror to index
            commit_sha: Commit to index at
            file_paths: Optional subset of files to index (for incremental)
            reuse_hashes: Map of file_path -> content_hash that can be reused
                         (file was unchanged since last index)
        """
        result = IndexResult()
        reuse_hashes = reuse_hashes or {}

        # If no file_paths given, get all files from the commit
        if file_paths is None:
            structure = await mirror.analyze_structure(commit_sha)
            file_paths = [p for p in structure.file_paths if detect_language(p) is not None]

        for file_path in file_paths:
            lang = detect_language(file_path)
            if lang is None:
                result.unsupported.append(file_path)
                continue

            # Check if we can reuse (content hash unchanged)
            content = await mirror.get_file_content(file_path, commit_sha)
            if content is None:
                result.warnings.append(f"Could not read {file_path}")
                continue

            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if reuse_hashes.get(file_path) == content_hash:
                # Skip — can reuse existing index entry
                logger.debug("reusing_index_entry", file=file_path)
                continue

            indexed_file = await self.index_file(file_path, content, mirror)
            result.files.append(indexed_file)

            if not indexed_file.is_supported:
                result.unsupported.append(file_path)

            result.total_symbols += len(indexed_file.symbols)
            result.total_relationships += len(indexed_file.relationships)

        logger.info(
            "indexed_repository",
            commit=commit_sha[:12],
            files=len(result.files),
            symbols=result.total_symbols,
            relationships=result.total_relationships,
            unsupported=len(result.unsupported),
        )
        return result

    def get_security_sensitive_symbols(self, symbols: list[IndexedSymbol]) -> list[IndexedSymbol]:
        """Filter symbols that are security-sensitive based on name/signature."""
        return [s for s in symbols if _is_security_sensitive(s.name, s.signature)]


# Singleton
indexer = CodeIndexer()
