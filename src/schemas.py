"""Pydantic request/response schemas for the MajorMatch JSON API.

These models do double duty:

* **Request validation** – flask-openapi3 parses and validates incoming JSON
  against the request models before a view runs, returning HTTP 422 (via the
  ``ErrorResponse`` envelope) when the body is malformed.
* **API documentation** – the very same models are rendered into the OpenAPI 3
  specification and the Swagger UI served under ``/api/docs``.
"""

import re

from pydantic import BaseModel, Field, field_validator

from .utils import CATEGORIES

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
class RegisterRequest(BaseModel):
    """Create an account."""

    email: str = Field(..., description="Account email address.", examples=["you@example.com"])
    password: str = Field(..., description="At least 8 characters.", examples=["correcthorse"])

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        value = (value or "").strip().lower()
        if not _EMAIL_RE.match(value):
            raise ValueError("Enter a valid email address.")
        return value

    @field_validator("password")
    @classmethod
    def _strong_enough(cls, value: str) -> str:
        if len(value or "") < 8:
            raise ValueError("Password must be at least 8 characters.")
        return value


class LoginRequest(BaseModel):
    """Sign in to an existing account."""

    email: str = Field(..., description="Account email address.", examples=["you@example.com"])
    password: str = Field(..., description="Account password.")

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        return (value or "").strip().lower()


class UserResponse(BaseModel):
    """The current authentication state."""

    authenticated: bool = Field(..., description="Whether a real account is signed in.")
    email: str | None = Field(None, description="Signed-in account email, if any.")
    csrf_token: str | None = Field(
        None, description="CSRF token to send as the X-CSRFToken header."
    )


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
class ProfileForm(BaseModel):
    """A student's profile, submitted to start a recommendation session.

    Every field is optional, but at least one of ``interests`` or ``hobbies``
    must be provided.
    """

    interests: str = Field(
        "",
        description="What genuinely interests the student.",
        examples=["building apps, understanding people, space, video games"],
    )
    hobbies: str = Field(
        "", description="The student's hobbies.", examples=["drawing, chess, coding, music"]
    )
    subjects: str = Field(
        "", description="Favourite school subjects.", examples=["math, biology, art"]
    )
    strengths: str = Field(
        "", description="The student's strengths.", examples=["problem-solving, creativity"]
    )
    work_style: str = Field(
        "", description="Preferred way of working.", examples=["With people and teams"]
    )
    goals: str = Field(
        "", description="Dream job or goal.", examples=["start a company, make games"]
    )
    dislikes: str = Field(
        "", description="Things the student wants to avoid.", examples=["lots of writing"]
    )


class ChatRequest(BaseModel):
    """The student's answer to the advisor's latest follow-up question."""

    answer: str = Field(
        ...,
        description="Free-text answer to the advisor's question.",
        examples=["I'd rather work in a team than solo"],
    )


class FeedbackRequest(BaseModel):
    """Feedback on a recommendation session."""

    session_id: str = Field(
        ...,
        description="The session the feedback is about (returned by POST /start).",
        examples=["3f2a1c9b8e7d4f6a"],
    )
    helpful: bool = Field(
        ..., description="Whether the recommended major was helpful.", examples=[True]
    )
    major: str | None = Field(
        None,
        description="The specific major the feedback is about (omit for overall feedback).",
        examples=["Computer Science"],
    )
    comment: str | None = Field(None, description="Optional free-text comment.")


# --------------------------------------------------------------------------- #
# Responses
# --------------------------------------------------------------------------- #
class MajorData(BaseModel):
    """Real labour-market data attached to a recommendation (see src/dataset.py)."""

    grounded: bool = Field(..., description="Whether the major matched the real dataset.")
    matched: str | None = Field(None, description="The dataset major/category it matched.")
    match_level: str | None = Field(
        None, description="Match tier: exact, synonym, fuzzy, category or none."
    )
    category: str | None = Field(None, description="Field-of-study category.")
    median_earnings: int | None = Field(None, description="Median earnings (USD), full-time.")
    employment_rate: float | None = Field(None, description="Employment rate, 0–1.")


class Recommendation(BaseModel):
    """A single ranked major recommendation."""

    name: str = Field(..., description="The recommended major.")
    match: int = Field(..., ge=0, le=100, description="Fit strength, 0–100.")
    why: str = Field(..., description="One-sentence reason this major fits the student.")
    data: MajorData | None = Field(
        None, description="Real-world data used to sanity-check and re-rank this major."
    )


class RecommendationResult(BaseModel):
    """The advisor's assessment for a turn (start or refine)."""

    scores: dict[str, int] = Field(
        ..., description=f"Trait scores 0–100 for each of: {', '.join(CATEGORIES)}."
    )
    recommendations: list[Recommendation] = Field(
        ..., description="Ranked major matches, highest first."
    )
    message: str = Field(..., description="A short, friendly note to the student.")
    question: str = Field(
        "", description="The next follow-up question (empty string when finished)."
    )
    questions_asked: int = Field(..., description="How many questions have been asked so far.")
    max_questions: int = Field(
        ..., description="Approximate number of questions before finishing."
    )
    done: bool = Field(..., description="True when no further questions are needed.")
    session_id: str | None = Field(
        None,
        description="Session id for submitting feedback (present when persistence is enabled).",
    )


class FeedbackResponse(BaseModel):
    """Result of submitting feedback."""

    ok: bool = Field(..., description="Whether the request was accepted.")
    stored: bool = Field(
        ..., description="Whether the feedback was persisted (false when persistence is disabled)."
    )


class SessionSummary(BaseModel):
    """A stored recommendation session, as returned by GET /history."""

    session_id: str = Field(..., description="Public session id.")
    status: str = Field(..., description="'active' or 'completed'.")
    is_demo: bool = Field(..., description="Whether the session used offline demo mode.")
    questions_asked: int
    top_major: str | None = Field(None, description="Name of the top-ranked major, if any.")
    top_match: int | None = Field(None, description="Match score of the top-ranked major.")
    recommendation_count: int
    recommendations: list[Recommendation]
    scores: dict[str, int]
    message: str
    created_at: str | None = Field(None, description="ISO-8601 creation timestamp (UTC).")
    updated_at: str | None = Field(None, description="ISO-8601 last-update timestamp (UTC).")


class HistoryResponse(BaseModel):
    """A visitor's recent recommendation sessions."""

    sessions: list[SessionSummary] = Field(
        ..., description="The visitor's recent sessions, newest first."
    )


class ErrorResponse(BaseModel):
    """Standard error envelope returned for 4xx/5xx responses."""

    error: str = Field(..., description="Human-readable error message.")
    details: list[dict] | None = Field(
        None, description="Field-level validation details, when applicable."
    )
