import pytest
from decimal import Decimal
from bot.validators import validate_order_inputs, ValidationError

def test_valid_market_order():
    """Test that a standard MARKET order passes validation."""
    symbol, side, order_type, qty, price = validate_order_inputs(
        symbol="BTCUSDT",
        side="buy",          # Testing lowercase conversion
        order_type="market", # Testing lowercase conversion
        quantity="0.01",
        price=None
    )
    
    assert symbol == "BTCUSDT"
    assert side == "BUY"
    assert order_type == "MARKET"
    assert qty == Decimal("0.01")
    assert price is None

def test_valid_limit_order():
    """Test that a standard LIMIT order passes validation."""
    symbol, side, order_type, qty, price = validate_order_inputs(
        symbol="ETHUSDT",
        side="SELL",
        order_type="LIMIT",
        quantity="1.5",
        price="3000"
    )
    
    assert symbol == "ETHUSDT"
    assert side == "SELL"
    assert order_type == "LIMIT"
    assert qty == Decimal("1.5")
    assert price == Decimal("3000")

def test_invalid_symbol():
    """Test that badly formatted symbols are rejected."""
    with pytest.raises(ValidationError) as exc_info:
        validate_order_inputs("BITCOIN", "BUY", "MARKET", "1", None)
    
    assert exc_info.value.field == "symbol"

def test_missing_limit_price():
    """Test that LIMIT orders reject missing prices."""
    with pytest.raises(ValidationError) as exc_info:
        validate_order_inputs("BTCUSDT", "BUY", "LIMIT", "1", None)
    
    assert exc_info.value.field == "price"
    assert "require a price" in exc_info.value.reason

def test_market_with_price():
    """Test that MARKET orders reject unnecessary prices."""
    with pytest.raises(ValidationError) as exc_info:
        validate_order_inputs("BTCUSDT", "BUY", "MARKET", "1", "50000")
    
    assert exc_info.value.field == "price"
    assert "must not include a price" in exc_info.value.reason

def test_negative_quantity():
    """Test that quantities must be greater than zero."""
    with pytest.raises(ValidationError) as exc_info:
        validate_order_inputs("BTCUSDT", "BUY", "MARKET", "-0.5", None)
    
    assert exc_info.value.field == "quantity"