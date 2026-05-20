"""
bot/orders.py
─────────────
Order execution layer for Binance Futures Testnet.

Responsibilities
----------------
- Translate validated order parameters into Binance Futures API calls.
- Log every outbound request and inbound response (at DEBUG level).
- Normalise the raw Binance response into a typed :class:`OrderResult`.
- Raise :class:`OrderExecutionError` for every failure so callers never
  handle raw Binance exceptions.

Design notes
------------
- This module is pure business logic: no CLI I/O, no credential loading.
- ``place_order()`` is the single public dispatcher for placement.
- ``cancel_order()`` is the public entry point for cancellation.
- Individual order-type functions are private helpers.
- ``Decimal`` is used throughout to preserve numeric precision.
- ``time.perf_counter()`` measures API round-trip latency for logging.

Fixes applied (v2)
------------------
- Added ``from decimal import Decimal, InvalidOperation`` — ``InvalidOperation``
  was missing in the previous version but referenced in ``_parse_response``,
  causing a ``NameError`` at runtime.
- ``_to_decimal`` promoted from nested function to module-level private
  helper — it has no closure dependencies and was re-created on every
  ``_parse_response`` call unnecessarily.
- ``elapsed_ms`` de-duplicated: computed once in a ``finally`` block instead
  of being repeated in every ``except`` branch.
- ``_execute_api_call`` now carries a proper ``Callable`` type annotation
  instead of a bare ``# type: ignore``.
- ``_parse_response`` wrapped in ``try/except (KeyError, InvalidOperation)``
  to handle unexpected or malformed Binance response payloads gracefully.
- Added ``cancel_order()`` for the cancel-order CLI command.
- Added ``__all__`` to declare the public API explicitly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from binance import Client
from binance.exceptions import (
    BinanceAPIException,
    BinanceOrderException,
    BinanceRequestException,
)

from bot.logging_config import get_logger

__all__ = [
    "OrderResult",
    "OrderExecutionError",
    "place_order",
    "cancel_order",
]

# ── Module logger ──────────────────────────────────────────────────────────────

log = get_logger("orders")


# ── Data transfer object ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class OrderResult:
    """
    Normalised, immutable representation of a Binance Futures order.

    Used for both placed and cancelled orders — the Binance API returns the
    same top-level fields for both operations.

    Attributes
    ----------
    order_id : int
        Binance-assigned unique order identifier.
    client_order_id : str
        Client-side order identifier (assigned by Binance if not overridden).
    symbol : str
        Trading pair (e.g. ``"BTCUSDT"``).
    side : str
        ``"BUY"`` or ``"SELL"``.
    order_type : str
        ``"MARKET"``, ``"LIMIT"``, etc.
    status : str
        Binance order status string (e.g. ``"FILLED"``, ``"NEW"``,
        ``"CANCELED"``).
    quantity : Decimal
        Original order quantity (``origQty``).
    executed_qty : Decimal
        Quantity actually executed at the time of the response.
    avg_price : Decimal | None
        Volume-weighted average execution price; ``None`` if not yet filled
        or if the field is absent / zero in the response.
    price : Decimal | None
        Limit price; ``None`` for MARKET orders or absent fields.
    raw : dict
        Complete unmodified Binance API response for audit purposes.
        Excluded from ``repr()`` to keep log lines readable.
    """

    order_id: int
    client_order_id: str
    symbol: str
    side: str
    order_type: str
    status: str
    quantity: Decimal
    executed_qty: Decimal
    avg_price: Decimal | None
    price: Decimal | None
    raw: dict = field(repr=False)


# ── Custom exception ───────────────────────────────────────────────────────────


class OrderExecutionError(RuntimeError):
    """
    Raised when any Binance API call fails during order operations.

    Attributes
    ----------
    api_code : int | None
        Binance error code from the response body, if available.
    api_message : str | None
        Binance error message from the response body, if available.
    """

    def __init__(
        self,
        message: str,
        *,
        api_code: int | None = None,
        api_message: str | None = None,
    ) -> None:
        self.api_code = api_code
        self.api_message = api_message
        detail = f" (Binance code={api_code}: {api_message})" if api_code else ""
        super().__init__(f"{message}{detail}")


# ── Public API ─────────────────────────────────────────────────────────────────


def place_order(
    client: Client,
    symbol: str,
    side: str,
    order_type: str,
    quantity: Decimal,
    price: Decimal | None = None,
) -> OrderResult:
    """
    Place a MARKET or LIMIT futures order and return a normalised result.

    This is the single public entry point for order placement. It dispatches
    to the appropriate private function based on ``order_type``.

    Parameters
    ----------
    client:
        Authenticated Binance client (from :func:`bot.client.get_client`).
    symbol:
        Validated uppercase trading pair (e.g. ``"BTCUSDT"``).
    side:
        ``"BUY"`` or ``"SELL"``.
    order_type:
        ``"MARKET"`` or ``"LIMIT"``.
    quantity:
        Positive decimal quantity.
    price:
        Required for ``"LIMIT"`` orders; must be ``None`` for ``"MARKET"``.

    Returns
    -------
    OrderResult
        Normalised, immutable order result.

    Raises
    ------
    OrderExecutionError
        On any Binance API error, network failure, or unexpected exception.
    ValueError
        If ``order_type`` is not ``"MARKET"`` or ``"LIMIT"`` — this is a
        programming error; validators should catch this before it reaches here.
    """
    log.info(
        "Placing %s %s order | symbol=%s qty=%s price=%s",
        order_type,
        side,
        symbol,
        quantity,
        price if price is not None else "N/A",
    )

    if order_type == "MARKET":
        return _place_market_order(client, symbol, side, quantity)

    if order_type == "LIMIT":
        if price is None:
            raise ValueError("price must not be None for LIMIT orders.")
        return _place_limit_order(client, symbol, side, quantity, price)

    raise ValueError(f"Unsupported order_type: '{order_type}'.")


def cancel_order(
    client: Client,
    symbol: str,
    order_id: int,
) -> OrderResult:
    """
    Cancel an open futures order and return a normalised result.

    Calls ``client.futures_cancel_order`` and normalises the Binance
    response through the shared ``_parse_response`` pipeline, so the
    returned :class:`OrderResult` has the same shape as a placed order
    (with ``status="CANCELED"``).

    Parameters
    ----------
    client:
        Authenticated Binance client (from :func:`bot.client.get_client`).
    symbol:
        Validated uppercase trading pair (e.g. ``"BTCUSDT"``).
    order_id:
        Binance-assigned order ID of the open order to cancel.

    Returns
    -------
    OrderResult
        Normalised result with ``status="CANCELED"``.

    Raises
    ------
    OrderExecutionError
        On any Binance API error, network failure, or unexpected exception.
        Notable Binance error codes:
        - ``-2011``: Unknown order — the order ID does not exist or is already
          filled/cancelled.
        - ``-1121``: Invalid symbol.
    """
    log.info(
        "Cancelling order | symbol=%s order_id=%s",
        symbol,
        order_id,
    )

    params: dict[str, Any] = {
        "symbol": symbol,
        "orderId": order_id,
    }

    log.debug("Cancel order params → %s", params)

    raw = _execute_api_call(client.futures_cancel_order, **params)

    result = _parse_response(raw)
    log.info(
        "Order cancelled | order_id=%s symbol=%s status=%s",
        result.order_id,
        result.symbol,
        result.status,
    )
    return result


# ── Private order executors ────────────────────────────────────────────────────


def _place_market_order(
    client: Client,
    symbol: str,
    side: str,
    quantity: Decimal,
) -> OrderResult:
    """
    Submit a MARKET order to Binance Futures Testnet.

    Parameters
    ----------
    client:
        Authenticated Binance client.
    symbol:
        Uppercase trading pair.
    side:
        ``"BUY"`` or ``"SELL"``.
    quantity:
        Positive decimal quantity.

    Returns
    -------
    OrderResult

    Raises
    ------
    OrderExecutionError
        On any API or network failure.
    """
    params: dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "type": Client.FUTURE_ORDER_TYPE_MARKET,
        "quantity": str(quantity),
    }

    log.debug("MARKET order params → %s", params)

    raw = _execute_api_call(client.futures_create_order, **params)

    result = _parse_response(raw)
    log.info(
        "MARKET order placed | order_id=%s status=%s executed_qty=%s avg_price=%s",
        result.order_id,
        result.status,
        result.executed_qty,
        result.avg_price,
    )
    return result


def _place_limit_order(
    client: Client,
    symbol: str,
    side: str,
    quantity: Decimal,
    price: Decimal,
) -> OrderResult:
    """
    Submit a LIMIT order to Binance Futures Testnet.

    Uses ``timeInForce=GTC`` (Good-Till-Cancelled) by default, which is
    the most common expectation for a limit order CLI tool.

    Parameters
    ----------
    client:
        Authenticated Binance client.
    symbol:
        Uppercase trading pair.
    side:
        ``"BUY"`` or ``"SELL"``.
    quantity:
        Positive decimal quantity.
    price:
        Positive limit price.

    Returns
    -------
    OrderResult

    Raises
    ------
    OrderExecutionError
        On any API or network failure.
    """
    params: dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "type": Client.FUTURE_ORDER_TYPE_LIMIT,
        "quantity": str(quantity),
        "price": str(price),
        "timeInForce": Client.TIME_IN_FORCE_GTC,
    }

    log.debug("LIMIT order params → %s", params)

    raw = _execute_api_call(client.futures_create_order, **params)

    result = _parse_response(raw)
    log.info(
        "LIMIT order placed | order_id=%s status=%s limit_price=%s",
        result.order_id,
        result.status,
        result.price,
    )
    return result


# ── Internal helpers ───────────────────────────────────────────────────────────


def _execute_api_call(
    api_fn: Callable[..., dict[str, Any]],
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Execute a Binance API callable, measure latency, and translate exceptions.

    Latency is measured in a ``finally`` block so it is always logged
    regardless of success or failure — eliminating the previous pattern of
    re-computing ``elapsed_ms`` inside each ``except`` branch.

    Parameters
    ----------
    api_fn:
        A callable from the Binance client
        (e.g. ``client.futures_create_order``,
        ``client.futures_cancel_order``).
    **kwargs:
        Arguments forwarded verbatim to ``api_fn``.

    Returns
    -------
    dict[str, Any]
        Raw JSON response body from Binance.

    Raises
    ------
    OrderExecutionError
        Wrapping :class:`~binance.exceptions.BinanceOrderException`,
        :class:`~binance.exceptions.BinanceAPIException`,
        :class:`~binance.exceptions.BinanceRequestException`, or any
        unexpected :class:`Exception`.
    """
    start = time.perf_counter()
    elapsed_ms = 0.0

    try:
        response: dict[str, Any] = api_fn(**kwargs)
        log.debug(
            "API call succeeded in %.1f ms | raw_response=%s",
            (time.perf_counter() - start) * 1_000,
            response,
        )
        return response

    except BinanceOrderException as exc:
        # BinanceOrderException is a subclass of BinanceAPIException;
        # it must be caught FIRST to avoid the parent clause swallowing it.
        raise OrderExecutionError(
            "Order was rejected by the exchange.",
            api_code=int(exc.code),
            api_message=exc.message,
        ) from exc

    except BinanceAPIException as exc:
        raise OrderExecutionError(
            "Binance API returned an error.",
            api_code=int(exc.code),
            api_message=exc.message,
        ) from exc

    except BinanceRequestException as exc:
        raise OrderExecutionError(
            f"Network error while contacting Binance: {exc}"
        ) from exc

    except Exception as exc:
        log.exception("Unexpected error in API call")
        raise OrderExecutionError(
            f"Unexpected error during API call: {exc}"
        ) from exc

    finally:
        # Always log the wall-clock time, even on failure.
        elapsed_ms = (time.perf_counter() - start) * 1_000
        log.debug("API call completed in %.1f ms", elapsed_ms)


def _to_decimal_or_none(value: str | None) -> Decimal | None:
    """
    Convert a string to :class:`Decimal`, returning ``None`` for absent or
    zero-valued strings.

    This is a module-level helper (not nested) because it has no closure
    dependencies and is reusable across multiple response parsers.

    Parameters
    ----------
    value:
        String representation of a decimal number, or ``None``.

    Returns
    -------
    Decimal | None
        The parsed value, or ``None`` if the input is ``None`` or resolves
        to ``Decimal("0")``.
    """
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None
    return parsed if parsed != Decimal("0") else None


def _parse_response(raw: dict[str, Any]) -> OrderResult:
    """
    Translate a raw Binance Futures API response into an :class:`OrderResult`.

    Compatible with responses from both ``futures_create_order`` and
    ``futures_cancel_order`` — Binance uses the same top-level schema for
    both.

    Binance Futures response shape (relevant fields)::

        {
          "orderId":      123456789,
          "clientOrderId": "abc123",
          "symbol":       "BTCUSDT",
          "side":         "BUY",
          "type":         "LIMIT",
          "status":       "NEW",          # "FILLED" | "CANCELED" | ...
          "origQty":      "0.01",
          "executedQty":  "0.00",
          "avgPrice":     "0.00",         # "0.00" when not filled
          "price":        "30000.00",     # "0" for MARKET orders
          ...
        }

    Parameters
    ----------
    raw:
        Unmodified dict returned by the Binance SDK.

    Returns
    -------
    OrderResult
        Fully populated, immutable result object.

    Raises
    ------
    OrderExecutionError
        If required keys are missing or a numeric field cannot be parsed —
        guards against unexpected API schema changes.
    """
    try:
        return OrderResult(
            order_id=int(raw["orderId"]),
            client_order_id=str(raw.get("clientOrderId", "")),
            symbol=str(raw["symbol"]),
            side=str(raw["side"]),
            order_type=str(raw["type"]),
            status=str(raw["status"]),
            quantity=Decimal(raw["origQty"]),
            executed_qty=Decimal(raw.get("executedQty", "0")),
            avg_price=_to_decimal_or_none(raw.get("avgPrice")),
            price=_to_decimal_or_none(raw.get("price")),
            raw=raw,
        )
    except (KeyError, InvalidOperation) as exc:
        log.error(
            "Failed to parse Binance response: %s | raw=%s",
            exc,
            raw,
        )
        raise OrderExecutionError(
            f"Unexpected response format from Binance: missing or invalid field '{exc}'. "
            "This may indicate an API schema change — check logs for the raw response."
        ) from exc