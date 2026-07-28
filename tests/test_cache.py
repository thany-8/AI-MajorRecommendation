"""Unit tests for the profile cache (:mod:`src.cache`)."""

from src.cache import ProfileCache


def test_make_key_normalises_case_and_whitespace():
    a = ProfileCache.make_key({"interests": "Coding, Games"})
    b = ProfileCache.make_key({"interests": "coding,   games"})
    c = ProfileCache.make_key({"interests": "  CODING,\tGAMES "})
    assert a == b == c


def test_make_key_differs_for_different_profiles():
    assert ProfileCache.make_key({"interests": "coding"}) != ProfileCache.make_key(
        {"interests": "painting"}
    )


def test_get_set_hit_and_miss():
    cache = ProfileCache(maxsize=10, ttl=60)
    form = {"interests": "coding"}
    assert cache.get(form) is None  # miss
    cache.set(form, ({"x": 1}, ["m"]))
    assert cache.get(form) == ({"x": 1}, ["m"])  # hit
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["size"] == 1


def test_get_returns_deep_copy_so_callers_cannot_mutate_cache():
    cache = ProfileCache(maxsize=10, ttl=60)
    form = {"interests": "coding"}
    cache.set(form, {"recommendations": [{"name": "CS"}]})
    got = cache.get(form)
    got["recommendations"][0]["name"] = "MUTATED"
    assert cache.get(form)["recommendations"][0]["name"] == "CS"


def test_disabled_cache_is_a_noop():
    cache = ProfileCache(maxsize=10, ttl=60, enabled=False)
    cache.set({"interests": "x"}, "value")
    assert cache.get({"interests": "x"}) is None
    assert cache.stats()["enabled"] is False


def test_clear_empties_entries_and_counters():
    cache = ProfileCache(maxsize=10, ttl=60)
    cache.set({"interests": "x"}, "value")
    cache.get({"interests": "x"})
    cache.clear()
    stats = cache.stats()
    assert stats["size"] == 0
    assert stats["hits"] == 0
    assert stats["misses"] == 0
