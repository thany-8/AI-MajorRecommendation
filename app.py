"""JSON API + single-page front-end for the AI Major Recommendation tool.

The browser loads a single-page app from ``GET /`` and then talks to a
versioned JSON API under ``/api/v1``. The API is described by an OpenAPI 3
specification generated from the Pydantic models in :mod:`src.schemas` and is
browsable via Swagger UI:

* Swagger UI:   ``/api/docs/swagger``
* OpenAPI spec: ``/api/docs/openapi.json``

Endpoints (all under ``/api/v1``):
    POST /start     - begin a session from the profile form.
    POST /chat      - refine the recommendation with the student's answer.
    POST /feedback  - record "was this major helpful?" feedback.
    GET  /history   - list the returning visitor's past sessions.

Operational:
    GET  /healthz   - liveness probe with metrics, cache and config snapshot.
"""

import os
import secrets
import uuid

from dotenv import load_dotenv
from flask import jsonify, make_response, render_template, request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_openapi3 import APIBlueprint, Info, OpenAPI, Tag
from pydantic import ValidationError

from src import database as storage
from src import observability, schemas
from src.cache import profile_cache
from src.dataset import major_dataset
from src.recommender import MAX_QUESTIONS, refine_session, start_session
from src.utils import RecommenderError

load_dotenv()

# Structured logging + optional Sentry error monitoring, configured before the
# app and its extensions emit any log lines.
observability.configure_logging()
observability.init_error_monitoring()


def _error_message(err: dict) -> str:
    """Extract a clean, user-facing message from a Pydantic error entry."""
    ctx = err.get("ctx") or {}
    if "error" in ctx:  # our custom ValueError validators put the message here
        return str(ctx["error"])
    return err.get("msg", "Invalid request.")


def _on_validation_error(e: ValidationError):
    """Render request-validation failures as a consistent JSON error envelope.

    flask-openapi3 invokes this when an incoming request fails Pydantic
    validation. The first problem is surfaced as ``error`` and the full list as
    ``details`` (see :class:`src.schemas.ErrorResponse`).
    """
    details = [
        {"loc": list(err.get("loc", ())), "msg": _error_message(err), "type": err.get("type", "")}
        for err in e.errors()
    ]
    message = details[0]["msg"] if details else "Invalid request."
    response = make_response(jsonify({"error": message, "details": details}))
    response.status_code = 422
    return response


info = Info(
    title="MajorMatch API",
    version="1.0.0",
    description=(
        "Recommends the university majors a student is most likely to enjoy, then "
        "refines them through a short chat-style Q&A. Recommendations are guidance, "
        "not a guarantee."
    ),
)

app = OpenAPI(
    __name__,
    info=info,
    doc_prefix="/api/docs",
    validation_error_status=422,
    validation_error_model=schemas.ErrorResponse,
    validation_error_callback=_on_validation_error,
)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

if not app.secret_key:
    raise RuntimeError(
        "FLASK_SECRET_KEY is missing. Add it to your .env file."
    )

# Harden the session cookie and enable CSRF protection on state-changing API
# requests (disable in tests via CSRF_ENABLED=0).
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["CSRF_ENABLED"] = os.getenv("CSRF_ENABLED", "1").strip().lower() in (
    "1", "true", "yes", "on",
)

# Initialise persistence for user profiles, sessions and feedback. Uses
# DATABASE_URL when set (e.g. a Postgres URL), otherwise a local SQLite file in
# the Flask instance folder. If this fails the app still runs; persistence is
# simply disabled (see src/database.py).
os.makedirs(app.instance_path, exist_ok=True)
_DEFAULT_DB_URL = "sqlite:///" + os.path.join(app.instance_path, "majormatch.db")
storage.init_app(os.getenv("DATABASE_URL") or _DEFAULT_DB_URL)


def _ratelimit_enabled() -> bool:
    """Whether rate limiting is active (disable in tests via RATELIMIT_ENABLED=0)."""
    return os.getenv("RATELIMIT_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")


def _rate_limit_key() -> str:
    """Rate-limit per signed-in account, else per anonymous visitor, else IP."""
    account_id = session.get("user_id")
    if account_id:
        return f"user:{account_id}"
    anon = session.get("uid")
    return f"anon:{anon}" if anon else get_remote_address()


# Per-user/session rate limiting. In-memory storage is fine for a single worker;
# point RATELIMIT_STORAGE_URI at Redis for a multi-process deployment. Limits are
# applied per API operation below (the SPA, docs and /healthz are unlimited).
_START_LIMIT = os.getenv("RATELIMIT_START", "15 per minute")
_CHAT_LIMIT = os.getenv("RATELIMIT_CHAT", "40 per minute")
_WRITE_LIMIT = os.getenv("RATELIMIT_DEFAULT", "60 per minute")
_AUTH_LIMIT = os.getenv("RATELIMIT_AUTH", "10 per minute")

limiter = Limiter(
    key_func=_rate_limit_key,
    app=app,
    storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
    headers_enabled=True,
)
limiter.enabled = _ratelimit_enabled()

# Request-lifecycle logging, metrics and JSON error handlers.
observability.install(app)

# Server-side conversation store: session id -> {messages, questions_asked}.
# An in-memory dict is sufficient for a single-process app and keeps the large
# model message history out of the (4 KB) signed session cookie.
_SESSIONS: dict[str, dict] = {}

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _csrf_token() -> str:
    """Return the per-session CSRF token, creating one on first use."""
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.before_request
def _csrf_protect():
    """Double-submit CSRF check: state-changing /api requests must echo the
    session CSRF token in the ``X-CSRFToken`` header."""
    _csrf_token()  # ensure a token exists for the page/meta tag
    if not app.config.get("CSRF_ENABLED", True):
        return None
    if request.method in _SAFE_METHODS or not request.path.startswith("/api/"):
        return None
    sent = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")
    if not sent or not secrets.compare_digest(sent, session.get("csrf_token", "")):
        return jsonify({"error": "CSRF token missing or invalid. Reload the page."}), 403
    return None


def _current_user_id(create: bool = False) -> int | None:
    """Resolve the current user id: signed-in account, else anonymous visitor.

    With ``create=True`` an anonymous cookie/identity is minted if none exists
    (used on writes); reads pass ``create=False`` so they never create rows.
    """
    account_id = session.get("user_id")
    if account_id:
        return account_id
    token = session.get("uid")
    if not token:
        if not create:
            return None
        token = storage.new_user_token()
        session["uid"] = token
        session.permanent = True
    user = storage.get_or_create_anonymous(token)
    return user["id"] if user else None


def _auth_payload(account: dict | None) -> dict:
    """Build the authentication-state response, including the CSRF token."""
    return {
        "authenticated": bool(account and not account.get("is_anonymous")),
        "email": account.get("email") if account else None,
        "csrf_token": _csrf_token(),
    }


def _is_demo(messages: list[dict]) -> bool:
    """Return True when the conversation was produced by offline demo mode."""
    return bool(messages) and messages[0].get("role") == "demo"


@app.route("/")
def index():
    """Render the single-page app shell (not part of the JSON API)."""
    return render_template(
        "index.html", max_questions=MAX_QUESTIONS, csrf_token=_csrf_token()
    )


@app.route("/healthz")
def healthz():
    """Liveness/observability probe: status, metrics, cache and config."""
    return jsonify(
        {
            "status": "ok",
            "uptime_seconds": observability.metrics.uptime_seconds(),
            "metrics": observability.metrics.snapshot(),
            "cache": profile_cache.stats(),
            "dataset": major_dataset.stats(),
            "rate_limit": {"enabled": limiter.enabled},
            "persistence": storage.is_enabled(),
        }
    )


# Versioned JSON API. All operations are grouped under one tag in the docs.
_TAG = Tag(name="MajorMatch", description="Recommend and refine university majors.")
api = APIBlueprint("api_v1", __name__, url_prefix="/api/v1", abp_tags=[_TAG])


@api.post(
    "/start",
    summary="Start a recommendation session",
    description=(
        "Assess a student's profile and return initial trait scores, ranked major "
        "recommendations, a friendly message and the first follow-up question."
    ),
    responses={
        200: schemas.RecommendationResult,
        400: schemas.ErrorResponse,
        422: schemas.ErrorResponse,
        429: schemas.ErrorResponse,
        502: schemas.ErrorResponse,
    },
)
@limiter.limit(_START_LIMIT)
def api_start(body: schemas.ProfileForm):
    """Begin a new recommendation session from the submitted profile form."""
    if not (body.interests.strip() or body.hobbies.strip()):
        return jsonify(
            {"error": "Tell us at least your interests or hobbies to get started."}
        ), 400

    form = body.model_dump()
    try:
        result, messages = start_session(form)
    except RecommenderError as exc:
        return jsonify({"error": str(exc)}), 502

    sid = uuid.uuid4().hex
    _SESSIONS[sid] = {"messages": messages, "questions_asked": 1}
    session["sid"] = sid

    result["questions_asked"] = 1
    result["max_questions"] = MAX_QUESTIONS
    result["done"] = not result["question"]

    # Persist the profile and the new session for this returning visitor. When
    # persistence is enabled we hand the session id to the browser so it can
    # later attach "was this helpful?" feedback to this exact session.
    storage.record_start(
        _current_user_id(create=True), sid, form, result,
        questions_asked=1, is_demo=_is_demo(messages),
    )
    if storage.is_enabled():
        result["session_id"] = sid

    return jsonify(result)


@api.post(
    "/chat",
    summary="Refine the recommendation",
    description=(
        "Continue the current session with the student's latest answer and return "
        "updated scores, recommendations and the next follow-up question."
    ),
    responses={
        200: schemas.RecommendationResult,
        400: schemas.ErrorResponse,
        422: schemas.ErrorResponse,
        429: schemas.ErrorResponse,
        502: schemas.ErrorResponse,
    },
)
@limiter.limit(_CHAT_LIMIT)
def api_chat(body: schemas.ChatRequest):
    """Refine the recommendation using the student's latest answer."""
    sid = session.get("sid")
    state = _SESSIONS.get(sid) if sid else None
    if not state:
        return jsonify({"error": "Your session expired. Please start again."}), 400

    answer = body.answer.strip()
    if not answer:
        return jsonify({"error": "Please type an answer first."}), 400

    try:
        result, messages = refine_session(
            state["messages"], answer, state["questions_asked"]
        )
    except RecommenderError as exc:
        return jsonify({"error": str(exc)}), 502

    state["messages"] = messages
    state["questions_asked"] += 1

    result["questions_asked"] = state["questions_asked"]
    result["max_questions"] = MAX_QUESTIONS
    result["done"] = (not result["question"]) or state["questions_asked"] >= MAX_QUESTIONS

    # Update the stored session with the refined scores/recommendations.
    storage.record_refine(sid, result, state["questions_asked"], result["done"])
    if storage.is_enabled():
        result["session_id"] = sid

    if result["done"]:
        # Free the stored conversation once the session is complete.
        _SESSIONS.pop(sid, None)
        session.pop("sid", None)

    return jsonify(result)


@api.post(
    "/feedback",
    summary="Submit feedback",
    description='Record a student\'s "was this major helpful?" answer for a session.',
    responses={
        200: schemas.FeedbackResponse,
        400: schemas.ErrorResponse,
        404: schemas.ErrorResponse,
        422: schemas.ErrorResponse,
        429: schemas.ErrorResponse,
    },
)
@limiter.limit(_WRITE_LIMIT)
def api_feedback(body: schemas.FeedbackRequest):
    """Record a student's feedback for a recommendation session."""
    session_id = body.session_id.strip()
    if not session_id:
        return jsonify({"error": "Missing session_id."}), 400

    major = (body.major or "").strip() or None
    comment = (body.comment or "").strip() or None

    if not storage.is_enabled():
        # Persistence is off; accept without storing so the UI stays friendly.
        return jsonify({"ok": True, "stored": False})

    saved = storage.record_feedback(session_id, major, bool(body.helpful), comment)
    if not saved:
        return jsonify({"error": "We couldn't find that session."}), 404
    return jsonify({"ok": True, "stored": True})


@api.get(
    "/history",
    summary="List past sessions",
    description="Return the returning visitor's most recent recommendation sessions.",
    responses={200: schemas.HistoryResponse, 429: schemas.ErrorResponse},
)
@limiter.limit(_WRITE_LIMIT)
def api_history():
    """Return the current user's most recent recommendation sessions."""
    return jsonify({"sessions": storage.list_sessions(_current_user_id())})


# --- Accounts & authentication --------------------------------------------- #
_AUTH_TAG = Tag(name="Auth", description="Accounts and sessions (email + password).")


@api.get(
    "/auth/me",
    tags=[_AUTH_TAG],
    summary="Current authentication state",
    description="Return whether an account is signed in, plus the CSRF token to "
                "send as the X-CSRFToken header on write requests.",
    responses={200: schemas.UserResponse},
)
def api_me():
    """Return the current authentication state and CSRF token."""
    account_id = session.get("user_id")
    account = storage.get_user(account_id) if account_id else None
    return jsonify(_auth_payload(account))


@api.post(
    "/auth/register",
    tags=[_AUTH_TAG],
    summary="Create an account",
    description="Register with email + password. Any recommendations made as a "
                "guest in this browser are adopted into the new account.",
    responses={
        201: schemas.UserResponse,
        409: schemas.ErrorResponse,
        422: schemas.ErrorResponse,
        429: schemas.ErrorResponse,
    },
)
@limiter.limit(_AUTH_LIMIT)
def api_register(body: schemas.RegisterRequest):
    """Create a new account, adopting the current guest's history."""
    account, error = storage.create_account(
        body.email, body.password, adopt_token=session.get("uid")
    )
    if error:
        return jsonify({"error": error}), 409
    session["user_id"] = account["id"]
    session.permanent = True
    return jsonify(_auth_payload(account)), 201


@api.post(
    "/auth/login",
    tags=[_AUTH_TAG],
    summary="Sign in",
    description="Sign in to an existing account. History then syncs across devices.",
    responses={
        200: schemas.UserResponse,
        401: schemas.ErrorResponse,
        422: schemas.ErrorResponse,
        429: schemas.ErrorResponse,
    },
)
@limiter.limit(_AUTH_LIMIT)
def api_login(body: schemas.LoginRequest):
    """Authenticate and start a signed-in session."""
    account = storage.authenticate(body.email, body.password)
    if not account:
        return jsonify({"error": "Invalid email or password."}), 401
    session["user_id"] = account["id"]
    session.permanent = True
    return jsonify(_auth_payload(account))


@api.post(
    "/auth/logout",
    tags=[_AUTH_TAG],
    summary="Sign out",
    description="End the signed-in session (guest browsing continues).",
    responses={200: schemas.UserResponse},
)
def api_logout():
    """Clear the signed-in account from the session."""
    session.pop("user_id", None)
    return jsonify(_auth_payload(None))


app.register_api(api)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)

