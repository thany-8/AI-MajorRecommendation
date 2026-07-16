"""Core recommendation engine backed by the OpenAI Chat Completions API.

The web app drives the whole experience through two entry points:

* :func:`start_session`  - takes the student's profile form and returns the
  initial trait scores, a first set of major recommendations, a friendly
  message, and the first follow-up question.
* :func:`refine_session` - takes the running conversation plus the student's
  latest answer and returns updated scores, recommendations, a message, and the
  next follow-up question (or an empty question when enough is known).

Each turn is a single OpenAI call that returns strict JSON, so there is no
fragile string parsing and no use of ``eval`` (unlike the original skeleton).
"""

from __future__ import annotations

import json
import os

from openai import OpenAIError

from . import demo as _demo
from .utils import (
    CATEGORIES,
    COMMON_MAJORS,
    RecommenderError,
    get_client,
    get_model,
)

# How many refining follow-up questions to ask before finalising.
MAX_QUESTIONS = 6


def _demo_enabled() -> bool:
    """Return True when offline demo mode is switched on via DEMO_MODE."""
    return os.getenv("DEMO_MODE", "").strip().lower() in ("1", "true", "yes", "on")


def _auto_demo_fallback_enabled() -> bool:
    """Return True when API-limit fallback to demo mode is enabled."""
    return os.getenv("AUTO_DEMO_FALLBACK", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _is_capacity_error(exc: OpenAIError) -> bool:
    """Return True when OpenAI failed due to quota/rate/billing limits."""
    text = str(exc).lower()
    tokens = (
        "insufficient_quota",
        "exceeded your current quota",
        "rate limit",
        "billing",
        "429",
    )
    return any(token in text for token in tokens)


def _seed_demo_from_messages(messages: list[dict]) -> list[dict]:
    """Create demo-mode state from the existing OpenAI conversation."""
    user_parts = []
    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), str):
            user_parts.append(msg["content"])
    profile_text = "\n".join(user_parts).strip() or "The student did not provide many details yet."
    _, demo_messages = _demo.start({}, profile_text)
    return demo_messages

_SYSTEM_PROMPT = f"""
You are a warm, encouraging university academic advisor. You help students
discover which university MAJORS (academic programs) best fit their interests,
hobbies, personality and strengths.

You score each student from 0-100 on these five traits:
{", ".join(CATEGORIES)}.

You recommend academic MAJORS. Prefer well-known majors such as:
{", ".join(COMMON_MAJORS)}.
You may also suggest a closely related major that is not in that list when it
clearly fits the student better.

Rules:
- Always reply with STRICT JSON only. No markdown, no prose outside the JSON.
- The JSON must use exactly these keys: "scores", "recommendations", "message",
  "question".
- "scores" is an object mapping every trait name to an integer 0-100.
- "recommendations" is an array of 4-6 objects, each with:
    "name"  (the major),
    "match" (integer 0-100, how strong the fit is),
    "why"   (one short sentence, addressed to the student, on why it fits).
  Sort recommendations from highest to lowest "match".
- "message" is a short, friendly 1-2 sentence note to the student about what you
  learned and how the recommendations shifted.
- "question" is a single, specific follow-up question that will best refine the
  recommendation. Use an empty string "" only when you are confident enough that
  no further question is needed.
- Keep every field concise and student-friendly.
""".strip()


def _chat_json(messages: list[dict]) -> dict:
    """Call the model and return the parsed JSON object.

    Raises:
        RecommenderError: On API errors or if the response is not valid JSON.
    """
    client = get_client()
    try:
        response = client.chat.completions.create(
            model=get_model(),
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.7,
        )
    except OpenAIError as exc:  # network, auth, rate-limit, etc.
        if _is_capacity_error(exc):
            raise RecommenderError(
                "Your OpenAI account has no available quota/credits. Add a balance "
                "at https://platform.openai.com/settings/organization/billing, or "
                "set DEMO_MODE=1 in your .env to run the app for free without a key."
            ) from exc
        raise RecommenderError(f"OpenAI API error: {exc}") from exc

    content = (response.choices[0].message.content or "").strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise RecommenderError(
            "The AI returned a response that could not be understood. "
            "Please try again."
        ) from exc


def _normalise(data: dict) -> dict:
    """Coerce the model output into a predictable, safe shape for the UI."""
    scores = {}
    raw_scores = data.get("scores") or {}
    for trait in CATEGORIES:
        try:
            scores[trait] = max(0, min(100, int(round(float(raw_scores.get(trait, 0))))))
        except (TypeError, ValueError):
            scores[trait] = 0

    recommendations = []
    for item in data.get("recommendations") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        try:
            match = max(0, min(100, int(round(float(item.get("match", 0))))))
        except (TypeError, ValueError):
            match = 0
        recommendations.append(
            {"name": name, "match": match, "why": str(item.get("why", "")).strip()}
        )
    recommendations.sort(key=lambda r: r["match"], reverse=True)

    return {
        "scores": scores,
        "recommendations": recommendations,
        "message": str(data.get("message", "")).strip(),
        "question": str(data.get("question", "")).strip(),
    }


def build_profile_summary(form: dict) -> str:
    """Turn the raw profile form into a readable summary for the model."""
    fields = [
        ("Interests", form.get("interests")),
        ("Hobbies", form.get("hobbies")),
        ("Favorite subjects", form.get("subjects")),
        ("Strengths", form.get("strengths")),
        ("Preferred way of working", form.get("work_style")),
        ("Career goals or dreams", form.get("goals")),
        ("Things they dislike or want to avoid", form.get("dislikes")),
    ]
    lines = [f"- {label}: {value.strip()}"
             for label, value in fields
             if isinstance(value, str) and value.strip()]
    if not lines:
        return "The student did not provide many details yet."
    return "Here is what the student told us about themselves:\n" + "\n".join(lines)


def start_session(form: dict) -> tuple[dict, list[dict]]:
    """Begin a new recommendation session from the profile form.

    Returns:
        A tuple of (result, messages) where ``result`` is the normalised payload
        for the UI and ``messages`` is the running OpenAI conversation to persist.
    """
    profile = build_profile_summary(form)
    if _demo_enabled():
        data, messages = _demo.start(form, profile)
        return _normalise(data), messages
    user_prompt = (
        f"{profile}\n\n"
        "Assess this student now. Provide their trait scores, 4-6 major "
        "recommendations with match percentages, a friendly message, and the "
        "single best follow-up question to refine the recommendation. "
        "Respond with the required JSON."
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    try:
        data = _chat_json(messages)
    except RecommenderError as exc:
        if _auto_demo_fallback_enabled() and "quota/credits" in str(exc).lower():
            data, messages = _demo.start(form, profile)
            data["message"] = (
                "OpenAI credits are currently unavailable, so I switched to free "
                "demo mode for now. " + data.get("message", "")
            ).strip()
            return _normalise(data), messages
        raise

    result = _normalise(data)
    messages.append({"role": "assistant", "content": json.dumps(data)})
    return result, messages


def refine_session(
    messages: list[dict], answer: str, questions_asked: int
) -> tuple[dict, list[dict]]:
    """Continue a session with the student's latest answer.

    Args:
        messages: The persisted OpenAI conversation from the previous turn.
        answer: The student's free-text answer to the last follow-up question.
        questions_asked: How many follow-up questions have been asked so far.

    Returns:
        A tuple of (result, messages) with the updated payload and conversation.
    """
    if _demo_enabled() or (messages and messages[0].get("role") == "demo"):
        data, messages = _demo.refine(messages, answer, questions_asked, MAX_QUESTIONS)
        return _normalise(data), messages

    finalize = questions_asked + 1 >= MAX_QUESTIONS
    instruction = (
        f'The student answered: "{answer.strip()}"\n\n'
        "Update the trait scores and recommendations based on this answer. "
        "Give a brief friendly message about what changed. "
    )
    if finalize:
        instruction += (
            'This is the final turn: set "question" to an empty string and make '
            "your recommendations final."
        )
    else:
        instruction += "Then ask the single best next follow-up question."

    messages = messages + [{"role": "user", "content": instruction}]
    try:
        data = _chat_json(messages)
    except RecommenderError as exc:
        if _auto_demo_fallback_enabled() and "quota/credits" in str(exc).lower():
            demo_messages = (
                messages if messages and messages[0].get("role") == "demo" else _seed_demo_from_messages(messages)
            )
            data, messages = _demo.refine(
                demo_messages,
                answer,
                questions_asked,
                MAX_QUESTIONS,
            )
            data["message"] = (
                "OpenAI credits are currently unavailable, so I switched to free "
                "demo mode for now. " + data.get("message", "")
            ).strip()
        else:
            raise

    result = _normalise(data)
    if finalize:
        result["question"] = ""
    messages.append({"role": "assistant", "content": json.dumps(data)})
    return result, messages
