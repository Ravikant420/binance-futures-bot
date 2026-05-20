"""
bot/validators.py
─────────────────
Pure input validation for trading order parameters.

Design principles
-----------------
- Every function is a pure validator: no I/O, no API calls, no side effects.
- All failures raise :class:`ValidationError` with a ``field`` name and a
  human-readable ``reason`` so the CLI can render precise error panels.
- ``validate_order_inputs()`` is the single public entry point for order
  placement; ``validate_cancel_inputs()`` is the entry point for cancellation.
- ``Decimal`` is used for quantity and price comparisons to avoid
  floating-point precision bugs (e.g. ``0.1 + 0.2 != 0.3`` in float).

Fixes applied (v2)
------------------
- Symbol regex broadened from ``^[A-Z]{1,10}USDT$`` to
  ``^[0-9]{0,6}[A-Z]{1,15}USDT$`` to accept real Binance symbols that
  carry a numeric prefix (e.g. 1000PEPEUSDT, 1000BONKUSDT, 1000FLOKIUSDT).
- Added ``__all__`` to declare the public API explicitly.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

__all__ = [
    "ValidationError",
    "validate_order_inputs",
    "validate_cancel_inputs",
]

# ── Custom exception ───────────────────────────────────────────────────────────


class ValidationError(ValueError):
    """
    Raised when a trading parameter fails validation.

    Attributes
    ----------
    field : str
        Name of the parameter that failed (e.g. ``"symbol"``, ``"quantity"``).
    reason : str
        Human-readable explanation of why the value was rejected.

    Examples
    --------
    >>> raise ValidationError("quantity", "must be greater than zero")
    ValidationError: [quantity] must be greater than zero
    """

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"[{field}] {reason}")


# ── Constants ──────────────────────────────────────────────────────────────────

_VALID_SIDES: frozenset[str] = frozenset({"BUY", "SELL"})
_VALID_ORDER_TYPES: frozenset[str] = frozenset({"MARKET", "LIMIT"})

# Accepts symbols with optional numeric prefix (e.g. 1000PEPEUSDT, BTCUSDT).
# Pattern: up to 6 leading digits, 1–15 uppercase letters, then "USDT".
_SYMBOL_PATTERN: re.Pattern[str] = re.compile(r"^[0-9]{0,6}[A-Z]{1,15}USDT$")

# Practical upper guard — Binance rejects absurdly large quantities anyway,
# but we fail fast locally to avoid wasting a signed API request.
_MAX_QUANTITY: Decimal = Decimal("1_000_000")


# ── Public API ─────────────────────────────────────────────────────────────────


def validate_order_inputs(
    symbol: str,
    side: str,
    order_type: str,
    quantity: str,
    price: str | None,
) -> tuple[str, str, str, Decimal, Decimal | None]:
    """
    Validate all inputs for a futures order and return normalised values.

    Parameters
    ----------
    symbol:
        Trading pair symbol as entered by the user (e.g. ``"btcusdt"``).
    side:
        Order direction as entered by the user (e.g. ``"buy"``).
    order_type:
        Order type as entered by the user (e.g. ``"market"``).
    quantity:
        Quantity string as entered by the user (e.g. ``"0.01"``).
    price:
        Price string as entered by the user for LIMIT orders.
        Must be ``None`` for MARKET orders.

    Returns
    -------
    tuple[str, str, str, Decimal, Decimal | None]
        ``(symbol, side, order_type, quantity, price)`` — all normalised and
        guaranteed valid.  ``price`` is ``None`` for MARKET orders.

    Raises
    ------
    ValidationError
        On the first validation failure encountered, with ``field`` and
        ``reason`` populated.

    Examples
    --------
    >>> validate_order_inputs("btcusdt", "buy", "market", "0.01", None)
    ('BTCUSDT', 'BUY', 'MARKET', Decimal('0.01'), None)

    >>> validate_order_inputs("btcusdt", "buy", "limit", "0.01", "30000")
    ('BTCUSDT', 'BUY', 'LIMIT', Decimal('0.01'), Decimal('30000'))
    """
    symbol = _validate_symbol(symbol)
    side = _validate_side(side)
    order_type = _validate_order_type(order_type)
    qty = _validate_quantity(quantity)
    validated_price = _validate_price(price, order_type)

    return symbol, side, order_type, qty, validated_price


def validate_cancel_inputs(
    symbol: str,
    order_id: str,
) -> tuple[str, int]:
    """
    Validate inputs for a cancel-order request.

    Parameters
    ----------
    symbol:
        Trading pair symbol as entered by the user (e.g. ``"btcusdt"``).
    order_id:
        Binance order ID as entered by the user (e.g. ``"283194212"``).

    Returns
    -------
    tuple[str, int]
        ``(symbol, order_id)`` — normalised and validated.

    Raises
    ------
    ValidationError
        If ``symbol`` is invalid or ``order_id`` is not a positive integer.
    """
    v_symbol = _validate_symbol(symbol)
    v_order_id = _validate_order_id(order_id)
    return v_symbol, v_order_id


# ── Private validators ─────────────────────────────────────────────────────────


def _validate_symbol(symbol: str) -> str:
    """
    Normalise and validate a trading pair symbol.

    - Strips surrounding whitespace.
    - Converts to uppercase.
    - Matches against ``_SYMBOL_PATTERN``.

    Returns
    -------
    str
        Uppercase, validated symbol (e.g. ``"BTCUSDT"``).

    Raises
    ------
    ValidationError
        If the symbol is empty or does not match the expected pattern.
    """
    raw = symbol.strip().upper()

    if not raw:
        raise ValidationError("symbol", "must not be empty.")

    if not _SYMBOL_PATTERN.match(raw):
        raise ValidationError(
            "symbol",
            f"'{raw}' is not a valid USDT-M futures symbol. "
            "Expected format: [digits]<BASE>USDT  "
            "(e.g. BTCUSDT, ETHUSDT, 1000PEPEUSDT).",
        )

    return raw


def _validate_side(side: str) -> str:
    """
    Normalise and validate the order side.

    Returns
    -------
    str
        Either ``"BUY"`` or ``"SELL"``.

    Raises
    ------
    ValidationError
        If the value is not ``BUY`` or ``SELL`` (case-insensitive).
    """
    raw = side.strip().upper()

    if raw not in _VALID_SIDES:
        raise ValidationError(
            "side",
            f"'{raw}' is not valid. Accepted values: BUY, SELL.",
        )

    return raw


def _validate_order_type(order_type: str) -> str:
    """
    Normalise and validate the order type.

    Returns
    -------
    str
        Either ``"MARKET"`` or ``"LIMIT"``.

    Raises
    ------
    ValidationError
        If the value is not ``MARKET`` or ``LIMIT`` (case-insensitive).
    """
    raw = order_type.strip().upper()

    if raw not in _VALID_ORDER_TYPES:
        raise ValidationError(
            "order_type",
            f"'{raw}' is not valid. Accepted values: MARKET, LIMIT.",
        )

    return raw


def _validate_quantity(quantity: str) -> Decimal:
    """
    Parse and validate the order quantity.

    Rules
    -----
    - Must be parseable as a decimal number.
    - Must be strictly greater than zero.
    - Must not exceed ``_MAX_QUANTITY`` (1,000,000).

    Returns
    -------
    Decimal
        Validated quantity.

    Raises
    ------
    ValidationError
        If the quantity is non-numeric, zero, negative, or exceeds the maximum.
    """
    raw = quantity.strip()

    try:
        qty = Decimal(raw)
    except InvalidOperation:
        raise ValidationError(
            "quantity",
            f"'{raw}' is not a valid number. Provide a positive decimal value.",
        )

    if qty <= Decimal("0"):
        raise ValidationError(
            "quantity",
            f"'{raw}' must be greater than zero.",
        )

    if qty > _MAX_QUANTITY:
        raise ValidationError(
            "quantity",
            f"'{raw}' exceeds the maximum allowed quantity of {_MAX_QUANTITY}.",
        )

    return qty


def _validate_price(price: str | None, order_type: str) -> Decimal | None:
    """
    Parse and validate the order price based on the order type.

    Rules
    -----
    - MARKET orders: ``price`` must be ``None``.  A supplied price is rejected
      to surface the user's mistake rather than silently ignoring it.
    - LIMIT orders: ``price`` must be a positive decimal number.

    Parameters
    ----------
    price:
        Raw price string from CLI, or ``None``.
    order_type:
        Normalised order type (``"MARKET"`` or ``"LIMIT"``).

    Returns
    -------
    Decimal | None
        Validated price as ``Decimal`` for LIMIT, ``None`` for MARKET.

    Raises
    ------
    ValidationError
        If the price is supplied for MARKET, absent for LIMIT, non-numeric,
        zero, or negative.
    """
    if order_type == "MARKET":
        if price is not None and price.strip():
            raise ValidationError(
                "price",
                "MARKET orders must not include a price. "
                "Remove the --price argument.",
            )
        return None

    # ── LIMIT branch ──────────────────────────────────────────────────────────
    if price is None or not price.strip():
        raise ValidationError(
            "price",
            "LIMIT orders require a price. Provide --price <value>.",
        )

    try:
        parsed = Decimal(price.strip())
    except InvalidOperation:
        raise ValidationError(
            "price",
            f"'{price}' is not a valid number. "
            "Provide a positive decimal value.",
        )

    if parsed <= Decimal("0"):
        raise ValidationError(
            "price",
            f"'{price}' must be greater than zero.",
        )

    return parsed


def _validate_order_id(order_id: str) -> int:
    """
    Parse and validate a Binance order ID.

    Rules
    -----
    - Must be parseable as a whole integer.
    - Must be strictly greater than zero.

    Returns
    -------
    int
        Validated order ID.

    Raises
    ------
    ValidationError
        If the order ID is non-numeric or not a positive integer.
    """
    raw = order_id.strip()

    try:
        parsed = int(raw)
    except ValueError:
        raise ValidationError(
            "order_id",
            f"'{raw}' is not a valid order ID. Must be a positive integer.",
        )

    if parsed <= 0:
        raise ValidationError(
            "order_id",
            f"'{raw}' must be a positive integer.",
        )

    return parsed