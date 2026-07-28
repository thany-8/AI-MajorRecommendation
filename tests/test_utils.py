"""Unit tests for :mod:`src.utils`."""

import pytest

from src import utils
from src.utils import (
    CATEGORIES,
    COMMON_MAJORS,
    DEFAULT_MODEL,
    CapacityError,
    RecommenderError,
    get_api_key,
    get_client,
    get_model,
)


def test_error_hierarchy():
    assert issubclass(RecommenderError, RuntimeError)
    assert issubclass(CapacityError, RecommenderError)


def test_constants_are_sane():
    assert len(CATEGORIES) == 5
    assert "Analytical" in CATEGORIES
    assert "Computer Science" in COMMON_MAJORS
    assert DEFAULT_MODEL.startswith("gemini")


def test_get_api_key_prefers_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "goog-key")
    assert get_api_key() == "gem-key"


def test_get_api_key_falls_back_to_google(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "goog-key")
    assert get_api_key() == "goog-key"


def test_get_api_key_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert get_api_key() is None


def test_get_model_default(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert get_model() == DEFAULT_MODEL


def test_get_model_override(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-custom")
    assert get_model() == "gemini-custom"


def test_get_client_requires_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(utils, "_client", None)
    with pytest.raises(RecommenderError, match="GEMINI_API_KEY"):
        get_client()


def test_get_client_is_cached(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    monkeypatch.setattr(utils, "_client", None)

    created = []

    class FakeClient:
        def __init__(self, api_key=None):
            created.append(api_key)
            self.api_key = api_key

    monkeypatch.setattr(utils.genai, "Client", FakeClient)

    first = get_client()
    second = get_client()

    assert first is second           # cached, not rebuilt
    assert created == ["abc"]         # constructed exactly once
    assert first.api_key == "abc"
