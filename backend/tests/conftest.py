"""Shared fixtures. Every test starts against an empty in-memory database."""

from __future__ import annotations

import os

os.environ.setdefault("READIT_PERSIST", "0")
os.environ.setdefault("READIT_SIMULATION", "0")
os.environ.setdefault("READIT_SECRET_KEY", "test-secret")

import shutil  # noqa: E402
import tempfile  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import db, reset_db  # noqa: E402
from app.llm import router as llm_router  # noqa: E402
from app.services import (  # noqa: E402
    generation_service,
    subreddit_service,
    user_service,
    vision_service,
)

settings.persist = False
settings.simulation_enabled = False
db.snapshot_path = None

# Never let a test write into the real media library.
_TEST_MEDIA_DIR = tempfile.mkdtemp(prefix="readit-test-media-")
settings.media_dir = _TEST_MEDIA_DIR


def pytest_sessionfinish(session, exitstatus):  # noqa: ANN001, ARG001
    shutil.rmtree(_TEST_MEDIA_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_world():
    """Fresh database per test, and no asyncio primitives bound to a dead loop."""
    reset_db()
    generation_service.reset_locks()
    vision_service.reset_locks()
    llm_router.reset_semaphore()
    yield
    reset_db()


@pytest.fixture
def client():
    """TestClient without the lifespan, so tests control their own world."""
    from app.main import create_app

    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    with TestClient(app) as test_client:
        yield test_client


import contextlib  # noqa: E402


@contextlib.asynccontextmanager
async def _noop_lifespan(app):  # noqa: ANN001
    yield


@pytest.fixture
def board():
    return subreddit_service.create(
        "testboard",
        title="Test Board",
        description="A board used by the test suite.",
        topics=["testing", "assertions"],
    )


@pytest.fixture
def person():
    return user_service.register("person@example.com", "hunter22", "realperson")


@pytest.fixture
def guest():
    return user_service.create_guest("tester")


@pytest.fixture
def admin():
    user = user_service.register(settings.admin_email, "adminpass", "readit_admin")
    db.collection("users").update(user["_id"], {"$set": {"is_admin": True}})
    return db.collection("users").get(user["_id"])


@pytest.fixture
def auth(client):
    """Return a helper that produces auth headers for a given user document."""

    def _auth(user: dict) -> dict[str, str]:
        token = user_service.start_session(user["_id"])
        return {"Authorization": f"Bearer {token}"}

    return _auth
