"""Centralized logging configuration.

Call setup_logging() once at the application entry point (main.py / collector).
Library modules use: logger = logging.getLogger(__name__)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logging(
    *,
    level: int = logging.INFO,
    log_file: str | Path | None = None,
    fmt: str = "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt: str = "%Y-%m-%d %H:%M:%S",
    console: bool = True,
) -> None:
    """Configure the root logger with console and optional file handlers.

    Args:
        level: Minimum log level (default INFO).
        log_file: Optional path to a log file. Parent dirs are created.
        fmt: Log format string.
        datefmt: Date format for timestamps.
        console: If True, add stderr handler. Set False for TUI mode
            (stderr writes corrupt Textual's alternate screen buffer).
    """
    root = logging.getLogger()

    # Avoid duplicate handlers on repeated calls
    if root.handlers:
        return

    root.setLevel(level)
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    if console:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(level)
        handler.setFormatter(formatter)
        root.addHandler(handler)

    # Optional file handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # file gets everything
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Quiet noisy libraries
    logging.getLogger("alembic").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def add_session_file_handler(
    log_dir: str | Path,
    session_id: str,
    *,
    level: int = logging.DEBUG,
    fmt: str = "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt: str = "%Y-%m-%d %H:%M:%S",
) -> logging.FileHandler:
    """Add a session-specific file handler to the root logger.

    Creates ``{log_dir}/agent_{session_id}.log``.  Returns the handler
    so callers can remove it later if needed.
    """
    log_path = Path(log_dir) / f"agent_{session_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(str(log_path), encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

    root = logging.getLogger()
    root.addHandler(handler)
    return handler
