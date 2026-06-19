"""Structured (JSON) logging for the CLAZZZIKS backend.

Standard library only — no extra dependencies. Entry points (CLI, web server)
call :func:`configure_logging` once at startup; library modules just do
``log = logging.getLogger(__name__)`` and attach structured context with the
:func:`log_event` helper (or ``extra={"context": {...}}`` directly).

All structured fields live under a single ``context`` key on the record so they
can never clash with reserved :class:`logging.LogRecord` attributes.

Configuration via environment (overridable per call):
    CLAZZZIKS_LOG_LEVEL   - DEBUG/INFO/WARNING/... (default INFO)
    CLAZZZIKS_LOG_FORMAT  - "json" (default) or "text"
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import sys
from typing import Any

#: Root logger name; every module logger (``clazzziks.*``) is a child of this.
ROOT_LOGGER = "clazzziks"


class JsonFormatter(logging.Formatter):
    """Render each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _dt.datetime.fromtimestamp(
                record.created, _dt.timezone.utc
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        context = getattr(record, "context", None)
        if context:
            # Never let context overwrite the core keys above.
            payload["context"] = context
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(
    level: str | int | None = None,
    fmt: str | None = None,
    stream=sys.stderr,
) -> logging.Logger:
    """Configure the ``clazzziks`` logger tree once, idempotently.

    Returns the configured root logger. Re-invoking replaces handlers so the
    last caller (e.g. an entry point) wins rather than stacking duplicates.
    """
    level = level or os.getenv("CLAZZZIKS_LOG_LEVEL", "INFO")
    if isinstance(level, str):
        level = level.upper()
    fmt = (fmt or os.getenv("CLAZZZIKS_LOG_FORMAT", "json")).lower()

    handler = logging.StreamHandler(stream)
    if fmt == "text":
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    else:
        handler.setFormatter(JsonFormatter())

    logger = logging.getLogger(ROOT_LOGGER)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    # Don't double-emit through the root logger's default handler.
    logger.propagate = False
    return logger


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    exc_info: bool = False,
    **context: Any,
) -> None:
    """Emit ``event`` at ``level`` with arbitrary structured ``context`` fields.

    Thin wrapper that packs keyword fields into the reserved ``context`` slot,
    keeping call sites readable::

        log_event(log, logging.INFO, "download.complete", url=url, ms=12)
    """
    logger.log(level, event, exc_info=exc_info, extra={"context": context or None})
