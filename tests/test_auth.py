"""Tests for accounts, authentication and CSRF protection."""

import pytest

import app as app_module
from src import database as storage


@pytest.fixture
def db(tmp_path):
    """Storage backed by a fresh SQLite database (for direct storage tests)."""
    storage.init_app("sqlite:///" + str(tmp_path / "auth.db"))
    return storage


def _csrf(client):
    return client.get("/api/v1/auth/me").get_json()["csrf_token"]


# --------------------------------------------------------------------------- #
# Storage layer
# --------------------------------------------------------------------------- #
def test_create_account_adopts_guest_history(db):
    anon = db.get_or_create_anonymous("guest-token")
    db.record_start(
        anon["id"], "s1", {"interests": "coding"},
        {"scores": {}, "recommendations": [{"name": "CS", "match": 90, "why": "x"}], "done": True},
        1,
    )
    account, error = db.create_account("g@h.com", "password1", adopt_token="guest-token")
    assert error is None
    assert account["id"] == anon["id"]  # the guest row was upgraded in place
    assert account["is_anonymous"] is False
    assert len(db.list_sessions(account["id"])) == 1


def test_duplicate_email_is_rejected(db):
    db.create_account("dup@example.com", "password1")
    account, error = db.create_account("DUP@example.com", "password2")  # case-insensitive
    assert account is None
    assert error


def test_authenticate_checks_credentials(db):
    db.create_account("z@example.com", "password1")
    assert db.authenticate("z@example.com", "password1") is not None
    assert db.authenticate("z@example.com", "wrong") is None
    assert db.authenticate("missing@example.com", "password1") is None


# --------------------------------------------------------------------------- #
# Auth endpoints
# --------------------------------------------------------------------------- #
def test_me_anonymous_by_default(client):
    body = client.get("/api/v1/auth/me").get_json()
    assert body["authenticated"] is False
    assert body["email"] is None
    assert body["csrf_token"]


def test_register_login_logout_flow(client):
    reg = client.post("/api/v1/auth/register", json={"email": "a@b.com", "password": "password1"})
    assert reg.status_code == 201
    assert reg.get_json()["authenticated"] is True
    assert reg.get_json()["email"] == "a@b.com"

    assert client.get("/api/v1/auth/me").get_json()["authenticated"] is True

    assert client.post("/api/v1/auth/logout", json={}).status_code == 200
    assert client.get("/api/v1/auth/me").get_json()["authenticated"] is False

    login = client.post("/api/v1/auth/login", json={"email": "a@b.com", "password": "password1"})
    assert login.status_code == 200
    assert login.get_json()["email"] == "a@b.com"


def test_register_duplicate_email_returns_409(client):
    payload = {"email": "dup@b.com", "password": "password1"}
    client.post("/api/v1/auth/register", json=payload)
    resp = client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 409


def test_register_weak_password_returns_422(client):
    resp = client.post("/api/v1/auth/register", json={"email": "x@b.com", "password": "short"})
    assert resp.status_code == 422
    assert "8 characters" in resp.get_json()["error"]


def test_register_invalid_email_returns_422(client):
    resp = client.post(
        "/api/v1/auth/register", json={"email": "not-an-email", "password": "password1"}
    )
    assert resp.status_code == 422


def test_login_bad_credentials_returns_401(client):
    client.post("/api/v1/auth/register", json={"email": "u@b.com", "password": "password1"})
    resp = client.post("/api/v1/auth/login", json={"email": "u@b.com", "password": "nope"})
    assert resp.status_code == 401


def test_history_syncs_across_devices(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    # Device 1: a guest starts a session, then registers (adopting that history).
    client.post("/api/v1/start", json={"interests": "coding"})
    assert client.post(
        "/api/v1/auth/register", json={"email": "sync@b.com", "password": "password1"}
    ).status_code == 201
    assert len(client.get("/api/v1/history").get_json()["sessions"]) == 1

    # Device 2: a fresh client signs in and sees the same history.
    device2 = app_module.app.test_client()
    assert device2.post(
        "/api/v1/auth/login", json={"email": "sync@b.com", "password": "password1"}
    ).status_code == 200
    assert len(device2.get("/api/v1/history").get_json()["sessions"]) == 1


# --------------------------------------------------------------------------- #
# CSRF protection
# --------------------------------------------------------------------------- #
def test_csrf_blocks_write_without_token(client):
    app_module.app.config["CSRF_ENABLED"] = True
    resp = client.post("/api/v1/start", json={"interests": "coding"})
    assert resp.status_code == 403
    assert "CSRF" in resp.get_json()["error"]


def test_csrf_allows_write_with_token(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    app_module.app.config["CSRF_ENABLED"] = True
    token = _csrf(client)
    resp = client.post(
        "/api/v1/start", json={"interests": "coding"}, headers={"X-CSRFToken": token}
    )
    assert resp.status_code == 200


def test_csrf_does_not_block_safe_reads(client):
    app_module.app.config["CSRF_ENABLED"] = True
    assert client.get("/api/v1/history").status_code == 200
