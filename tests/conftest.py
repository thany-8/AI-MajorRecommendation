"""Shared pytest fixtures for the MajorMatch test-suite.

The environment is configured **before** ``app`` / ``recommender`` are imported
so that app.py's import-time work (loading ``.env``, initialising the database,
requiring a secret key) is hermetic: it never points at the real database and
never needs a real Gemini API key. Every Gemini call is mocked, and an autouse
safety-net makes any un-mocked API access fail loudly instead of hitting the
network.
"""

import json
import os
import tempfile
import unittest.mock as mock

# --- Configure the environment before importing the application ---------------
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")
# Default to the real (mocked) engine, not demo mode; individual tests opt in.
os.environ["DEMO_MODE"] = "0"
os.environ["AUTO_DEMO_FALLBACK"] = "0"
# Keep test output quiet (INFO request logs are suppressed; warnings/errors show).
os.environ.setdefault("LOG_LEVEL", "WARNING")
# Point persistence at a throwaway SQLite file so importing app.py never touches
# the real instance/ database. Per-test isolation is handled by the `client`
# fixture below.
_BOOT_DIR = tempfile.mkdtemp(prefix="majormatch-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_BOOT_DIR, "boot.db")

import pytest  # noqa: E402

import app as app_module  # noqa: E402
from src import (  # noqa: E402
    cache,
    dataset,
    observability,
    recommender,  # noqa: E402
)
from src import database as storage  # noqa: E402

# A representative, well-formed Gemini payload used by most mocked tests.
DEFAULT_PAYLOAD = {
    "scores": {
        "Analytical": 80,
        "Creative": 40,
        "Social": 55,
        "Technical": 88,
        "Leadership": 50,
    },
    "recommendations": [
        {"name": "Computer Science", "match": 92, "why": "You love building software."},
        {"name": "Data Science", "match": 85, "why": "You enjoy analysing data."},
    ],
    "message": "Great matches so far!",
    "question": "Do you prefer solo or team work?",
}


class _FakeResponse:
    """Mimics the object returned by ``client.models.generate_content``."""

    def __init__(self, text):
        self.text = text


def make_fake_client(payload=None, *, error=None, text=None):
    """Build a stand-in Gemini client.

    * ``error``   – raise this exception from ``generate_content``.
    * ``text``    – return this raw string as the response text.
    * ``payload`` – otherwise return ``json.dumps(payload)`` (defaults to
      :data:`DEFAULT_PAYLOAD`).
    """
    client = mock.MagicMock(name="FakeGeminiClient")

    def _generate(*_args, **_kwargs):
        if error is not None:
            raise error
        if text is not None:
            return _FakeResponse(text)
        body = DEFAULT_PAYLOAD if payload is None else payload
        return _FakeResponse(json.dumps(body))

    client.models.generate_content.side_effect = _generate
    return client


@pytest.fixture(autouse=True)
def _no_real_api(monkeypatch):
    """Fail fast if any test reaches the real Gemini client without mocking it."""

    def _boom():
        raise AssertionError(
            "recommender.get_client() was called without a mock — a test would "
            "have hit the real Gemini API."
        )

    monkeypatch.setattr(recommender, "get_client", _boom)


@pytest.fixture(autouse=True)
def _reset_shared_state():
    """Isolate module-level singletons (cache, metrics, limiter) between tests."""
    cache.profile_cache.clear()
    cache.profile_cache.enabled = True
    dataset.major_dataset.reset_counts()
    dataset.major_dataset.enabled = True
    observability.metrics.reset()
    app_module.limiter.enabled = False
    app_module.limiter.reset()
    yield


@pytest.fixture
def mock_gemini(monkeypatch):
    """Return an installer that swaps in a fake Gemini client.

    Usage::

        def test_x(mock_gemini):
            mock_gemini()                    # default canned JSON
            mock_gemini(payload={...})       # custom JSON
            mock_gemini(error=some_exc)      # raise from the API
            mock_gemini(text="not json")     # raw (unparseable) text
    """

    def _install(payload=None, *, error=None, text=None):
        client = make_fake_client(payload, error=error, text=text)
        monkeypatch.setattr(recommender, "get_client", lambda: client)
        return client

    return _install


@pytest.fixture
def client(tmp_path):
    """A Flask test client backed by a fresh, isolated SQLite database."""
    storage.init_app("sqlite:///" + str(tmp_path / "test.db"))
    app_module._SESSIONS.clear()
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as test_client:
        yield test_client
