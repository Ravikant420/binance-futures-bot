"""
bot — core trading logic package.

Exposes nothing at package level intentionally.
Import directly from submodules:
    from bot.client import get_client
    from bot.orders import place_market_order, place_limit_order
    from bot.validators import validate_order_inputs
    from bot.logging_config import setup_logging
"""
