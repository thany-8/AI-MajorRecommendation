"""Integration tests for the versioned JSON API using Flask's test client.

Gemini is never contacted: most tests run in offline demo mode, and the
non-demo path is exercised with a mocked Gemini client.
"""

import app as app_module
from src import database as storage
from src.recommender import MAX_QUESTIONS
from src.utils import RecommenderError


def _run_to_completion(client, first):
    """Answer follow-up questions until the advisor marks the session done."""
    data = first
    for _ in range(MAX_QUESTIONS + 2):
        if data.get("done"):
            break
        data = client.post("/api/v1/chat", json={"answer": "teams"}).get_json()
    return data


# --------------------------------------------------------------------------- #
# GET / (single-page app shell)
# --------------------------------------------------------------------------- #
def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"MajorMatch" in resp.data
    assert b'id="profile-form"' in resp.data


# --------------------------------------------------------------------------- #
# API documentation (OpenAPI + Swagger UI)
# --------------------------------------------------------------------------- #
def test_openapi_spec_is_served(client):
    resp = client.get("/api/docs/openapi.json")
    assert resp.status_code == 200
    spec = resp.get_json()
    assert spec["info"]["title"] == "MajorMatch API"
    assert spec["openapi"].startswith("3.")
    assert set(spec["paths"]) == {
        "/api/v1/start",
        "/api/v1/chat",
        "/api/v1/feedback",
        "/api/v1/history",
    }


def test_swagger_ui_is_served(client):
    resp = client.get("/api/docs/swagger")
    assert resp.status_code == 200
    assert b"swagger" in resp.data.lower()


# --------------------------------------------------------------------------- #
# POST /api/v1/start
# --------------------------------------------------------------------------- #
def test_start_demo_returns_recommendations_and_session(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    resp = client.post("/api/v1/start", json={"interests": "coding and video games"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["recommendations"]
    assert data["questions_asked"] == 1
    assert data["max_questions"] == MAX_QUESTIONS
    assert "session_id" in data  # persistence enabled -> id handed to client


def test_start_requires_interests_or_hobbies(client):
    resp = client.post("/api/v1/start", json={"subjects": "math"})
    assert resp.status_code == 400
    assert "interests" in resp.get_json()["error"].lower()


def test_start_persists_session_visible_in_history(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    client.post("/api/v1/start", json={"interests": "coding"})
    history = client.get("/api/v1/history").get_json()["sessions"]
    assert len(history) == 1
    assert history[0]["is_demo"] is True


def test_start_real_path_with_mocked_gemini(client, monkeypatch, mock_gemini):
    monkeypatch.setenv("DEMO_MODE", "0")
    mock_gemini()
    resp = client.post("/api/v1/start", json={"interests": "coding"})
    assert resp.status_code == 200
    top = resp.get_json()["recommendations"][0]
    assert top["name"] == "Computer Science"
    assert top["data"]["grounded"] is True  # sanity-checked against the real dataset
    history = client.get("/api/v1/history").get_json()["sessions"]
    assert history[0]["is_demo"] is False


def test_start_recommender_error_returns_502(client, monkeypatch):
    def boom(_form):
        raise RecommenderError("API is down")

    monkeypatch.setattr(app_module, "start_session", boom)
    resp = client.post("/api/v1/start", json={"interests": "x"})
    assert resp.status_code == 502
    assert "API is down" in resp.get_json()["error"]


def test_start_omits_session_id_when_persistence_disabled(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setattr(storage, "_enabled", False)
    data = client.post("/api/v1/start", json={"interests": "x"}).get_json()
    assert "session_id" not in data


# --------------------------------------------------------------------------- #
# POST /api/v1/chat
# --------------------------------------------------------------------------- #
def test_chat_missing_answer_returns_422_envelope(client):
    resp = client.post("/api/v1/chat", json={})
    assert resp.status_code == 422
    body = resp.get_json()
    assert "error" in body
    assert body["details"][0]["loc"] == ["answer"]


def test_chat_without_session_returns_400(client):
    resp = client.post("/api/v1/chat", json={"answer": "hello"})
    assert resp.status_code == 400


def test_chat_empty_answer_returns_400(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    client.post("/api/v1/start", json={"interests": "coding"})
    resp = client.post("/api/v1/chat", json={"answer": "   "})
    assert resp.status_code == 400


def test_chat_recommender_error_returns_502(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    client.post("/api/v1/start", json={"interests": "coding"})

    def boom(_messages, _answer, _asked):
        raise RecommenderError("refine failed")

    monkeypatch.setattr(app_module, "refine_session", boom)
    resp = client.post("/api/v1/chat", json={"answer": "teams"})
    assert resp.status_code == 502


def test_full_flow_completes_and_can_be_reviewed(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    start = client.post(
        "/api/v1/start", json={"interests": "coding", "hobbies": "chess"}
    ).get_json()
    session_id = start["session_id"]

    final = _run_to_completion(client, start)
    assert final["done"] is True

    history = client.get("/api/v1/history").get_json()["sessions"]
    assert history[0]["session_id"] == session_id
    assert history[0]["status"] == "completed"


# --------------------------------------------------------------------------- #
# POST /api/v1/feedback
# --------------------------------------------------------------------------- #
def test_feedback_stored_for_session(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    start = client.post("/api/v1/start", json={"interests": "coding"}).get_json()
    resp = client.post(
        "/api/v1/feedback",
        json={"session_id": start["session_id"], "major": "Computer Science", "helpful": True},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "stored": True}


def test_feedback_missing_session_id_returns_422(client):
    resp = client.post("/api/v1/feedback", json={"helpful": True})
    assert resp.status_code == 422


def test_feedback_missing_helpful_returns_422(client):
    resp = client.post("/api/v1/feedback", json={"session_id": "abc"})
    assert resp.status_code == 422


def test_feedback_unknown_session_returns_404(client):
    resp = client.post("/api/v1/feedback", json={"session_id": "missing", "helpful": False})
    assert resp.status_code == 404


def test_feedback_soft_ok_when_persistence_disabled(client, monkeypatch):
    monkeypatch.setattr(storage, "_enabled", False)
    resp = client.post("/api/v1/feedback", json={"session_id": "whatever", "helpful": True})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "stored": False}


# --------------------------------------------------------------------------- #
# GET /api/v1/history
# --------------------------------------------------------------------------- #
def test_history_empty_for_new_visitor(client):
    resp = client.get("/api/v1/history")
    assert resp.status_code == 200
    assert resp.get_json()["sessions"] == []


# --------------------------------------------------------------------------- #
# Observability: health, tracing, rate limiting, error handling
# --------------------------------------------------------------------------- #
def test_healthz_reports_status_and_context(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert "metrics" in body
    assert "cache" in body
    assert body["dataset"]["loaded"] is True
    assert body["dataset"]["major_count"] > 100
    assert body["rate_limit"]["enabled"] is False  # disabled in tests
    assert "X-Request-ID" in resp.headers


def test_healthz_metrics_count_requests(client):
    client.get("/healthz")
    body = client.get("/healthz").get_json()
    assert body["metrics"]["requests_total"] >= 1


def test_request_id_is_echoed_from_header(client):
    resp = client.get("/healthz", headers={"X-Request-ID": "trace-123"})
    assert resp.headers["X-Request-ID"] == "trace-123"


def test_unknown_api_route_returns_json_404(client):
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    assert resp.get_json()["error"]


def test_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    app_module.limiter.enabled = True
    app_module.limiter.reset()

    saw_429 = False
    for _ in range(60):
        resp = client.post("/api/v1/start", json={"interests": "coding"})
        if resp.status_code == 429:
            saw_429 = True
            assert resp.get_json()["error"]
            break
    assert saw_429, "rate limit never triggered"


def test_unhandled_exception_returns_json_500(client, monkeypatch):
    monkeypatch.setitem(app_module.app.config, "PROPAGATE_EXCEPTIONS", False)

    def boom(_form):
        raise ValueError("kaboom")

    monkeypatch.setattr(app_module, "start_session", boom)
    resp = client.post("/api/v1/start", json={"interests": "coding"})
    assert resp.status_code == 500
    assert resp.get_json()["error"]
    assert client.get("/healthz").get_json()["metrics"].get("errors_total", 0) >= 1
