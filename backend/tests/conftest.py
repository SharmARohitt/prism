"""Pytest configuration and fixtures."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Add backend to path so tests can import prism
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set test environment BEFORE importing prism modules
os.environ["DATABASE_URL"] = "sqlite:///./test_prism.db"
os.environ["GIT_MIRROR_DIR"] = str(Path(tempfile.gettempdir()) / "prism-test-mirrors")
os.environ["OLLAMA_BASE_URL"] = "http://localhost:99999"  # Non-existent — tests use stub
os.environ["WEBHOOK_SECRET"] = "change-me-to-a-random-secret"
os.environ["LOG_LEVEL"] = "WARNING"

from prism.config import get_settings, reload_settings  # noqa: E402
from prism.database import Base, close_db, get_db, init_db  # noqa: E402
from prism.main import create_app  # noqa: E402

# Force reload settings with test env
reload_settings()


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_setup():
    """Initialize a fresh in-memory database for each test."""
    # Reset engine
    import prism.database as db_mod
    db_mod._engine = None
    db_mod._session_factory = None

    await init_db()
    yield
    await close_db()

    # Clean up test DB file
    if Path("test_prism.db").exists():
        Path("test_prism.db").unlink()


@pytest_asyncio.fixture(scope="function")
async def client(db_setup):
    """Create an HTTP test client."""
    app = create_app()

    # Start/stop lifespan
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture
async def db_session(db_setup):
    """Get a database session for direct DB testing."""
    from prism.database import get_session
    async with get_session() as session:
        yield session


@pytest.fixture
def sample_python_code():
    """Sample Python source code for indexing tests."""
    return '''"""Sample module for testing."""

import os
from typing import Optional


class UserService:
    """Handles user operations."""

    def __init__(self, db):
        self.db = db

    def get_user(self, user_id: int) -> Optional[dict]:
        """Retrieve a user by ID."""
        return self.db.query(user_id)

    def authenticate(self, username: str, password: str) -> bool:
        """Check user credentials."""
        user = self.db.find_by_username(username)
        if user and user.check_password(password):
            return True
        return False


def create_token(user_id: int) -> str:
    """Create an authentication token."""
    import secrets
    return secrets.token_hex(32)


def validate_input(data: dict) -> bool:
    """Validate user input."""
    if not data:
        return False
    return True
'''


@pytest.fixture
def sample_javascript_code():
    """Sample JavaScript source code for indexing tests."""
    return '''import express from "express";
import { authMiddleware } from "./auth.js";

const app = express();

function handleRequest(req, res) {
  const userId = req.params.id;
  const user = getUserById(userId);
  res.json(user);
}

async function getUserById(id) {
  return await db.query(id);
}

export { handleRequest };
'''


@pytest.fixture
def mock_git_repo(tmp_path):
    """Create a temporary Git repository for testing."""
    import git

    repo_path = tmp_path / "test-repo"
    repo_path.mkdir()
    repo = git.Repo.init(str(repo_path))

    # Create a sample file
    (repo_path / "app.py").write_text('''
def hello():
    print("Hello, world!")
''')

    # Configure git
    repo.config_writer().set_value("user", "name", "Test User").release()
    repo.config_writer().set_value("user", "email", "test@example.com").release()

    # Add and commit
    repo.index.add(["app.py"])
    repo.index.commit("Initial commit")

    return str(repo_path)
