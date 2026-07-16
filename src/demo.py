"""Offline demo engine, used when ``DEMO_MODE`` is enabled.

Produces realistic, deterministic major recommendations from simple keyword
matching, so the app runs with **no OpenAI key and no cost**. It is not a
replacement for the real AI advisor — just enough to explore the UI or present
the app. ``recommender.start_session``/``refine_session`` delegate here when
demo mode is on, so the rest of the app is unchanged.
"""

from __future__ import annotations

import json

from .utils import CATEGORIES

# Follow-up questions the demo advisor asks, in order.
QUESTIONS = [
    "When you build or create something, do you prefer working out the logic and "
    "details, or imagining how it looks and feels?",
    "Would you rather work solo on deep problems, or lead and collaborate with a team?",
    "Are you more drawn to working with people, or with data, systems and things?",
    "Do you enjoy hands-on making and experimenting, or analysing and researching ideas?",
]

# Trait -> keywords, used to score any free text (profile or answer).
_SIGNALS = {
    "Analytical": ["analyse", "analyze", "research", "problem", "logic", "math",
                   "numbers", "data", "study", "think", "deep", "science", "puzzle"],
    "Creative": ["design", "art", "draw", "paint", "music", "creative", "visual",
                 "imagine", "story", "aesthetic", "looks", "feel", "photography", "film"],
    "Social": ["people", "help", "helping", "team", "together", "talk", "community",
               "care", "patient", "communicate", "social", "friends", "teach"],
    "Technical": ["code", "coding", "app", "apps", "software", "build", "computer",
                  "tech", "engineer", "system", "systems", "machine", "robot",
                  "game", "games", "hands-on", "hands on", "under the hood"],
    "Leadership": ["lead", "leading", "leader", "manage", "organize", "organise",
                   "charge", "direct", "run", "business", "startup", "entrepreneur"],
}

# Major -> matching keywords, trait weights, a base popularity nudge, and a blurb.
_MAJORS = {
    "Computer Science": {
        "kw": ["code", "coding", "app", "apps", "program", "software", "computer",
               "tech", "game", "games", "ai", "robot", "algorithm"],
        "traits": {"Technical": 1.0, "Analytical": 0.9},
        "base": 7,
        "blurb": "building software and solving logical problems.",
    },
    "Software Engineering": {
        "kw": ["build", "building", "software", "app", "apps", "engineer",
               "product", "develop", "system", "systems"],
        "traits": {"Technical": 1.0, "Analytical": 0.6, "Leadership": 0.4},
        "base": 6,
        "blurb": "turning ideas into working, real-world products.",
    },
    "Data Science": {
        "kw": ["data", "statistics", "stats", "math", "analysis", "analytics",
               "numbers", "machine learning", "pattern", "science"],
        "traits": {"Analytical": 1.0, "Technical": 0.7},
        "base": 5,
        "blurb": "finding insights and patterns in data.",
    },
    "Psychology": {
        "kw": ["people", "psychology", "mind", "behavior", "behaviour", "help",
               "emotion", "understand", "therapy", "brain"],
        "traits": {"Social": 1.0, "Analytical": 0.5},
        "base": 5,
        "blurb": "understanding how people think and behave.",
    },
    "Business Administration": {
        "kw": ["business", "money", "manage", "management", "lead", "leadership",
               "startup", "company", "entrepreneur", "market", "marketing", "sell"],
        "traits": {"Leadership": 1.0, "Social": 0.6},
        "base": 5,
        "blurb": "leading teams and running organizations.",
    },
    "Graphic Design": {
        "kw": ["design", "art", "draw", "drawing", "paint", "creative", "visual",
               "aesthetic", "illustration", "looks", "feel"],
        "traits": {"Creative": 1.0, "Technical": 0.3},
        "base": 4,
        "blurb": "creating visual, aesthetic work.",
    },
    "Fine Arts": {
        "kw": ["art", "music", "paint", "draw", "creative", "perform", "theatre",
               "film", "photography", "story"],
        "traits": {"Creative": 1.0, "Social": 0.3},
        "base": 3,
        "blurb": "expressing ideas through creative work.",
    },
    "Mechanical Engineering": {
        "kw": ["build", "fix", "machine", "hands-on", "hands on", "robot", "car",
               "cars", "mechanical", "physics", "experiment"],
        "traits": {"Technical": 1.0, "Analytical": 0.7},
        "base": 4,
        "blurb": "designing and building physical things.",
    },
    "Nursing": {
        "kw": ["help", "helping", "health", "care", "caring", "medicine",
               "patient", "hospital", "biology"],
        "traits": {"Social": 1.0, "Technical": 0.4},
        "base": 4,
        "blurb": "caring for people and their health.",
    },
    "Communications": {
        "kw": ["writing", "write", "talk", "speak", "media", "social media",
               "communication", "journalism", "story"],
        "traits": {"Social": 0.8, "Creative": 0.6},
        "base": 4,
        "blurb": "connecting with people through media and storytelling.",
    },
    "Economics": {
        "kw": ["economy", "money", "finance", "market", "numbers", "trade",
               "business", "analysis"],
        "traits": {"Analytical": 1.0, "Leadership": 0.4},
        "base": 4,
        "blurb": "analysing markets, incentives and decisions.",
    },
    "Political Science": {
        "kw": ["politics", "government", "law", "debate", "society", "history",
               "justice", "policy"],
        "traits": {"Social": 0.8, "Analytical": 0.6, "Leadership": 0.6},
        "base": 3,
        "blurb": "shaping society, policy and institutions.",
    },
}


def _compute_scores(text: str) -> dict:
    """Score the five traits from free text via keyword hits."""
    text = (text or "").lower()
    scores = {}
    for trait, keywords in _SIGNALS.items():
        hits = sum(1 for kw in keywords if kw in text)
        scores[trait] = max(0, min(96, 42 + hits * 13))
    return scores


def _apply_answer(scores: dict, answer: str) -> dict:
    """Boost traits mentioned in the student's latest answer."""
    text = (answer or "").lower()
    updated = dict(scores)
    for trait, keywords in _SIGNALS.items():
        hits = sum(1 for kw in keywords if kw in text)
        if hits:
            updated[trait] = min(98, updated.get(trait, 42) + hits * 9)
    return updated


def _rank_majors(scores: dict, text: str) -> list:
    """Rank majors by trait alignment plus keyword hits in the text."""
    text = (text or "").lower()
    scored = []
    for name, spec in _MAJORS.items():
        weights = spec["traits"]
        align = sum(scores.get(t, 42) * w for t, w in weights.items()) / (
            sum(weights.values()) or 1
        )
        matched = [kw for kw in spec["kw"] if kw in text]
        raw = align + len(matched) * 9 + spec["base"]
        scored.append((name, raw, matched, spec))

    scored.sort(key=lambda item: item[1], reverse=True)
    top = scored[:5]
    raw_max = top[0][1] if top else 1

    recommendations = []
    for name, raw, matched, spec in top:
        match = int(round(93 * raw / raw_max)) if raw_max else 70
        match = max(58, min(96, match))
        if matched:
            why = f"Your mention of \u201c{matched[0]}\u201d fits {name} \u2014 it's about {spec['blurb']}"
        else:
            why = f"A strong overall fit \u2014 {name} is about {spec['blurb']}"
        recommendations.append({"name": name, "match": match, "why": why})
    return recommendations


def start(form: dict, profile_text: str) -> tuple[dict, list]:
    """Demo equivalent of :func:`recommender.start_session`."""
    scores = _compute_scores(profile_text)
    recommendations = _rank_majors(scores, profile_text)
    top = recommendations[0]["name"] if recommendations else "a great major"
    data = {
        "scores": scores,
        "recommendations": recommendations,
        "message": (
            f"Thanks! I can already see strong matches like {top}. "
            "Let's refine them with a few quick questions. "
            "(Demo mode \u2014 no OpenAI credits are being used.)"
        ),
        "question": QUESTIONS[0],
    }
    state = {"scores": scores, "text": profile_text}
    messages = [{"role": "demo", "content": json.dumps(state)}]
    return data, messages


def refine(messages: list, answer: str, questions_asked: int, max_questions: int) -> tuple[dict, list]:
    """Demo equivalent of :func:`recommender.refine_session`."""
    try:
        state = json.loads(messages[0]["content"]) if messages else {}
    except (json.JSONDecodeError, KeyError, IndexError):
        state = {}
    scores = state.get("scores") or {trait: 42 for trait in CATEGORIES}
    text = state.get("text", "")

    scores = _apply_answer(scores, answer)
    text = f"{text} {answer}".strip()
    recommendations = _rank_majors(scores, text)
    top = recommendations[0]["name"] if recommendations else "your top major"

    next_index = questions_asked
    finalize = (questions_asked + 1 >= max_questions) or (next_index >= len(QUESTIONS))
    question = "" if finalize else QUESTIONS[next_index]

    if finalize:
        message = (
            f"That gives me a clear picture \u2014 {top} stands out as your top match. "
            "These are your final recommendations! \U0001f389"
        )
    else:
        message = f"Got it \u2014 I've updated your matches, and {top} is looking like a strong fit."

    data = {
        "scores": scores,
        "recommendations": recommendations,
        "message": message,
        "question": question,
    }
    new_state = {"scores": scores, "text": text}
    messages = [{"role": "demo", "content": json.dumps(new_state)}]
    return data, messages
