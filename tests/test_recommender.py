"""Unit tests for :mod:`src.recommender` (Gemini calls are mocked)."""

import json

import pytest
from google.genai import errors as genai_errors

from src import recommender as rec
from src.utils import CATEGORIES, CapacityError, RecommenderError


def _capacity_error(message="RESOURCE_EXHAUSTED rate limit"):
    return genai_errors.APIError(
        429, {"error": {"message": message, "status": "RESOURCE_EXHAUSTED"}}
    )


# --------------------------------------------------------------------------- #
# build_profile_summary
# --------------------------------------------------------------------------- #
def test_build_profile_summary_empty():
    assert rec.build_profile_summary({}) == "The student did not provide many details yet."


def test_build_profile_summary_includes_and_strips_fields():
    summary = rec.build_profile_summary(
        {"interests": "  coding  ", "goals": "make games", "hobbies": ""}
    )
    assert "- Interests: coding" in summary
    assert "- Career goals or dreams: make games" in summary
    assert "Hobbies" not in summary  # blank fields are omitted


# --------------------------------------------------------------------------- #
# _normalise
# --------------------------------------------------------------------------- #
def test_normalise_clamps_scores_and_fills_all_traits():
    out = rec._normalise({"scores": {"Analytical": 150, "Creative": -5, "Technical": "oops"}})
    assert set(out["scores"]) == set(CATEGORIES)
    assert out["scores"]["Analytical"] == 100
    assert out["scores"]["Creative"] == 0
    assert out["scores"]["Technical"] == 0  # non-numeric -> 0


def test_normalise_recommendations_filter_clamp_and_sort():
    out = rec._normalise(
        {
            "recommendations": [
                {"name": "CS", "match": 120, "why": "  good  "},
                {"name": "", "match": 99, "why": "no name"},   # dropped
                "not-a-dict",                                    # dropped
                {"name": "Bio", "match": "bad", "why": "x"},     # match -> 0
            ]
        }
    )
    names = [r["name"] for r in out["recommendations"]]
    assert names == ["CS", "Bio"]              # invalid entries removed, sorted desc
    assert out["recommendations"][0]["match"] == 100
    assert out["recommendations"][0]["why"] == "good"


def test_normalise_defaults_for_missing_keys():
    out = rec._normalise({})
    assert out["scores"] == {c: 0 for c in CATEGORIES}
    assert out["recommendations"] == []
    assert out["message"] == ""
    assert out["question"] == ""


def test_normalise_coerces_message_and_question_to_str():
    out = rec._normalise({"message": "  hi  ", "question": 42})
    assert out["message"] == "hi"
    assert out["question"] == "42"


# --------------------------------------------------------------------------- #
# _to_gemini
# --------------------------------------------------------------------------- #
def test_to_gemini_maps_roles_and_joins_system():
    system, contents = rec._to_gemini(
        [
            {"role": "system", "content": "SYS1"},
            {"role": "system", "content": "SYS2"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "model", "content": "again"},
        ]
    )
    assert system == "SYS1\n\nSYS2"
    assert [c.role for c in contents] == ["user", "model", "model"]
    assert contents[0].parts[0].text == "hello"


def test_to_gemini_without_system_returns_none():
    system, contents = rec._to_gemini([{"role": "user", "content": "x"}])
    assert system is None
    assert len(contents) == 1


# --------------------------------------------------------------------------- #
# _is_capacity_error
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "message",
    [
        "RESOURCE_EXHAUSTED",
        "rate limit reached",
        "quota exceeded",
        "429 too many requests",
        "503 service unavailable",
        "the model is overloaded",
    ],
)
def test_is_capacity_error_detected_by_text(message):
    assert rec._is_capacity_error(Exception(message)) is True


def test_is_capacity_error_detected_by_code():
    err = Exception("mystery")
    err.code = 429
    assert rec._is_capacity_error(err) is True

    err2 = Exception("mystery")
    err2.status_code = 503
    assert rec._is_capacity_error(err2) is True


def test_is_capacity_error_false_for_generic():
    assert rec._is_capacity_error(Exception("bad request: invalid argument")) is False


# --------------------------------------------------------------------------- #
# env toggles
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value,expected",
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("", False),
        ("nope", False),
    ],
)
def test_demo_enabled(monkeypatch, value, expected):
    monkeypatch.setenv("DEMO_MODE", value)
    assert rec._demo_enabled() is expected


def test_auto_demo_fallback_defaults_on(monkeypatch):
    monkeypatch.delenv("AUTO_DEMO_FALLBACK", raising=False)
    assert rec._auto_demo_fallback_enabled() is True


def test_auto_demo_fallback_can_be_disabled(monkeypatch):
    monkeypatch.setenv("AUTO_DEMO_FALLBACK", "0")
    assert rec._auto_demo_fallback_enabled() is False


# --------------------------------------------------------------------------- #
# _seed_demo_from_messages
# --------------------------------------------------------------------------- #
def test_seed_demo_from_messages_builds_demo_state():
    demo_messages = rec._seed_demo_from_messages(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "I like coding and math"},
            {"role": "assistant", "content": "ok"},
        ]
    )
    assert demo_messages and demo_messages[0]["role"] == "demo"


# --------------------------------------------------------------------------- #
# _chat_json
# --------------------------------------------------------------------------- #
def test_chat_json_parses_response(mock_gemini):
    mock_gemini({"scores": {}, "recommendations": [], "message": "m", "question": "q"})
    out = rec._chat_json([{"role": "user", "content": "hi"}])
    assert out["message"] == "m"


def test_chat_json_raises_capacity_error(mock_gemini):
    mock_gemini(error=_capacity_error())
    with pytest.raises(CapacityError):
        rec._chat_json([{"role": "user", "content": "hi"}])


def test_chat_json_wraps_other_api_errors(mock_gemini):
    mock_gemini(
        error=genai_errors.APIError(
            400, {"error": {"message": "invalid argument", "status": "INVALID_ARGUMENT"}}
        )
    )
    with pytest.raises(RecommenderError) as excinfo:
        rec._chat_json([{"role": "user", "content": "hi"}])
    assert not isinstance(excinfo.value, CapacityError)


def test_chat_json_raises_on_unparseable_text(mock_gemini):
    mock_gemini(text="this is not json")
    with pytest.raises(RecommenderError):
        rec._chat_json([{"role": "user", "content": "hi"}])


# --------------------------------------------------------------------------- #
# start_session
# --------------------------------------------------------------------------- #
def test_start_session_demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    result, messages = rec.start_session({"interests": "coding"})
    assert messages[0]["role"] == "demo"
    assert set(result["scores"]) == set(CATEGORIES)
    assert result["recommendations"]


def test_start_session_real_path(monkeypatch, mock_gemini):
    monkeypatch.setenv("DEMO_MODE", "0")
    mock_gemini()
    result, messages = rec.start_session({"interests": "coding"})
    assert result["recommendations"][0]["name"] == "Computer Science"
    roles = [m["role"] for m in messages]
    assert roles[0] == "system" and roles[1] == "user" and roles[-1] == "assistant"
    assert json.loads(messages[-1]["content"])  # assistant content is stored JSON


def test_start_session_capacity_falls_back_to_demo(monkeypatch, mock_gemini):
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setenv("AUTO_DEMO_FALLBACK", "1")
    mock_gemini(error=_capacity_error("quota exhausted"))
    result, messages = rec.start_session({"interests": "coding"})
    assert messages[0]["role"] == "demo"
    assert "demo mode" in result["message"].lower()


def test_start_session_capacity_without_fallback_raises(monkeypatch, mock_gemini):
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setenv("AUTO_DEMO_FALLBACK", "0")
    mock_gemini(error=_capacity_error("quota exhausted"))
    with pytest.raises(CapacityError):
        rec.start_session({"interests": "coding"})


# --------------------------------------------------------------------------- #
# refine_session
# --------------------------------------------------------------------------- #
def test_refine_session_demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    _, messages = rec.start_session({"interests": "coding"})
    result, messages2 = rec.refine_session(messages, "I like teams", questions_asked=1)
    assert set(result["scores"]) == set(CATEGORIES)
    assert messages2[0]["role"] == "demo"


def test_refine_session_demo_detected_from_messages(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    _, messages = rec.start_session({"interests": "coding"})
    # Even with demo mode off, a demo-tagged conversation stays in demo.
    monkeypatch.setenv("DEMO_MODE", "0")
    _, messages2 = rec.refine_session(messages, "teams", questions_asked=1)
    assert messages2[0]["role"] == "demo"


def test_refine_session_real_path(monkeypatch, mock_gemini):
    monkeypatch.setenv("DEMO_MODE", "0")
    mock_gemini()
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "profile"},
        {"role": "assistant", "content": json.dumps({"x": 1})},
    ]
    result, messages2 = rec.refine_session(messages, "I like teams", questions_asked=1)
    assert result["recommendations"][0]["name"] == "Computer Science"
    assert messages2[-1]["role"] == "assistant"
    assert any("I like teams" in m["content"] for m in messages2 if m["role"] == "user")


def test_refine_session_finalize_forces_empty_question(monkeypatch, mock_gemini):
    monkeypatch.setenv("DEMO_MODE", "0")
    mock_gemini()  # default payload has a non-empty question
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "p"}]
    result, _ = rec.refine_session(messages, "answer", questions_asked=rec.MAX_QUESTIONS - 1)
    assert result["question"] == ""


def test_refine_session_capacity_falls_back_to_demo(monkeypatch, mock_gemini):
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setenv("AUTO_DEMO_FALLBACK", "1")
    mock_gemini(error=_capacity_error("overloaded"))
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "p"}]
    result, messages2 = rec.refine_session(messages, "answer", questions_asked=1)
    assert "demo mode" in result["message"].lower()
    assert messages2[0]["role"] == "demo"


# --------------------------------------------------------------------------- #
# Caching of the initial recommendation
# --------------------------------------------------------------------------- #
def test_start_session_caches_and_skips_second_gemini_call(monkeypatch, mock_gemini):
    monkeypatch.setenv("DEMO_MODE", "0")
    client = mock_gemini()
    first, _ = rec.start_session({"interests": "coding"})
    # A normalised-identical profile should be served from cache.
    second, _ = rec.start_session({"interests": "  Coding "})
    assert first["recommendations"] == second["recommendations"]
    assert client.models.generate_content.call_count == 1


def test_start_session_capacity_fallback_is_not_cached(monkeypatch, mock_gemini):
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setenv("AUTO_DEMO_FALLBACK", "1")
    client = mock_gemini(error=_capacity_error("quota"))
    rec.start_session({"interests": "coding"})
    rec.start_session({"interests": "coding"})
    # Demo fallbacks are never cached, so Gemini is retried on the next request.
    assert client.models.generate_content.call_count == 2


def test_start_session_grounds_recommendations_with_real_data(monkeypatch, mock_gemini):
    monkeypatch.setenv("DEMO_MODE", "0")
    mock_gemini()
    result, _ = rec.start_session({"interests": "coding"})
    top = result["recommendations"][0]
    assert top["name"] == "Computer Science"
    assert top["data"]["grounded"] is True
    assert top["data"]["median_earnings"] > 0
