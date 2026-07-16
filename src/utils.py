# src/utils.py
"""Shared configuration and OpenAI client helpers.

This module centralises everything the rest of the app needs to talk to the
OpenAI API: loading the ``.env`` file, building the (modern v1/v2) client, and
exposing the trait categories and the seed list of majors.
"""

import os

from dotenv import load_dotenv
from openai import OpenAI

# Load variables from a local .env file (if present) into the environment.
load_dotenv()


class RecommenderError(RuntimeError):
    """Raised when the recommendation engine cannot complete a request.

    Used for user-facing failures such as a missing API key, an OpenAI API
    error, or an unparseable model response.
    """


# Personality / aptitude traits the questions score the student on (0-100).
CATEGORIES = ["Analytical", "Creative", "Social", "Technical", "Leadership"]

# A broad seed list of university majors. The model may also suggest majors
# outside this list; it is provided as helpful context, not a hard limit.
COMMON_MAJORS = [
    "Computer Science", "Software Engineering", "Data Science",
    "Information Systems", "Cybersecurity", "Electrical Engineering",
    "Mechanical Engineering", "Civil Engineering", "Aerospace Engineering",
    "Biomedical Engineering", "Mathematics", "Statistics", "Physics",
    "Biology", "Chemistry", "Environmental Science", "Neuroscience",
    "Psychology", "Sociology", "Anthropology", "Political Science",
    "Economics", "Philosophy", "Business Administration", "Marketing",
    "Finance", "Accounting", "Entrepreneurship", "Nursing",
    "Public Health", "Kinesiology", "Nutrition", "Graphic Design",
    "Fine Arts", "Architecture", "Industrial Design", "Music",
    "Film & Media Studies", "Theatre", "English Literature", "History",
    "Communications", "Journalism", "Education", "Linguistics",
    "International Relations", "Criminal Justice", "Law (Pre-Law)",
    "Medicine (Pre-Med)",
]

# Default chat model; overridable via the OPENAI_MODEL environment variable.
DEFAULT_MODEL = "gpt-4o-mini"

# Cache the client so we do not rebuild it on every request.
_client = None


def get_client():
    """Return a cached OpenAI client, creating it on first use.

    Raises:
        RecommenderError: If ``OPENAI_API_KEY`` is not configured.
    """
    global _client
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RecommenderError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add your "
            "OpenAI API key."
        )
    if _client is None:
        _client = OpenAI(api_key=api_key)
    return _client


def get_model():
    """Return the configured OpenAI chat model name."""
    return os.getenv("OPENAI_MODEL", DEFAULT_MODEL)


def ask_question(question):
    """Ask the user a question on the CLI and return their trimmed response."""
    print(question)
    return input("> ").strip()