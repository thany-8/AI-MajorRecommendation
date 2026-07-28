"""Structured logging, request tracing, metrics and error monitoring.

This module gives the app production-friendly observability:

* **Structured logs** – one JSON object per line, with request context, so logs
  are machine-parseable (LOG_FORMAT=plain switches to human-readable output).
* **Request tracing** – every request gets an id, echoed back as ``X-Request-ID``
  and attached to its log lines.
* **Metrics** – in-process counters (requests, errors, rate-limited) surfaced by
  the ``/healthz`` endpoint.
* **Error monitoring** – unhandled exceptions are logged with a traceback and
  returned as a clean JSON 500 (rather than an HTML page); an optional Sentry
  hook activates when ``SENTRY_DSN`` is set.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid

from flask import g, jsonify, request
from werkzeug.exceptions import HTTPException

logger = logging.getLogger("majormatch")

# Standard LogRecord attributes, so we can detect caller-supplied "extra" fields.
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}

# Request-context fields promoted to top-level keys in the JSON log line.
_CONTEXT_FIELDS = (
    "request_id",
    "method",
    "path",
    "status",
    "duration_ms",
    "remote_addr",
    "event",
)


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Promote known request-context fields, then any other custom extras.
        for key, value in record.__dict__.items():
            if key in _RESERVED or value is None:
                continue
            if key in _CONTEXT_FIELDS or key not in payload:
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = str(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str | None = None, fmt: str | None = None) -> None:
    """Configure root logging once, honouring LOG_LEVEL and LOG_FORMAT."""
    level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    fmt = (fmt or os.getenv("LOG_FORMAT", "json")).lower()

    handler = logging.StreamHandler(sys.stderr)
    if fmt == "plain":
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    # Werkzeug's per-request access log duplicates our structured request log.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


class Metrics:
    """A tiny thread-safe counter registry for lightweight monitoring."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self.started_at = time.time()

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._counters)

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self.started_at = time.time()

    def uptime_seconds(self) -> float:
        return round(time.time() - self.started_at, 1)


metrics = Metrics()


def init_error_monitoring() -> bool:
    """Enable Sentry error monitoring when ``SENTRY_DSN`` is set.

    ``sentry-sdk`` is an optional dependency: if the DSN is set but the package
    is missing, we log a warning and carry on with local logging only.
    """
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; skipping.")
        return False
    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0") or "0"),
    )
    logger.info("Sentry error monitoring enabled.")
    return True


def _log_level_for(path: str) -> int:
    """Health checks and static assets are noisy; log them at DEBUG."""
    if path == "/healthz" or "/static/" in path:
        return logging.DEBUG
    return logging.INFO


def install(app) -> None:
    """Register request-lifecycle logging, metrics and JSON error handlers."""

    @app.before_request
    def _begin():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        g.start_time = time.perf_counter()

    @app.after_request
    def _finish(response):
        request_id = getattr(g, "request_id", None)
        if request_id:
            response.headers["X-Request-ID"] = request_id

        duration_ms = None
        if hasattr(g, "start_time"):
            duration_ms = round((time.perf_counter() - g.start_time) * 1000, 2)

        metrics.incr("requests_total")
        if response.status_code >= 500:
            metrics.incr("errors_total")
        elif response.status_code == 429:
            metrics.incr("rate_limited_total")

        logger.log(
            _log_level_for(request.path),
            "request",
            extra={
                "event": "request",
                "request_id": request_id,
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "remote_addr": request.remote_addr,
            },
        )
        return response

    @app.errorhandler(404)
    def _not_found(e):
        # JSON for the API surface; the default HTML page elsewhere (e.g. SPA).
        if request.path.startswith("/api/"):
            return jsonify({"error": "Not found."}), 404
        return e

    @app.errorhandler(429)
    def _rate_limited(e):
        description = getattr(e, "description", "Too many requests.")
        logger.warning(
            "rate limit exceeded",
            extra={"event": "rate_limited", "request_id": getattr(g, "request_id", None),
                   "path": request.path},
        )
        return jsonify(
            {"error": f"Rate limit exceeded: {description}. Please slow down and try again."}
        ), 429

    @app.errorhandler(Exception)
    def _unhandled(e):
        # Preserve intentional HTTP errors (404, 422, 429, ...) and their bodies.
        if isinstance(e, HTTPException):
            return e
        request_id = getattr(g, "request_id", None)
        logger.error(
            "unhandled exception",
            extra={"event": "unhandled_exception", "request_id": request_id,
                   "path": request.path},
            exc_info=e,
        )
        return jsonify(
            {"error": "An unexpected error occurred. Please try again.", "request_id": request_id}
        ), 500
