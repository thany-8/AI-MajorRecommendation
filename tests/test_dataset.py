"""Unit tests for real-data grounding (:mod:`src.dataset`)."""

from src.dataset import MajorDataset, _normalize, major_dataset


def test_dataset_loads_real_majors():
    stats = major_dataset.stats()
    assert stats["loaded"] is True
    assert stats["major_count"] > 100
    assert "Census" in (stats["source"] or "")


def test_normalize_strips_parentheticals_and_punctuation():
    assert _normalize("Law (Pre-Law)") == "law"
    assert _normalize("  Computer   Science! ") == "computer science"


def test_match_exact():
    record, level = major_dataset.match("Computer Science")
    assert level == "exact"
    assert record["median_earnings"] > 0


def test_match_business_administration_is_grounded():
    record, level = major_dataset.match("Business Administration")
    assert level in ("exact", "synonym", "fuzzy")
    assert record is not None


def test_match_category_fallback():
    record, level = major_dataset.match("Political Science")
    assert level in ("category", "exact", "synonym", "fuzzy")
    assert record is not None


def test_match_unknown_major_is_none():
    record, level = major_dataset.match("Underwater Basket Weaving")
    assert level == "none"
    assert record is None


def test_ground_recommendations_annotates_and_reranks():
    recs = [
        {"name": "Underwater Basket Weaving", "match": 90, "why": "x"},
        {"name": "Computer Science", "match": 88, "why": "y"},
    ]
    out = major_dataset.ground_recommendations(recs)
    # The grounded major should out-rank the demoted, ungrounded one.
    assert out[0]["name"] == "Computer Science"
    assert out[0]["data"]["grounded"] is True
    assert out[0]["data"]["median_earnings"] > 0
    ungrounded = next(r for r in out if r["name"] == "Underwater Basket Weaving")
    assert ungrounded["data"]["grounded"] is False
    assert ungrounded["match"] < 90  # gently demoted


def test_ground_recommendations_disabled_is_passthrough():
    ds = MajorDataset(enabled=False)
    recs = [{"name": "Computer Science", "match": 88, "why": "y"}]
    assert ds.ground_recommendations(recs) == recs
    assert "data" not in recs[0]


def test_missing_data_file_disables_grounding(tmp_path):
    ds = MajorDataset(path=tmp_path / "missing.json")
    assert ds.enabled is False
    assert ds.stats()["loaded"] is False
    recs = [{"name": "X", "match": 50, "why": "z"}]
    assert ds.ground_recommendations(recs) == recs
