#!/usr/bin/env python3
"""Build ``data/majors.json`` from a real, open college-majors dataset.

Source: FiveThirtyEight's "College Majors" dataset, derived from the U.S. Census
Bureau's American Community Survey (ACS) PUMS. It is distilled here into a
compact, committed JSON file that the app loads at runtime to sanity-check and
gently re-rank the model's major recommendations against real labour-market
data (median earnings, employment rate, field category).

    Data: American Community Survey (U.S. Census Bureau, public domain),
          cleaned by FiveThirtyEight (CC BY 4.0).
    https://github.com/fivethirtyeight/data/tree/master/college-majors

Usage::

    python scripts/build_major_dataset.py
"""

from __future__ import annotations

import csv
import io
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import requests

SOURCE_URL = (
    "https://raw.githubusercontent.com/fivethirtyeight/data/master/"
    "college-majors/recent-grads.csv"
)
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "majors.json"


def _to_int(value: str):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: str):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build(rows: list[dict]) -> dict:
    """Distil raw CSV rows into the committed dataset structure."""
    majors = []
    for row in rows:
        name = (row.get("Major") or "").strip()
        if not name:
            continue
        unemployment = _to_float(row.get("Unemployment_rate"))
        median = _to_int(row.get("Median"))
        college = _to_int(row.get("College_jobs")) or 0
        non_college = _to_int(row.get("Non_college_jobs")) or 0
        degree_share = (
            round(college / (college + non_college), 4)
            if (college + non_college) > 0
            else None
        )
        majors.append(
            {
                "name": name,
                "category": (row.get("Major_category") or "").strip(),
                "grads": _to_int(row.get("Total")),
                "median_earnings": median,
                "employment_rate": (
                    round(1 - unemployment, 4) if unemployment is not None else None
                ),
                "degree_job_share": degree_share,
            }
        )

    majors.sort(key=lambda m: m["name"])

    # Category aggregates, used as a fallback when a major only matches a field.
    categories: dict[str, dict] = {}
    by_category: dict[str, list[dict]] = {}
    for major in majors:
        by_category.setdefault(major["category"], []).append(major)
    for category, items in by_category.items():
        earnings = [m["median_earnings"] for m in items if m["median_earnings"]]
        employ = [m["employment_rate"] for m in items if m["employment_rate"] is not None]
        categories[category] = {
            "count": len(items),
            "median_earnings": int(statistics.median(earnings)) if earnings else None,
            "employment_rate": round(statistics.mean(employ), 4) if employ else None,
        }

    all_earnings = [m["median_earnings"] for m in majors if m["median_earnings"]]
    return {
        "meta": {
            "source": "FiveThirtyEight College Majors (U.S. Census Bureau ACS PUMS)",
            "source_url": SOURCE_URL,
            "license": "Data: ACS (public domain); compilation: CC BY 4.0 (FiveThirtyEight)",
            "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "major_count": len(majors),
            "earnings_min": min(all_earnings) if all_earnings else None,
            "earnings_max": max(all_earnings) if all_earnings else None,
        },
        "categories": categories,
        "majors": majors,
    }


def main() -> int:
    print(f"Fetching {SOURCE_URL} ...")
    resp = requests.get(SOURCE_URL, timeout=30)
    resp.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    dataset = build(rows)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Wrote {OUTPUT} — {dataset['meta']['major_count']} majors, "
        f"{len(dataset['categories'])} categories."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
