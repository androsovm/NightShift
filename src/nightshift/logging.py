"""Structured logging configuration for NightShift."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog


def configure_logging(*, verbose: bool = False, log_file: Path | None = None) -> None:
    """Set up structlog with proper processors and output.

    Args:
        verbose: If True, use colored console output at DEBUG level.
                 If False, use JSON output at INFO level (for launchd/systemd).
        log_file: Optional path to a JSONL log file for the run.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if verbose:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
        level = logging.DEBUG
    else:
        renderer = structlog.processors.JSONRenderer()
        level = logging.INFO

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)

    # File handler (for nightshift run logs)
    handlers: list[logging.Handler] = [console_handler]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_formatter = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
        file_handler.setFormatter(file_formatter)
        handlers.append(file_handler)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    for handler in handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(level)
