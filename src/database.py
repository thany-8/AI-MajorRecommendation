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

logger = logging.getLogger(__name__)

# Default on-disk SQLite database (relative to the current working directory).
# app.py overrides this with a path inside the Flask instance folder.
DEFAULT_DATABASE_URL = "sqlite:///majormatch.db"

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
    """An anonymous returning visitor, identified by an opaque cookie token."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
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


def record_start(
    token: str,
    public_id: str,
    form: dict,
    result: dict,
    questions_asked: int,
    is_demo: bool = False,
) -> None:
    """Persist a new session: user (if new), profile snapshot and first result.

    Best-effort: any failure is logged and swallowed.
    """
    if not _enabled:
        return
    try:
        with _session_scope() as session:
            user = _get_or_create_user(session, token)
            profile = Profile(
                user_id=user.id,
                **{key: (str(form.get(key, "") or "")).strip() for key in Profile.FIELDS},
            )
            session.add(profile)
            session.flush()
            session.add(
                RecommendationSession(
                    public_id=public_id,
                    user_id=user.id,
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


def list_sessions(token: str, limit: int = 8) -> list[dict]:
    """Return a user's recent sessions, newest first, as plain dicts."""
    if not _enabled:
        return []
    try:
        with _session_scope() as session:
            user = session.scalar(select(User).where(User.token == token))
            if user is None:
                return []
            rows = session.scalars(
                select(RecommendationSession)
                .where(RecommendationSession.user_id == user.id)
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
