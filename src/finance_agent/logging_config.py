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
) -> None:
    """Configure the root logger with console and optional file handlers.

    Args:
        level: Minimum log level (default INFO).
        log_file: Optional path to a log file. Parent dirs are created.
        fmt: Log format string.
        datefmt: Date format for timestamps.
    """
    root = logging.getLogger()

    # Avoid duplicate handlers on repeated calls
    if root.handlers:
        return

    root.setLevel(level)
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    # Console handler (stderr so it doesn't mix with stdout data output)
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

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
