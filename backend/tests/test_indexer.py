"""Tests for the Tree-sitter code indexing engine."""

import pytest

from prism.core.indexer import (
    CodeIndexer,
    IndexedSymbol,
    _is_security_sensitive,
    detect_language,
)


class TestDetectLanguage:
    def test_python(self):
        assert detect_language("app.py") == "python"

    def test_javascript(self):
        assert detect_language("app.js") == "javascript"

    def test_typescript(self):
        assert detect_language("app.ts") == "typescript"

    def test_tsx(self):
        assert detect_language("App.tsx") == "typescript"

    def test_java(self):
        assert detect_language("Main.java") == "java"

    def test_go(self):
        assert detect_language("main.go") == "go"

    def test_rust(self):
        assert detect_language("main.rs") == "rust"

    def test_markdown(self):
        assert detect_language("README.md") == "markdown"

    def test_unsupported(self):
        assert detect_language("config.xyz") is None

    def test_no_extension(self):
        assert detect_language("Makefile") is None


class TestSecuritySensitiveDetection:
    def test_auth_function(self):
        assert _is_security_sensitive("authenticate", "def authenticate(user, password)")

    def test_password_function(self):
        assert _is_security_sensitive("check_password")

    def test_token_function(self):
        assert _is_security_sensitive("create_token")

    def test_sql_query(self):
        assert _is_security_sensitive("execute_query", "def execute_query(sql)")

    def test_encrypt_function(self):
        assert _is_security_sensitive("encrypt_data")

    def test_innocent_function(self):
        assert not _is_security_sensitive("format_date")

    def test_innocent_class(self):
        assert not _is_security_sensitive("UserFormatter", "class UserFormatter")

    def test_file_handler(self):
        assert _is_security_sensitive("open_file")


class TestCodeIndexer:
    async def test_index_python_file(self, sample_python_code):
        """Test that indexing a Python file extracts symbols."""
        indexer = CodeIndexer()
        # Create a minimal mock mirror
        from unittest.mock import AsyncMock
        mirror = AsyncMock()
        mirror.url = ""

        result = await indexer.index_file("app.py", sample_python_code, mirror)

        assert result.path == "app.py"
        assert result.language == "python"
        assert result.is_supported
        assert len(result.symbols) > 0

        # Check we found the class
        class_symbols = [s for s in result.symbols if s.symbol_type.value == "class"]
        assert len(class_symbols) >= 1
        assert class_symbols[0].name == "UserService"

        # Check we found functions
        func_symbols = [s for s in result.symbols if s.symbol_type.value == "function"]
        func_names = [s.name for s in func_symbols]
        assert "create_token" in func_names
        assert "validate_input" in func_names

        # Check we found methods
        method_symbols = [s for s in result.symbols if s.symbol_type.value == "method"]
        method_names = [s.name for s in method_symbols]
        assert "get_user" in method_names
        assert "authenticate" in method_names

    async def test_index_javascript_file(self, sample_javascript_code):
        """Test that indexing a JavaScript file extracts symbols."""
        indexer = CodeIndexer()
        from unittest.mock import AsyncMock
        mirror = AsyncMock()

        result = await indexer.index_file("server.js", sample_javascript_code, mirror)

        assert result.path == "server.js"
        assert result.language == "javascript"
        assert result.is_supported

    async def test_index_unsupported_file(self):
        """Test that unsupported files are handled gracefully."""
        indexer = CodeIndexer()
        from unittest.mock import AsyncMock
        mirror = AsyncMock()

        result = await indexer.index_file("config.xyz", "some content", mirror)

        assert result.path == "config.xyz"
        assert result.language is None
        assert not result.is_supported

    async def test_index_extracts_relationships(self, sample_python_code):
        """Test that indexing extracts import/call relationships."""
        indexer = CodeIndexer()
        from unittest.mock import AsyncMock
        mirror = AsyncMock()

        result = await indexer.index_file("app.py", sample_python_code, mirror)

        # Should have some relationships (imports or calls)
        assert len(result.relationships) > 0

        # Check for import relationships
        import_rels = [r for r in result.relationships if r.relation_type.value == "imports"]
        assert len(import_rels) > 0

    async def test_content_hash_is_computed(self, sample_python_code):
        """Test that content hash is computed for files."""
        indexer = CodeIndexer()
        from unittest.mock import AsyncMock
        mirror = AsyncMock()

        result = await indexer.index_file("app.py", sample_python_code, mirror)

        assert len(result.content_hash) == 64  # SHA-256 hex

    async def test_security_sensitive_symbols_detected(self, sample_python_code):
        """Test that security-sensitive symbols are identified."""
        indexer = CodeIndexer()
        from unittest.mock import AsyncMock
        mirror = AsyncMock()

        result = await indexer.index_file("app.py", sample_python_code, mirror)

        sensitive = indexer.get_security_sensitive_symbols(result.symbols)
        sensitive_names = [s.name for s in sensitive]
        assert "authenticate" in sensitive_names
        assert "create_token" in sensitive_names
        assert "validate_input" in sensitive_names
