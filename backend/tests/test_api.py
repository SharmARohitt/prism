"""Tests for API endpoints."""

import pytest
import json


class TestHealthEndpoint:
    """Test the health and readiness endpoints."""

    async def test_health_check(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "database" in data
        assert "llm_provider" in data

    async def test_ready_check(self, client):
        resp = await client.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ready"] is True


class TestRepositoryEndpoints:
    """Test repository connection, listing, and overview endpoints."""

    async def test_connect_repository_invalid_url(self, client):
        """Test that an invalid URL is rejected."""
        resp = await client.post("/api/repositories", json={"url": ""})
        assert resp.status_code == 400

    async def test_connect_repository_blocked_url(self, client):
        """Test that SSRF-blocked URLs are rejected."""
        resp = await client.post("/api/repositories", json={"url": "http://169.254.169.254/repo"})
        assert resp.status_code == 400
        assert "ssrf" in resp.json()["detail"].lower() or "metadata" in resp.json()["detail"].lower()

    async def test_list_repositories_empty(self, client):
        """Test listing repositories when none exist."""
        resp = await client.get("/api/repositories")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["repositories"] == []

    async def test_get_nonexistent_repository(self, client):
        """Test getting a non-existent repository returns 404."""
        resp = await client.get("/api/repositories/nonexistent-id")
        assert resp.status_code == 404

    async def test_connect_repository_invalid_scheme(self, client):
        """Test that invalid URL schemes are rejected."""
        resp = await client.post("/api/repositories", json={"url": "ftp://example.com/repo"})
        assert resp.status_code == 400


class TestSettingsEndpoint:
    """Test the settings endpoint."""

    async def test_get_settings(self, client):
        resp = await client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "llm" in data
        assert "integrations" in data
        assert "database_type" in data
        assert data["llm"]["provider"] == "ollama"

    async def test_settings_includes_scanner_integrations(self, client):
        resp = await client.get("/api/settings")
        data = resp.json()
        integration_names = [i["name"] for i in data["integrations"]]
        assert "coverity" in integration_names
        assert "blackduck" in integration_names
        assert "github" in integration_names


class TestMcpEndpoint:
    """Test the MCP tools endpoint."""

    async def test_list_mcp_tools(self, client):
        resp = await client.get("/api/mcp/tools")
        assert resp.status_code == 200
        data = resp.json()
        tools = data["tools"]
        assert len(tools) > 0
        # Check key tools are registered
        tool_names = [t["name"] for t in tools]
        assert "get_repository_overview" in tool_names
        assert "get_commit_diff" in tool_names
        assert "get_changed_symbols" in tool_names
        assert "get_symbol_definition" in tool_names
        assert "get_callers_and_callees" in tool_names
        assert "get_evidence_for_finding" in tool_names

    async def test_execute_mcp_tool_missing_repo(self, client):
        """Test that executing a tool without repository_id returns 400."""
        resp = await client.post("/api/mcp/tools/execute", json={
            "tool_name": "get_repository_overview",
            "arguments": {},
        })
        assert resp.status_code == 400

    async def test_execute_mcp_tool_unknown(self, client):
        """Test that an unknown tool returns an error."""
        resp = await client.post("/api/mcp/tools/execute", json={
            "tool_name": "nonexistent_tool",
            "arguments": {"repository_id": "test", "commit_sha": "abc"},
        })
        assert resp.status_code in (400, 404, 500)


class TestWebhookEndpoint:
    """Test webhook processing."""

    async def test_webhook_ping(self, client):
        """Test that a ping event is accepted."""
        resp = await client.post(
            "/api/webhooks/github",
            json={
                "repository": {"full_name": "test/repo", "clone_url": "https://github.com/test/repo"},
            },
            headers={"X-GitHub-Event": "ping"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] is True

    async def test_webhook_unknown_event(self, client):
        """Test that unknown event types return not accepted."""
        resp = await client.post(
            "/api/webhooks/github",
            json={
                "repository": {"full_name": "test/repo", "clone_url": "https://github.com/test/repo"},
            },
            headers={"X-GitHub-Event": "unknown_event"},
        )
        assert resp.status_code == 200

    async def test_webhook_missing_signature_with_secret(self, client):
        """Test that missing signature is handled."""
        # With default test secret, signature verification may be skipped in dev
        resp = await client.post(
            "/api/webhooks/github",
            json={
                "repository": {"full_name": "test/repo", "clone_url": "https://github.com/test/repo"},
            },
            headers={"X-GitHub-Event": "push"},
        )
        # Should be accepted (dev mode skips verification)
        assert resp.status_code == 200

    async def test_webhook_idempotency(self, client):
        """Test that duplicate delivery IDs don't cause double processing."""
        payload = {
            "repository": {"full_name": "test/repo", "clone_url": "https://github.com/test/repo"},
        }
        headers = {
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": "test-delivery-123",
        }

        # First request
        resp1 = await client.post("/api/webhooks/github", json=payload, headers=headers)
        assert resp1.status_code == 200

        # Second request with same delivery ID
        resp2 = await client.post("/api/webhooks/github", json=payload, headers=headers)
        assert resp2.status_code == 200
        assert "already processed" in resp2.json()["message"].lower()
