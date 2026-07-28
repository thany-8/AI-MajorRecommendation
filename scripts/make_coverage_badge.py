#!/usr/bin/env python3
"""Generate ``docs/coverage.svg`` from the current coverage data.

Reads the ``.coverage`` file produced by the test-suite and writes a
shields-style SVG badge. No third-party badge library is required — only the
``coverage`` package (a dependency of ``pytest-cov``).

Usage::

    pytest                              # produces .coverage
    python scripts/make_coverage_badge.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import coverage

# (minimum coverage %, badge colour) — highest matching threshold wins.
_COLOURS = [
    (95, "#4c1"),      # brightgreen
    (90, "#97ca00"),   # green
    (75, "#a4a61d"),   # yellowgreen
    (60, "#dfb317"),   # yellow
    (40, "#fe7d37"),   # orange
    (0, "#e05d44"),    # red
]

_LABEL = "coverage"


def _colour_for(percent: int) -> str:
    for threshold, colour in _COLOURS:
        if percent >= threshold:
            return colour
    return _COLOURS[-1][1]


def _text_width(text: str) -> int:
    """Rough width (px) of ``text`` at font-size 11, plus horizontal padding."""
    return int(round(len(text) * 6.5)) + 10


def _svg(percent: int) -> str:
    value = f"{percent}%"
    colour = _colour_for(percent)
    label_w = _text_width(_LABEL)
    value_w = _text_width(value)
    total_w = label_w + value_w
    label_x = label_w / 2
    value_x = label_w + value_w / 2
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="20"
     role="img" aria-label="{_LABEL}: {value}">
  <title>{_LABEL}: {value}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <mask id="m"><rect width="{total_w}" height="20" rx="3" fill="#fff"/></mask>
  <g mask="url(#m)">
    <rect width="{label_w}" height="20" fill="#555"/>
    <rect x="{label_w}" width="{value_w}" height="20" fill="{colour}"/>
    <rect width="{total_w}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle"
     font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
    <text x="{label_x}" y="15" fill="#010101" fill-opacity=".3">{_LABEL}</text>
    <text x="{label_x}" y="14">{_LABEL}</text>
    <text x="{value_x}" y="15" fill="#010101" fill-opacity=".3">{value}</text>
    <text x="{value_x}" y="14">{value}</text>
  </g>
</svg>
"""


def main() -> int:
    cov = coverage.Coverage()
    try:
        cov.load()
        percent = int(round(cov.report(file=io.StringIO())))
    except coverage.CoverageException as exc:  # pragma: no cover - defensive
        print(f"Could not read coverage data: {exc}", file=sys.stderr)
        print("Run the test-suite first: pytest", file=sys.stderr)
        return 1

    out = Path(__file__).resolve().parent.parent / "docs" / "coverage.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_svg(percent), encoding="utf-8")
    print(f"Wrote {out} ({percent}% coverage)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
