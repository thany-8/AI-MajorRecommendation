"""Persistence layer for user profiles, sessions and feedback.

This module stores three things so the app can remember students between
visits and learn from them:

* **User profiles** – the interests/hobbies/strengths form a student submits.
* **Recommendation sessions** – the ranked majors, trait scores and message
  produced for each visit, updated as the chat refines them.
* **Feedback** – a student's "was this major helpful?" answer for a session.

It is deliberately **framework-agnostic** (no Flask imports) and backed by
SQLAlchemy, so the very same code runs on **SQLite** (the zero-config default,
great for local use) or **PostgreSQL** (set ``DATABASE_URL``) with no changes.

Every public helper is *best-effort*: persistence must never break the core
recommendation experience, so write failures are logged and swallowed. Call
:func:`init_app` once at start-up; if it fails (bad URL, missing driver, server
down) the module simply reports :func:`is_enabled` as ``False`` and every helper
becomes a safe no-op.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import uuid
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
    text,
)
from sqlalchemy import (
    inspect as sa_inspect,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)
from sqlalchemy.types import JSON
from werkzeug.security import check_password_hash, generate_password_hash

logger = logging.getLogger(__name__)

# Default on-disk SQLite database (relative to the current working directory).
# app.py overrides this with a path inside the Flask instance folder.
DEFAULT_DATABASE_URL = "sqlite:///majormatch.db"

# A constant hash compared against when a login email is unknown, so that
# authentication takes a similar amount of time whether or not the account
# exists (mitigates user-enumeration via timing).
_DUMMY_PASSWORD_HASH = generate_password_hash("majormatch-dummy", method="pbkdf2:sha256")

# Module-level engine/session factory, configured by init_app().
_engine = None
_Session: sessionmaker | None = None
_enabled = False


def _utcnow() -> _dt.datetime:
    """Return a timezone-aware UTC timestamp."""
    return _dt.datetime.now(_dt.timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class User(Base):
    """A visitor.

    Anonymous visitors are identified by an opaque cookie ``token``. When a
    visitor registers, ``email`` and ``password_hash`` are set on their row (an
    existing anonymous row can be upgraded in place, so guest history carries
    over) and they can then sign in from any device.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    profiles: Mapped[list["Profile"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["RecommendationSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Profile(Base):
    """A snapshot of the profile form a student submitted."""

    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    interests: Mapped[str | None] = mapped_column(Text, default="")
    hobbies: Mapped[str | None] = mapped_column(Text, default="")
    subjects: Mapped[str | None] = mapped_column(Text, default="")
    strengths: Mapped[str | None] = mapped_column(Text, default="")
    work_style: Mapped[str | None] = mapped_column(Text, default="")
    goals: Mapped[str | None] = mapped_column(Text, default="")
    dislikes: Mapped[str | None] = mapped_column(Text, default="")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped[User] = relationship(back_populates="profiles")

    # Only these keys are persisted from a submitted form.
    FIELDS = (
        "interests",
        "hobbies",
        "subjects",
        "strengths",
        "work_style",
        "goals",
        "dislikes",
    )


class RecommendationSession(Base):
    """One recommendation session: its ranked majors, scores and progress.

    ``public_id`` is the opaque id shared with the browser (it mirrors the
    in-memory conversation id in app.py) and is used to look a session up when
    refining it or attaching feedback.
    """

    __tablename__ = "recommendation_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(String(16), default="active")  # active | completed
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    questions_asked: Mapped[int] = mapped_column(Integer, default=0)

    scores: Mapped[dict] = mapped_column(JSON, default=dict)
    recommendations: Mapped[list] = mapped_column(JSON, default=list)
    message: Mapped[str | None] = mapped_column(Text, default="")

    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    user: Mapped[User] = relationship(back_populates="sessions")
    profile: Mapped[Profile | None] = relationship()
    feedback: Mapped[list["Feedback"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Feedback(Base):
    """A student's "was this major helpful?" response for a session.

    ``major`` names the recommended major the feedback is about, or is ``NULL``
    for feedback on the session overall.
    """

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("recommendation_sessions.id", ondelete="CASCADE"), index=True
    )
    major: Mapped[str | None] = mapped_column(String(120), nullable=True)
    helpful: Mapped[bool] = mapped_column(Boolean, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session: Mapped[RecommendationSession] = relationship(back_populates="feedback")


def _normalise_url(url: str) -> str:
    """Normalise a database URL for SQLAlchemy.

    Rewrites the legacy ``postgres://`` scheme some providers hand out to the
    ``postgresql://`` form SQLAlchemy 2.0 requires.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


def new_user_token() -> str:
    """Return a fresh opaque token to identify a returning visitor."""
    return uuid.uuid4().hex


def init_app(database_url: str | None = None, echo: bool = False) -> bool:
    """Configure the engine and create tables. Returns ``True`` when enabled.

    Never raises: a misconfigured or unreachable database is logged and leaves
    persistence disabled so the rest of the app keeps working.
    """
    global _engine, _Session, _enabled

    # Dispose any previously-configured engine so re-initialising (e.g. between
    # tests, or when switching databases) doesn't leak open connections.
    if _engine is not None:
        _engine.dispose()
        _engine = None

    url = _normalise_url(database_url or os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL)
    try:
        connect_args: dict = {}
        if url.startswith("sqlite"):
            # Flask's dev server is multi-threaded; allow cross-thread use and
            # wait (rather than erroring) briefly when the file is locked.
            connect_args = {"check_same_thread": False, "timeout": 30}

        engine = create_engine(
            url, echo=echo, future=True, pool_pre_ping=True, connect_args=connect_args
        )
        Base.metadata.create_all(engine)
        _migrate_users(engine)
    except (SQLAlchemyError, OSError, ImportError) as exc:
        _engine = None
        _Session = None
        _enabled = False
        logger.warning("Persistence disabled: could not initialise database (%s): %s",
                        url.split("://", 1)[0], exc)
        return False

    _engine = engine
    _Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    _enabled = True
    logger.info("Persistence enabled using %s backend.", url.split("://", 1)[0])
    return True


def is_enabled() -> bool:
    """Return ``True`` when a database has been initialised successfully."""
    return _enabled


def _migrate_users(engine) -> None:
    """Add the account columns/index to a pre-existing ``users`` table.

    ``create_all`` only creates missing *tables*, so databases created before
    accounts existed need the ``email`` / ``password_hash`` columns added. This
    is a tiny, idempotent forward migration (a no-op on fresh databases).
    """
    try:
        columns = {col["name"] for col in sa_inspect(engine).get_columns("users")}
        statements = []
        if "email" not in columns:
            statements.append("ALTER TABLE users ADD COLUMN email VARCHAR(255)")
        if "password_hash" not in columns:
            statements.append("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)")
        statements.append("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)")
        with engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))
    except SQLAlchemyError as exc:  # pragma: no cover - defensive
        logger.warning("User-account migration skipped: %s", exc)


@contextmanager
def _session_scope() -> Generator[Session, None, None]:
    """Provide a transactional session that commits or rolls back."""
    assert _Session is not None  # guarded by callers via is_enabled()
    session = _Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _get_or_create_user(session: Session, token: str) -> User:
    """Return the user for ``token``, creating the row on first sight."""
    user = session.scalar(select(User).where(User.token == token))
    if user is None:
        user = User(token=token)
        session.add(user)
        session.flush()
    return user


def _user_to_dict(user: User) -> dict:
    """Public, JSON-friendly shape of a user (never includes the password)."""
    return {
        "id": user.id,
        "email": user.email,
        "is_anonymous": user.email is None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def get_or_create_anonymous(token: str) -> dict | None:
    """Return the anonymous user for ``token``, creating it if needed."""
    if not _enabled or not token:
        return None
    try:
        with _session_scope() as session:
            return _user_to_dict(_get_or_create_user(session, token))
    except SQLAlchemyError as exc:
        logger.warning("Could not resolve anonymous user: %s", exc)
        return None


def get_user(user_id: int | None) -> dict | None:
    """Return the user with ``user_id``, or ``None``."""
    if not _enabled or not user_id:
        return None
    try:
        with _session_scope() as session:
            user = session.get(User, user_id)
            return _user_to_dict(user) if user else None
    except SQLAlchemyError as exc:
        logger.warning("Could not load user %s: %s", user_id, exc)
        return None


def create_account(
    email: str, password: str, adopt_token: str | None = None
) -> tuple[dict | None, str | None]:
    """Register an account, returning ``(user, None)`` or ``(None, error)``.

    If ``adopt_token`` points at an existing *anonymous* user, that row is
    upgraded in place so the guest's saved sessions become the new account's.
    """
    if not _enabled:
        return None, "Accounts are unavailable right now."
    email = (email or "").strip().lower()
    try:
        with _session_scope() as session:
            if session.scalar(select(User).where(User.email == email)) is not None:
                return None, "That email is already registered. Try signing in."

            user = None
            if adopt_token:
                candidate = session.scalar(select(User).where(User.token == adopt_token))
                if candidate is not None and candidate.email is None:
                    user = candidate  # upgrade the guest row (keeps its history)
            if user is None:
                user = User(token=new_user_token())
                session.add(user)

            user.email = email
            user.password_hash = generate_password_hash(password, method="pbkdf2:sha256")
            session.flush()
            return _user_to_dict(user), None
    except SQLAlchemyError as exc:
        logger.warning("Could not create account: %s", exc)
        return None, "Could not create the account. Please try again."


def authenticate(email: str, password: str) -> dict | None:
    """Return the user for valid ``email``/``password`` credentials, else None."""
    if not _enabled:
        return None
    email = (email or "").strip().lower()
    try:
        with _session_scope() as session:
            user = session.scalar(select(User).where(User.email == email))
            if user is None or not user.password_hash:
                check_password_hash(_DUMMY_PASSWORD_HASH, password or "")  # constant-ish time
                return None
            if not check_password_hash(user.password_hash, password or ""):
                return None
            return _user_to_dict(user)
    except SQLAlchemyError as exc:
        logger.warning("Could not authenticate: %s", exc)
        return None


def record_start(
    user_id: int | None,
    public_id: str,
    form: dict,
    result: dict,
    questions_asked: int,
    is_demo: bool = False,
) -> None:
    """Persist a new session: profile snapshot and first result for ``user_id``.

    Best-effort: any failure is logged and swallowed.
    """
    if not _enabled or not user_id:
        return
    try:
        with _session_scope() as session:
            profile = Profile(
                user_id=user_id,
                **{key: (str(form.get(key, "") or "")).strip() for key in Profile.FIELDS},
            )
            session.add(profile)
            session.flush()
            session.add(
                RecommendationSession(
                    public_id=public_id,
                    user_id=user_id,
                    profile_id=profile.id,
                    status="completed" if result.get("done") else "active",
                    is_demo=is_demo,
                    questions_asked=questions_asked,
                    scores=result.get("scores") or {},
                    recommendations=result.get("recommendations") or [],
                    message=result.get("message") or "",
                )
            )
    except SQLAlchemyError as exc:
        logger.warning("Could not persist session start %s: %s", public_id, exc)


def record_refine(
    public_id: str, result: dict, questions_asked: int, done: bool
) -> None:
    """Update a stored session with refined scores/recommendations/progress.

    Best-effort: any failure is logged and swallowed.
    """
    if not _enabled:
        return
    try:
        with _session_scope() as session:
            row = session.scalar(
                select(RecommendationSession).where(
                    RecommendationSession.public_id == public_id
                )
            )
            if row is None:
                return
            row.scores = result.get("scores") or {}
            row.recommendations = result.get("recommendations") or []
            row.message = result.get("message") or ""
            row.questions_asked = questions_asked
            row.status = "completed" if done else "active"
    except SQLAlchemyError as exc:
        logger.warning("Could not persist session refine %s: %s", public_id, exc)


def record_feedback(
    public_id: str, major: str | None, helpful: bool, comment: str | None = None
) -> bool:
    """Store a feedback answer for a session. Returns ``True`` when saved."""
    if not _enabled:
        return False
    try:
        with _session_scope() as session:
            row = session.scalar(
                select(RecommendationSession).where(
                    RecommendationSession.public_id == public_id
                )
            )
            if row is None:
                return False
            session.add(
                Feedback(
                    session_id=row.id,
                    major=(major or None),
                    helpful=bool(helpful),
                    comment=(comment or None),
                )
            )
        return True
    except SQLAlchemyError as exc:
        logger.warning("Could not persist feedback for %s: %s", public_id, exc)
        return False


def list_sessions(user_id: int | None, limit: int = 8) -> list[dict]:
    """Return a user's recent sessions, newest first, as plain dicts."""
    if not _enabled or not user_id:
        return []
    try:
        with _session_scope() as session:
            rows = session.scalars(
                select(RecommendationSession)
                .where(RecommendationSession.user_id == user_id)
                .order_by(RecommendationSession.created_at.desc())
                .limit(limit)
            ).all()
            return [_session_to_dict(row) for row in rows]
    except SQLAlchemyError as exc:
        logger.warning("Could not list sessions for user: %s", exc)
        return []


def _session_to_dict(row: RecommendationSession) -> dict:
    """Serialise a session row into a JSON-friendly summary dict."""
    recs = row.recommendations or []
    top = recs[0] if recs else None
    return {
        "session_id": row.public_id,
        "status": row.status,
        "is_demo": row.is_demo,
        "questions_asked": row.questions_asked,
        "top_major": (top or {}).get("name") if isinstance(top, dict) else None,
        "top_match": (top or {}).get("match") if isinstance(top, dict) else None,
        "recommendation_count": len(recs),
        "recommendations": recs,
        "scores": row.scores or {},
        "message": row.message or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
