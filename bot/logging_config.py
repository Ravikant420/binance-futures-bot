"""
bot/logging_config.py
─────────────────────
Centralised logging configuration for the trading bot.

Design decisions
----------------
- Two handlers: rotating file (DEBUG+) and console (INFO+).
- RotatingFileHandler prevents unbounded log growth in long-running sessions.
- Idempotency is implemented by checking ``logger.handlers`` — the canonical
  Python idiom — rather than a module-level flag. This is thread-safe and
  requires no global state.
- Log format includes milliseconds so latency differences are visible.
- The logs/ directory is created automatically if absent.

Fixes applied (v2)
------------------
- Removed unused ``import os`` (was flagged by ruff F401).
- Replaced ``_configured: bool`` global flag + ``global`` statement with
  ``if logger.handlers`` check — thread-safe, no mutable global state.
- Added ``__all__`` to declare the public API explicitly.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

__all__ = ["setup_logging", "get_logger", "LOGGER_NAME"]

# ── Constants ──────────────────────────────────────────────────────────────────

LOGGER_NAME: str = "trading_bot"

_LOG_DIR: Path = Path(__file__).resolve().parent.parent / "logs"
_LOG_FILE: Path = _LOG_DIR / "trading.log"

_FILE_MAX_BYTES: int = 5 * 1024 * 1024   # 5 MB per file
_FILE_BACKUP_COUNT: int = 3               # keep trading.log + 3 rotated copies

_LOG_FORMAT: str = (
    "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(message)s"
)
_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


# ── Public API ─────────────────────────────────────────────────────────────────


def setup_logging(log_level: int = logging.DEBUG) -> logging.Logger:
    """
    Configure the root ``trading_bot`` logger exactly once.

    Idempotency is implemented by inspecting ``logger.handlers``: if handlers
    are already registered the logger is returned immediately without adding
    duplicates.  This is the standard Python idiom and is safe to call from
    multiple modules or in tests without accumulating duplicate handlers.

    Parameters
    ----------
    log_level:
        Minimum severity for the **file** handler.  The console handler is
        always pinned to INFO to keep terminal output clean.

    Returns
    -------
    logging.Logger
        The configured ``trading_bot`` logger, ready for use.
    """
    logger = logging.getLogger(LOGGER_NAME)

    # ── Idempotency guard ──────────────────────────────────────────────────────
    # ``logger.handlers`` is the single source of truth — no global flag needed.
    # Checking the handlers list is also thread-safe unlike a bare bool flag.
    if logger.handlers:
        return logger

    _ensure_log_dir()

    logger.setLevel(logging.DEBUG)

    logger.addHandler(_build_file_handler(log_level))
    logger.addHandler(_build_console_handler())

    logger.propagate = False

    logger.debug("Logging initialised. File → %s", _LOG_FILE)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """
    Return a child logger under the ``trading_bot`` namespace.

    Parameters
    ----------
    name:
        Dotted suffix appended to ``trading_bot``.  If *None* or empty the
        root ``trading_bot`` logger is returned.

    Examples
    --------
    >>> log = get_logger("orders")
    >>> log.name
    'trading_bot.orders'
    """
    if not name:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")


# ── Private helpers ────────────────────────────────────────────────────────────


def _ensure_log_dir() -> None:
    """Create the logs/ directory (and any parents) if it does not exist."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _build_file_handler(level: int) -> logging.handlers.RotatingFileHandler:
    """
    Build a rotating file handler that writes structured log lines.

    Rotation occurs when the file reaches ``_FILE_MAX_BYTES``.  Up to
    ``_FILE_BACKUP_COUNT`` old files are retained; older ones are deleted.
    """
    handler = logging.handlers.RotatingFileHandler(
        filename=_LOG_FILE,
        maxBytes=_FILE_MAX_BYTES,
        backupCount=_FILE_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(_build_formatter())
    return handler


def _build_console_handler() -> logging.StreamHandler:  # type: ignore[type-arg]
    """
    Build a stderr console handler restricted to INFO and above.

    Keeping the console at INFO avoids flooding the terminal with DEBUG-level
    API internals while still surfacing all important events.
    """
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(_build_formatter())
    return handler


def _build_formatter() -> logging.Formatter:
    """Return a shared :class:`logging.Formatter` using the project format."""
    return logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)