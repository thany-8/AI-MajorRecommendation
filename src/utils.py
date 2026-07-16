# src/utils.py
"""Shared configuration and Google Gemini client helpers.

This module centralises everything the rest of the app needs to talk to the
Gemini API: loading the ``.env`` file, building the client, and exposing the
trait categories and the seed list of majors.
"""

import os

from dotenv import load_dotenv
from google import genai

# Load variables from a local .env file (if present) into the environment.
load_dotenv()


class RecommenderError(RuntimeError):
    """Raised when the recommendation engine cannot complete a request.

    Used for user-facing failures such as a missing API key, a Gemini API
    error, or an unparseable model response.
    """


class CapacityError(RecommenderError):
    """Raised when the Gemini API is rate-limited or out of quota.

    Kept distinct from other errors so the app can automatically fall back to
    demo mode (see AUTO_DEMO_FALLBACK) when this specific condition occurs.
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

# Default chat model; overridable via the GEMINI_MODEL environment variable.
DEFAULT_MODEL = "gemini-2.5-flash"

# Cache the client so we do not rebuild it on every request.
_client = None


def get_api_key():
    """Return the configured Gemini API key (GEMINI_API_KEY or GOOGLE_API_KEY)."""
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def get_client():
    """Return a cached Gemini client, creating it on first use.

    Raises:
        RecommenderError: If no Gemini API key is configured.
    """
    global _client
    api_key = get_api_key()
    if not api_key:
        raise RecommenderError(
            "GEMINI_API_KEY is not set. Get a free key at "
            "https://aistudio.google.com/apikey, then copy .env.example to .env "
            "and add it (or set DEMO_MODE=1 to run without a key)."
        )
    if _client is None:
        _client = genai.Client(api_key=api_key)
    return _client


def get_model():
    """Return the configured Gemini model name."""
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)