"""In-process cache for initial recommendations.

Repeated — or effectively identical — profile submissions should not re-hit the
Gemini API. This module caches the result of the *initial* assessment
(:func:`src.recommender.start_session`) keyed by a normalised form of the
student's profile, with a bounded size and a time-to-live.

The cache is intentionally in-process (fine for a single Flask/Gunicorn worker).
A multi-process deployment would swap the backing store for something shared
(e.g. Redis); keeping the surface small (:meth:`ProfileCache.get`/``set``/
``clear``/``stats``) keeps that change local.
"""

from __future__ import annotations

import copy
import hashlib
import os
import threading

from cachetools import TTLCache

# Profile fields that define a "profile" for cache-key purposes.
_KEY_FIELDS = (
    "interests",
    "hobbies",
    "subjects",
    "strengths",
    "work_style",
    "goals",
    "dislikes",
)


def _env_int(name: str, default: int) -> int:
    """Return an int from the environment, falling back to ``default``."""
    try:
        return int(os.getenv(name, ""))
    except (TypeError, ValueError):
        return default


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class ProfileCache:
    """A thread-safe, bounded, TTL cache of ``start_session`` results."""

    def __init__(
        self,
        maxsize: int | None = None,
        ttl: int | None = None,
        enabled: bool | None = None,
    ):
        self.maxsize = maxsize if maxsize is not None else _env_int("CACHE_MAXSIZE", 512)
        self.ttl = ttl if ttl is not None else _env_int("CACHE_TTL", 3600)
        self.enabled = enabled if enabled is not None else _env_flag("CACHE_ENABLED", True)
        self._cache: TTLCache = TTLCache(maxsize=max(1, self.maxsize), ttl=max(1, self.ttl))
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def make_key(form: dict) -> str:
        """Return a stable key for a profile form.

        Each field is lower-cased and whitespace-collapsed so that profiles that
        are effectively the same (differing only in case, spacing or trailing
        blanks) map to the same key.
        """
        parts = []
        for field in _KEY_FIELDS:
            value = str((form or {}).get(field, "") or "")
            value = " ".join(value.lower().split())
            parts.append(f"{field}={value}")
        canonical = "\n".join(parts)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get(self, form: dict):
        """Return a deep copy of the cached value for ``form``, or ``None``."""
        if not self.enabled:
            return None
        key = self.make_key(form)
        with self._lock:
            value = self._cache.get(key)
            if value is None:
                self.misses += 1
                return None
            self.hits += 1
            return copy.deepcopy(value)

    def set(self, form: dict, value) -> None:
        """Store a deep-copied snapshot of ``value`` under ``form``'s key."""
        if not self.enabled:
            return
        key = self.make_key(form)
        with self._lock:
            self._cache[key] = copy.deepcopy(value)

    def clear(self) -> None:
        """Empty the cache and reset hit/miss counters."""
        with self._lock:
            self._cache.clear()
            self.hits = 0
            self.misses = 0

    def stats(self) -> dict:
        """Return a snapshot of cache configuration and hit/miss counters."""
        with self._lock:
            total = self.hits + self.misses
            return {
                "enabled": self.enabled,
                "size": len(self._cache),
                "maxsize": self.maxsize,
                "ttl": self.ttl,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else 0.0,
            }


# Module-level singleton used by the recommender.
profile_cache = ProfileCache()
