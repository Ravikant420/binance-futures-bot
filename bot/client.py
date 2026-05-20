"""
bot/client.py
─────────────
Binance Futures Testnet client factory.

Responsibilities
----------------
- Load API credentials from environment variables (populated from .env).
- Build and return a configured ``binance.Client`` pointed at the Testnet.
- Perform a lightweight connectivity check on construction.
- Raise typed, descriptive exceptions so callers never see raw library errors.

Design notes
------------
- ``get_client()`` is the single point of entry for all Binance SDK access.
  No other module should instantiate ``binance.Client`` directly.
- The module keeps NO module-level client singleton; the CLI layer is
  responsible for calling ``get_client()`` once and passing it down.
- Credentials are never logged.  Only their *presence* is confirmed.

Fixes applied (v2)
------------------
- Removed the erroneous ``client.FUTURES_URL = ...`` line.  Setting
  ``testnet=True`` in python-binance ≥ 1.0.17 already configures the correct
  Testnet base URLs internally.  Mutating a class-level constant on the
  instance was redundant and conceptually misleading.
- Added ``__all__`` to declare the public API explicitly.
"""

from __future__ import annotations

import os

from binance import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from dotenv import load_dotenv

from bot.logging_config import get_logger

__all__ = ["get_client", "MissingCredentialsError", "ClientConnectionError"]

# ── Module logger ──────────────────────────────────────────────────────────────

log = get_logger("client")

# ── Custom exceptions ──────────────────────────────────────────────────────────


class MissingCredentialsError(RuntimeError):
    """Raised when BINANCE_API_KEY or BINANCE_API_SECRET is absent or empty."""


class ClientConnectionError(RuntimeError):
    """Raised when the initial ping to Binance Testnet fails."""


# ── Public API ─────────────────────────────────────────────────────────────────


def get_client() -> Client:
    """
    Build and return an authenticated Binance Futures Testnet client.

    Steps
    -----
    1. Load ``.env`` (if present) into the process environment.
    2. Read ``BINANCE_API_KEY`` and ``BINANCE_API_SECRET`` from the environment.
    3. Construct a :class:`binance.Client` with ``testnet=True``, which the
       python-binance library uses to configure the correct Testnet endpoints
       automatically (REST + WebSocket).
    4. Perform a ``futures_ping()`` to verify network reachability.

    Returns
    -------
    binance.Client
        A ready-to-use client configured for USDT-M Futures Testnet.

    Raises
    ------
    MissingCredentialsError
        If either environment variable is absent or empty.
    ClientConnectionError
        If the Testnet is unreachable or rejects the credentials on ping.
    """
    load_dotenv()

    api_key, api_secret = _load_credentials()

    log.debug("Credentials loaded. Building Binance Testnet client …")

    client = _build_client(api_key, api_secret)

    _verify_connectivity(client)

    log.info("Binance Futures Testnet client ready.")
    return client


# ── Private helpers ────────────────────────────────────────────────────────────


def _load_credentials() -> tuple[str, str]:
    """
    Read API credentials from environment variables.

    Returns
    -------
    tuple[str, str]
        ``(api_key, api_secret)`` — both guaranteed non-empty strings.

    Raises
    ------
    MissingCredentialsError
        If either variable is missing or contains only whitespace.
    """
    api_key: str | None = os.getenv("BINANCE_API_KEY", "").strip() or None
    api_secret: str | None = os.getenv("BINANCE_API_SECRET", "").strip() or None

    missing: list[str] = []
    if not api_key:
        missing.append("BINANCE_API_KEY")
    if not api_secret:
        missing.append("BINANCE_API_SECRET")

    if missing:
        msg = (
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Ensure they are set in your .env file or shell environment."
        )
        log.error(msg)
        raise MissingCredentialsError(msg)

    # Safe: both values confirmed non-None above.
    return api_key, api_secret  # type: ignore[return-value]


def _build_client(api_key: str, api_secret: str) -> Client:
    """
    Instantiate :class:`binance.Client` with ``testnet=True``.

    ``testnet=True`` is the documented, version-stable way to point the
    python-binance client at Testnet endpoints for both REST and WebSocket.
    We do NOT additionally override ``client.FUTURES_URL`` — doing so would
    mutate a class-level constant in an instance-level way, which is
    misleading and unnecessary given the flag already handles routing.

    Parameters
    ----------
    api_key:
        Binance Testnet API key.
    api_secret:
        Binance Testnet API secret.

    Returns
    -------
    binance.Client

    Raises
    ------
    ClientConnectionError
        If the ``Client`` constructor itself raises unexpectedly.
    """
    try:
        return Client(
            api_key=api_key,
            api_secret=api_secret,
            testnet=True,
        )
    except Exception as exc:
        msg = f"Failed to instantiate Binance client: {exc}"
        log.exception(msg)
        raise ClientConnectionError(msg) from exc


def _verify_connectivity(client: Client) -> None:
    """
    Send a lightweight ``futures_ping`` to confirm Testnet is reachable.

    Parameters
    ----------
    client:
        The freshly built Binance client.

    Raises
    ------
    ClientConnectionError
        On any network error, API exception, or timeout.
    """
    try:
        client.futures_ping()
        log.debug("Testnet ping successful.")
    except BinanceAPIException as exc:
        msg = (
            f"Binance API rejected the ping (code={exc.code}): {exc.message}. "
            "Check that your Testnet API key and secret are correct."
        )
        log.error(msg)
        raise ClientConnectionError(msg) from exc
    except BinanceRequestException as exc:
        msg = f"Network error during connectivity check: {exc}"
        log.error(msg)
        raise ClientConnectionError(msg) from exc
    except Exception as exc:
        msg = f"Unexpected error during connectivity check: {exc}"
        log.exception(msg)
        raise ClientConnectionError(msg) from exc