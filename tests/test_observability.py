"""Unit tests for structured logging and metrics (:mod:`src.observability`)."""

import json
import logging
import sys

from src import observability
from src.observability import JsonFormatter, Metrics


def _record(level=logging.INFO, msg="hello", exc_info=None, **extra):
    record = logging.LogRecord("test.logger", level, __file__, 1, msg, None, exc_info)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_valid_json_with_request_context():
    record = _record(event="request", method="GET", path="/x", status=200, duration_ms=1.5)
    out = json.loads(JsonFormatter().format(record))
    assert out["level"] == "INFO"
    assert out["logger"] == "test.logger"
    assert out["message"] == "hello"
    assert out["method"] == "GET"
    assert out["path"] == "/x"
    assert out["status"] == 200
    assert out["timestamp"].endswith("Z")


def test_json_formatter_includes_exception_traceback():
    try:
        raise ValueError("boom")
    except ValueError:
        record = _record(level=logging.ERROR, msg="failed", exc_info=sys.exc_info())
    out = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in out["exception"]


def test_json_formatter_stringifies_unserialisable_extra():
    out = json.loads(JsonFormatter().format(_record(weird=object())))
    assert "weird" in out  # coerced to str, output still valid JSON


def test_metrics_incr_snapshot_and_reset():
    metrics = Metrics()
    metrics.incr("a")
    metrics.incr("a", 2)
    metrics.incr("b")
    assert metrics.snapshot() == {"a": 3, "b": 1}
    assert metrics.uptime_seconds() >= 0
    metrics.reset()
    assert metrics.snapshot() == {}


def test_init_error_monitoring_without_dsn_is_disabled(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert observability.init_error_monitoring() is False


def test_init_error_monitoring_without_sentry_sdk_is_disabled(monkeypatch):
    # sentry-sdk is an optional dependency and is not installed in the test env.
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    assert observability.init_error_monitoring() is False
