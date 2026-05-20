"""
bot/account.py
──────────────
Account management for Binance Futures Testnet.

Responsibilities
----------------
- Fetch account balances.
- Isolate account-related exceptions from order exceptions.
"""

from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation

from binance import Client

from bot.logging_config import get_logger

__all__ = ["AccountError", "get_usdt_balance"]

log = get_logger("account")


class AccountError(RuntimeError):
    """Raised when account data cannot be retrieved from Binance."""
    pass


def get_usdt_balance(client: Client) -> Decimal:
    """
    Fetch the total USDT balance from the Futures Testnet account.

    Parameters
    ----------
    client:
        Authenticated Binance client.

    Returns
    -------
    Decimal
        The total USDT balance.

    Raises
    ------
    AccountError
        On any API or network failure.
    """
    start = time.perf_counter()
    log.debug("Fetching futures account balances...")

    try:
        balances = client.futures_account_balance()
        
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.debug("API call succeeded in %.1f ms", elapsed_ms)

        
        for asset in balances:
            if asset.get("asset") == "USDT":
                raw_balance = asset.get("balance", "0")
                return Decimal(raw_balance)
                
        # If USDT isn't found in the payload, the balance is effectively zero
        return Decimal("0")

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.error("Failed to fetch balance after %.1f ms | error=%s", elapsed_ms, exc)
        raise AccountError(f"Could not retrieve account balance: {exc}") from exc