"""Ground the model's recommendations in real labour-market data.

Loads the distilled college-majors dataset (built by
``scripts/build_major_dataset.py`` from the U.S. Census ACS via FiveThirtyEight)
and uses it to:

* **sanity-check** each recommended major against real, recognised majors —
  flagging ones the model may have invented or mis-named, and
* **gently re-rank** the recommendations toward grounded majors, attaching real
  median-earnings / employment-rate data for display.

Grounding is best-effort: if the data file is missing or ``DATASET_ENABLED=0``,
:meth:`MajorDataset.ground_recommendations` returns the input unchanged.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "majors.json"

# Match tier -> fraction of the model's score retained (grounded majors keep
# their score; weaker/no matches are gently demoted).
_CONFIDENCE = {"exact": 1.0, "synonym": 1.0, "fuzzy": 0.9, "category": 0.75, "none": 0.5}
_FUZZY_CUTOFF = 0.82

# Curated synonyms mapping app majors to dataset entries (checked before fuzzy).
_SYNONYMS = {
    "business administration": "business management and administration",
    "software engineering": "computer science",
    "data science": "computer science",
    "cybersecurity": "computer science",
    "information systems": "information sciences",
    "graphic design": "commercial art and graphic design",
    "entrepreneurship": "business management and administration",
    "pre-med": "biology",
    "medicine": "biology",
    "pre-law": "pre law and legal studies",
    "law": "pre law and legal studies",
}

# Keyword -> dataset category, for a last-resort category-level match.
_CATEGORY_KEYWORDS = [
    ("Engineering", ("engineering", "architecture")),
    ("Computers & Mathematics",
     ("computer", "software", "data", "information", "cyber", "mathematic", "statistic")),
    ("Business", ("business", "marketing", "finance", "accounting", "entrepreneur", "management")),
    ("Psychology & Social Work", ("psychology", "social work", "counsel")),
    ("Arts", ("art", "design", "music", "theatre", "theater", "film", "dance", "photography")),
    ("Health",
     ("nursing", "health", "medicine", "medical", "kinesiology", "nutrition",
      "pharmacy", "dental")),
    ("Biology & Life Science", ("biology", "biomedical", "neuroscience", "genetics", "ecology")),
    ("Physical Sciences", ("physics", "chemistry", "astronomy", "geology", "environmental")),
    ("Social Science",
     ("economics", "political", "sociology", "anthropology", "international", "geography")),
    ("Humanities & Liberal Arts",
     ("english", "history", "philosophy", "linguistics", "literature", "language", "classics")),
    ("Communications & Journalism", ("communication", "journalism", "media", "public relations")),
    ("Education", ("education", "teaching")),
    ("Law & Public Policy", ("law", "legal", "criminal justice", "public policy", "public admin")),
    ("Agriculture & Natural Resources", ("agriculture", "forestry", "natural resource", "animal")),
]


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _normalize(name: str) -> str:
    """Lower-case, drop parentheticals and punctuation, collapse whitespace."""
    name = re.sub(r"\(.*?\)", " ", name or "")
    name = re.sub(r"[^a-z0-9]+", " ", name.lower())
    return " ".join(name.split()).strip()


class MajorDataset:
    """Loads the majors dataset and grounds recommendations against it."""

    def __init__(self, path: Path | None = None, enabled: bool | None = None):
        self.enabled = enabled if enabled is not None else _env_flag("DATASET_ENABLED", True)
        self._by_norm: dict[str, dict] = {}
        self._norm_names: list[str] = []
        self._categories: dict[str, dict] = {}
        self._meta: dict = {}
        self._lock = threading.Lock()
        self.grounded = 0
        self.ungrounded = 0
        self._load(path or _DATA_FILE)

    def _load(self, path: Path) -> None:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Major dataset unavailable (%s); grounding disabled: %s", path, exc)
            self.enabled = False
            return
        self._meta = data.get("meta", {})
        self._categories = data.get("categories", {})
        for major in data.get("majors", []):
            self._by_norm[_normalize(major["name"])] = major
        self._norm_names = list(self._by_norm)

    def _category_for(self, norm_name: str) -> str | None:
        for category, keywords in _CATEGORY_KEYWORDS:
            if any(kw in norm_name for kw in keywords):
                return category
        return None

    def match(self, name: str) -> tuple[dict | None, str]:
        """Return ``(record, level)`` for a major name.

        ``level`` is one of ``exact``, ``synonym``, ``fuzzy``, ``category`` or
        ``none``. ``record`` is a dataset major (or a category aggregate for
        ``category`` matches), or ``None`` when nothing matches.
        """
        norm = _normalize(name)
        if not norm or not self._by_norm:
            return None, "none"
        if norm in self._by_norm:
            return self._by_norm[norm], "exact"
        synonym = _SYNONYMS.get(norm)
        if synonym:
            record = self._by_norm.get(_normalize(synonym))
            if record:
                return record, "synonym"
        close = difflib.get_close_matches(norm, self._norm_names, n=1, cutoff=_FUZZY_CUTOFF)
        if close:
            return self._by_norm[close[0]], "fuzzy"
        category = self._category_for(norm)
        if category and category in self._categories:
            record = dict(self._categories[category])
            record["name"] = category
            record["category"] = category
            return record, "category"
        return None, "none"

    def ground_recommendations(self, recommendations: list[dict]) -> list[dict]:
        """Annotate recommendations with dataset data and gently re-rank them."""
        if not self.enabled or not recommendations:
            return recommendations

        grounded: list[dict] = []
        for rec in recommendations:
            item = dict(rec)
            record, level = self.match(item.get("name", ""))
            is_grounded = level != "none"
            with self._lock:
                if is_grounded:
                    self.grounded += 1
                else:
                    self.ungrounded += 1
            if not is_grounded:
                logger.info(
                    "recommended major not found in dataset",
                    extra={"event": "ungrounded_major", "major": item.get("name")},
                )

            item["data"] = {
                "grounded": is_grounded,
                "matched": record.get("name") if record else None,
                "match_level": level,
                "category": record.get("category") if record else None,
                "median_earnings": record.get("median_earnings") if record else None,
                "employment_rate": record.get("employment_rate") if record else None,
            }

            try:
                base = int(item.get("match", 0))
            except (TypeError, ValueError):
                base = 0
            factor = 0.85 + 0.15 * _CONFIDENCE.get(level, 0.5)
            item["match"] = max(0, min(100, round(base * factor)))
            grounded.append(item)

        grounded.sort(key=lambda r: r["match"], reverse=True)
        return grounded

    def stats(self) -> dict:
        """Return a snapshot for the health endpoint."""
        return {
            "enabled": self.enabled,
            "loaded": bool(self._by_norm),
            "major_count": len(self._by_norm),
            "source": self._meta.get("source"),
            "grounded": self.grounded,
            "ungrounded": self.ungrounded,
        }

    def reset_counts(self) -> None:
        with self._lock:
            self.grounded = 0
            self.ungrounded = 0


# Module-level singleton used by the recommender.
major_dataset = MajorDataset()
