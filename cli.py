"""
cli.py
──────
Typer CLI entry point for the Binance Futures Testnet Trading Bot.

Responsibilities
----------------
- Define all CLI commands and their arguments/options.
- Call the validation layer → fail fast with a clean message on bad input.
- Call the order execution layer → surface the result to the user.
- Be the single place that catches domain exceptions and converts them to
  user-facing error messages + exit codes.
- Contain zero business logic.

Commands
--------
place-order
    Place a MARKET or LIMIT order on Binance Futures Testnet.
cancel-order
    Cancel an active open order on Binance Futures Testnet.
get-balance
    Fetch the total USDT balance for the Testnet account.

Usage examples
--------------
# MARKET BUY
python cli.py place-order BTCUSDT BUY MARKET --quantity 0.01

# LIMIT SELL
python cli.py place-order ETHUSDT SELL LIMIT --quantity 0.5 --price 3500

# CANCEL ORDER
python cli.py cancel-order BTCUSDT 13167929754

# GET BALANCE
python cli.py get-balance

# Help
python cli.py --help
python cli.py place-order --help
"""

from __future__ import annotations

import sys
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from bot.client import ClientConnectionError, MissingCredentialsError, get_client
from bot.logging_config import get_logger, setup_logging
from bot.orders import OrderExecutionError, OrderResult, place_order, cancel_order
from bot.validators import ValidationError, validate_order_inputs, validate_cancel_inputs
from bot.account import AccountError, get_usdt_balance

# ── Bootstrap logging before any application code runs ────────────────────────

setup_logging()
log = get_logger("cli")

# ── Typer application ──────────────────────────────────────────────────────────

app = typer.Typer(
    name="futures-bot",
    help=(
        "Binance Futures Testnet Trading Bot.\n\n"
        "Place MARKET and LIMIT orders on USDT-M Futures Testnet via CLI."
    ),
    add_completion=False,      # disable shell completion prompts for simplicity
    pretty_exceptions_enable=False,  # we handle all exceptions ourselves
)

# Prevents Typer from collapsing the application into a single-command UI
@app.callback()
def main_callback() -> None:
    """Binance Futures Testnet Trading Bot CLI Router."""
    pass

# Rich consoles — stdout for normal output, stderr for errors.
console = Console()
err_console = Console(stderr=True, style="bold red")


# ── Commands ───────────────────────────────────────────────────────────────────


@app.command("place-order")
def place_order_command(
    symbol: str = typer.Argument(
        ...,
        help="Trading pair symbol, e.g. BTCUSDT, ETHUSDT.",
        metavar="SYMBOL",
    ),
    side: str = typer.Argument(
        ...,
        help="Order side: BUY or SELL.",
        metavar="SIDE",
    ),
    order_type: str = typer.Argument(
        ...,
        help="Order type: MARKET or LIMIT.",
        metavar="ORDER_TYPE",
    ),
    quantity: str = typer.Option(
        ...,
        "--quantity",
        "-q",
        help="Order quantity in base asset units (e.g. 0.01 for 0.01 BTC).",
    ),
    price: Optional[str] = typer.Option(
        None,
        "--price",
        "-p",
        help="Limit price (required for LIMIT orders, omit for MARKET).",
    ),
) -> None:
    """
    Place a MARKET or LIMIT futures order on Binance Testnet.

    \b
    Examples:
      # Market buy 0.01 BTC
      python cli.py place-order BTCUSDT BUY MARKET --quantity 0.01

      # Limit sell 0.5 ETH at 3500 USDT
      python cli.py place-order ETHUSDT SELL LIMIT --quantity 0.5 --price 3500
    """
    log.info(
        "CLI: place-order invoked | symbol=%s side=%s type=%s qty=%s price=%s",
        symbol,
        side,
        order_type,
        quantity,
        price,
    )

    # ── Step 1: Validate inputs ────────────────────────────────────────────────
    try:
        v_symbol, v_side, v_order_type, v_qty, v_price = validate_order_inputs(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
        )
    except ValidationError as exc:
        log.warning("Validation failed: %s", exc)
        _print_validation_error(exc)
        raise typer.Exit(code=1)

    # ── Step 2: Display order summary before sending ───────────────────────────
    _print_order_summary(v_symbol, v_side, v_order_type, v_qty, v_price)

    # ── Step 3: Build client ───────────────────────────────────────────────────
    try:
        client = get_client()
    except MissingCredentialsError as exc:
        log.error("Credential error: %s", exc)
        _print_error("Credential Error", str(exc))
        raise typer.Exit(code=2)
    except ClientConnectionError as exc:
        log.error("Connection error: %s", exc)
        _print_error("Connection Error", str(exc))
        raise typer.Exit(code=3)

    # ── Step 4: Place the order ────────────────────────────────────────────────
    try:
        result = place_order(
            client=client,
            symbol=v_symbol,
            side=v_side,
            order_type=v_order_type,
            quantity=v_qty,
            price=v_price,
        )
    except OrderExecutionError as exc:
        log.error("Order execution failed: %s", exc)
        _print_error("Order Execution Failed", str(exc))
        raise typer.Exit(code=4)

    # ── Step 5: Display result ─────────────────────────────────────────────────
    _print_order_result(result)
    log.info("CLI: place-order completed successfully | order_id=%s", result.order_id)


@app.command("cancel-order")
def cancel_order_command(
    symbol: str = typer.Argument(
        ...,
        help="Trading pair symbol, e.g. BTCUSDT, ETHUSDT.",
        metavar="SYMBOL",
    ),
    order_id: str = typer.Argument(
        ...,
        help="The unique numerical Order ID provided by Binance.",
        metavar="ORDER_ID",
    ),
) -> None:
    """
    Cancel an active open order on Binance Testnet.

    \b
    Examples:
      # Cancel an open order with ID 13167929754
      python cli.py cancel-order BTCUSDT 13167929754
    """
    log.info("CLI: cancel-order invoked | symbol=%s order_id=%s", symbol, order_id)

    # ── Step 1: Validate inputs ────────────────────────────────────────────────
    try:
        v_symbol, v_order_id = validate_cancel_inputs(symbol=symbol, order_id=order_id)
    except ValidationError as exc:
        log.warning("Validation failed: %s", exc)
        _print_validation_error(exc)
        raise typer.Exit(code=1)

    # ── Step 2: Build client ───────────────────────────────────────────────────
    try:
        client = get_client()
    except MissingCredentialsError as exc:
        log.error("Credential error: %s", exc)
        _print_error("Credential Error", str(exc))
        raise typer.Exit(code=2)
    except ClientConnectionError as exc:
        log.error("Connection error: %s", exc)
        _print_error("Connection Error", str(exc))
        raise typer.Exit(code=3)

    # ── Step 3: Execute cancellation ───────────────────────────────────────────
    try:
        result = cancel_order(
            client=client,
            symbol=v_symbol,
            order_id=v_order_id,
        )
    except OrderExecutionError as exc:
        log.error("Order cancellation failed: %s", exc)
        _print_error("Order Cancellation Failed", str(exc))
        raise typer.Exit(code=4)

    # ── Step 4: Display result ─────────────────────────────────────────────────
    _print_order_result(result)
    log.info("CLI: cancel-order completed successfully | order_id=%s", result.order_id)


@app.command("get-balance")
def get_balance_command() -> None:
    """
    Check your available USDT balance on the Binance Testnet.
    """
    log.info("CLI: get-balance invoked")

    # ── Step 1: Build client ───────────────────────────────────────────────────
    try:
        client = get_client()
    except MissingCredentialsError as exc:
        _print_error("Credential Error", str(exc))
        raise typer.Exit(code=2)
    except ClientConnectionError as exc:
        _print_error("Connection Error", str(exc))
        raise typer.Exit(code=3)

    # ── Step 2: Fetch Balance ──────────────────────────────────────────────────
    try:
        balance = get_usdt_balance(client)
    except AccountError as exc:
        log.error("Failed to retrieve balance: %s", exc)
        _print_error("Balance Check Failed", str(exc))
        raise typer.Exit(code=5)

    # ── Step 3: Display result ─────────────────────────────────────────────────
    table = Table(
        box=box.ROUNDED,
        show_header=False,
        min_width=45
    )
    table.add_column("Asset", style="dim", width=15)
    table.add_column("Balance", style="bold cyan")
    
    # Format the decimal to look like currency (e.g., 100,000.00)
    table.add_row("USDT Balance", f"{balance:,.2f} USDT")

    panel = Panel(
        table,
        title="[bold cyan]💰 Account Balance[/bold cyan]",
        border_style="cyan",
        padding=(0, 1),
    )
    
    console.print()
    console.print(panel)
    console.print()
    
    log.info("CLI: get-balance completed successfully | balance=%s", balance)


# ── Output helpers ─────────────────────────────────────────────────────────────


def _print_order_summary(
    symbol: str,
    side: str,
    order_type: str,
    quantity,
    price,
) -> None:
    """Print a clean summary of the order about to be placed."""
    side_color = "green" if side == "BUY" else "red"

    table = Table(
        title="Order Summary",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        min_width=45,
    )
    table.add_column("Field", style="dim", width=16)
    table.add_column("Value", style="bold")

    table.add_row("Symbol", symbol)
    table.add_row("Side", f"[{side_color}]{side}[/{side_color}]")
    table.add_row("Type", order_type)
    table.add_row("Quantity", str(quantity))
    table.add_row("Price", str(price) if price is not None else "Market Price")

    console.print()
    console.print(table)
    console.print()


def _print_order_result(result: OrderResult) -> None:
    """Print a formatted panel showing the full order result layout."""
    side_color = "green" if result.side == "BUY" else "red"
    
    # Dynamically handle statuses and apply distinct presentation colors
    if result.status in ("FILLED", "NEW"):
        status_color = "green"
        panel_title = "[bold green]✓ Order Placed Successfully[/bold green]"
        panel_border = "green"
    elif result.status == "CANCELED":
        status_color = "yellow"
        panel_title = "[bold yellow]✓ Order Cancelled Successfully[/bold yellow]"
        panel_border = "yellow"
    else:
        status_color = "red"
        panel_title = f"[bold red]✓ Order Status Update: {result.status}[/bold red]"
        panel_border = "red"

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        min_width=50,
    )
    table.add_column("Field", style="dim", width=20)
    table.add_column("Value", style="bold")

    table.add_row("Order ID", str(result.order_id))
    table.add_row("Client Order ID", result.client_order_id)
    table.add_row("Symbol", result.symbol)
    table.add_row("Side", f"[{side_color}]{result.side}[/{side_color}]")
    table.add_row("Type", result.order_type)
    table.add_row("Status", f"[{status_color}]{result.status}[/{status_color}]")
    table.add_row("Ordered Qty", str(result.quantity))
    table.add_row("Executed Qty", str(result.executed_qty))
    table.add_row(
        "Avg Fill Price",
        str(result.avg_price) if result.avg_price is not None else "—",
    )
    table.add_row(
        "Limit Price",
        str(result.price) if result.price is not None else "—",
    )

    panel = Panel(
        table,
        title=panel_title,
        border_style=panel_border,
        padding=(0, 1),
    )
    console.print(panel)
    console.print()


def _print_order_summary_before(symbol, side, order_type, quantity, price) -> None:
    """Alias kept for consistency; delegates to _print_order_summary."""
    _print_order_summary(symbol, side, order_type, quantity, price)


def _print_validation_error(exc: ValidationError) -> None:
    """Print a user-friendly validation failure message."""
    err_console.print(
        Panel(
            f"[bold]Field:[/bold] {exc.field}\n"
            f"[bold]Reason:[/bold] {exc.reason}",
            title="[bold red]✗ Validation Error[/bold red]",
            border_style="red",
        )
    )


def _print_error(title: str, message: str) -> None:
    """Print a generic error panel to stderr."""
    err_console.print(
        Panel(
            message,
            title=f"[bold red]✗ {title}[/bold red]",
            border_style="red",
        )
    )


# ── Entry point ────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    app()