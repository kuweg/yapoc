"""Loguru-based logging setup for YAPOC.

Call ``setup_logging()`` once at process startup. Idempotent — safe to call
multiple times (subsequent calls are no-ops).

Format controlled by ``settings.log_json``:
  - Human (default): colourised single-line with agent column
  - JSON (log_json=True): loguru's native ``serialize=True`` NDJSON

All stdlib ``logging.getLogger()`` calls (notification_poller, usage_tracker,
adapters, etc.) are intercepted and forwarded through loguru via
``InterceptHandler`` so every log record goes to the same sinks.
"""

from __future__ import annotations

import logging
import sys

_SETUP_DONE = False

# Noisy third-party loggers to raise to WARNING
_SILENCE = (
    "httpx",
    "httpcore",
    "anthropic",
    "uvicorn.access",
    "apscheduler",
    "watchdog",
    "watchfiles",
)


class InterceptHandler(logging.Handler):
    """Forward stdlib logging records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        from loguru import logger

        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Walk the call stack to find the actual caller
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore[assignment]
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _human_fmt(record: dict) -> str:  # type: ignore[type-arg]
    """Callable format: gracefully handles records that have no 'agent' extra."""
    agent = record["extra"].get("agent", "")
    if agent:
        agent_col = f"[{agent:<10}]"
    else:
        # stdlib-intercepted records: use the logger name's last component
        agent_col = f"[{record['name'].split('.')[-1]:<10}]"
    # Loguru appends {exception} automatically when present; \n keeps it on its own line
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
        "<level>[{level: <5}]</level> "
        f"{agent_col} "
        "{message}\n{exception}"
    )


def setup_logging() -> None:
    """Configure loguru sinks and intercept stdlib logging.  Idempotent."""
    global _SETUP_DONE
    if _SETUP_DONE:
        return
    _SETUP_DONE = True

    from loguru import logger
    from app.config import settings

    # Remove loguru's default stderr sink so we control the format ourselves
    logger.remove()

    if not settings.log_agent_activity:
        # Add a silent sink so loguru doesn't complain; no output emitted
        logger.add(sys.stderr, level="CRITICAL")
        return

    level = settings.log_level.upper()

    if settings.log_json:
        # loguru's native serializer — one JSON object per line
        logger.add(sys.stderr, level=level, serialize=True, enqueue=False)
    else:
        logger.add(
            sys.stderr,
            level=level,
            format=_human_fmt,  # type: ignore[arg-type]
            colorize=True,
            enqueue=False,
        )

    if settings.log_file:
        from pathlib import Path
        Path(settings.log_file).parent.mkdir(parents=True, exist_ok=True)
        if settings.log_json:
            logger.add(
                settings.log_file,
                level=level,
                serialize=True,
                rotation="10 MB",
                retention=3,
                encoding="utf-8",
                enqueue=False,
            )
        else:
            logger.add(
                settings.log_file,
                level=level,
                format=_human_fmt,  # type: ignore[arg-type]
                colorize=False,  # no ANSI codes in files
                rotation="10 MB",
                retention=3,
                encoding="utf-8",
                enqueue=False,
            )

    # Route ALL stdlib logging.getLogger() calls through loguru
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # Quiet noisy third-party loggers at stdlib level so InterceptHandler drops them
    for name in _SILENCE:
        logging.getLogger(name).setLevel(logging.WARNING)
