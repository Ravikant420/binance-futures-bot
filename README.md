# Binance Futures Testnet Trading Bot

A clean, production-style CLI trading bot that places **MARKET** and **LIMIT** orders, manages cancellations, and tracks account balances on the [Binance Futures Testnet](https://testnet.binancefuture.com) (USDT-M).

Built with Python 3.10+, `python-binance`, `Typer`, and `Rich`.

---

## Features

- Place **MARKET** and **LIMIT** orders (BUY and SELL)
- **Cancel** active open limit orders dynamically
- Fetch and format real-time **USDT account balances**
- **Pure Validation Layer:** Catch bad inputs (e.g., negative quantities) offline before making API calls
- **Resilient Error Handling:** Normalizes Binance exceptions into typed, user-friendly CLI output
- Structured logging to rotating file + console
- Clean `Rich` terminal output with colored tables and panels
- Modular architecture — each file has a single responsibility
- Credentials loaded securely from `.env` — never hardcoded
- Meaningful exit codes for CI/scripting integration
- **Automated Testing:** Lightning-fast offline unit tests via `pytest`

---

## Architecture & Design Decisions

This bot was designed with enterprise-level separation of concerns, moving beyond a simple monolithic script:

* **`cli.py` (Presentation):** Handles Typer command routing and Rich terminal output. Contains zero business logic.
* **`bot/validators.py` (Validation):** Pure functions that normalize inputs. Highly testable and entirely isolated from network dependencies.
* **`bot/client.py` (Configuration):** Manages environment variables securely and initializes the Binance client with the necessary `testnet=True` routing.
* **`bot/orders.py` & `bot/account.py` (Business Logic):** Wraps raw Binance SDK calls, handles latency tracking via `time.perf_counter()`, and repackages complex API JSON responses into immutable dataclasses.

---

## Installation

### 1. Clone the repository

git clone https://github.com/ravikant420/binance-futures-bot.git
cd binance-futures-bot

### 2. Create and activate a virtual environment

python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate

### 3. Install dependencies

pip install -r requirements.txt

---

## Environment Variable Setup

### 1. Get Testnet credentials

Visit [https://testnet.binancefuture.com](https://testnet.binancefuture.com), log in, and generate an API key and secret. *(Note: Keys generated on the main Binance exchange or Spot Testnet will fail with a `-2015` error).*

### 2. Create your `.env` file

cp .env.example .env

Edit `.env` and fill in your credentials:

BINANCE_API_KEY=your_testnet_api_key_here
BINANCE_API_SECRET=your_testnet_api_secret_here

> ⚠️ Never commit your `.env` file. It is listed in `.gitignore`.

---

## Usage

### General help

python cli.py --help

### 1. Place an Order

**MARKET BUY — Buy 0.01 BTC at current market price**
python cli.py place-order BTCUSDT BUY MARKET --quantity 0.01

**LIMIT BUY — Buy 0.5 ETH when price drops to 3000 USDT**
python cli.py place-order ETHUSDT BUY LIMIT --quantity 0.5 --price 3000

### 2. Cancel an Order

Cancel an active limit order using the numeric Order ID provided by Binance.
python cli.py cancel-order ETHUSDT 8717384053

### 3. Check Account Balance

Fetch your current Testnet USDT balance.
python cli.py get-balance

---

## Testing

The pure validation layer is backed by an automated test suite. Tests execute locally without requiring an internet connection or valid API keys.

pytest tests/

---

## Logging

All activity is written to `logs/trading.log`. The file rotates at **5 MB** and keeps up to 3 backups (`trading.log.1`, `trading.log.2`, `trading.log.3`).

### Example log output

2026-05-20 18:48:06.167 | DEBUG    | trading_bot.client | Testnet ping successful.
2026-05-20 18:48:06.167 | INFO     | trading_bot.client | Binance Futures Testnet client ready.
2026-05-20 18:48:06.168 | INFO     | trading_bot.orders | Placing LIMIT BUY order | symbol=ETHUSDT qty=0.5 price=1500
2026-05-20 18:48:06.375 | DEBUG    | trading_bot.orders | API call succeeded in 207.2 ms | raw_response={...}
2026-05-20 18:48:06.375 | INFO     | trading_bot.orders | LIMIT order placed | order_id=8717331105 status=NEW limit_price=1500.00
2026-05-20 18:48:06.380 | INFO     | trading_bot.cli    | CLI: place-order completed successfully | order_id=8717331105

---

## Error Handling & Exit Codes

These codes allow the bot to be integrated cleanly into shell scripts or CI pipelines.

| Code | Meaning | User Message |
|------|---------|--------------|
| `0` | Success | — |
| `1` | Input validation error | "Validation Error" panel |
| `2` | Missing API credentials | "Credential Error" panel |
| `3` | Binance Testnet unreachable | "Connection Error" panel |
| `4` | Order rejected by the exchange | "Order Execution Failed" panel |
| `5` | Balance check failed | "Balance Check Failed" panel |

---

## Assumptions & Notes

- Only **USDT-M** Futures Testnet is supported (not COIN-M).
- LIMIT orders use `timeInForce=GTC` (Good-Till-Cancelled).
- Quantity precision must match the symbol's step size or Binance may reject the order. Use exact decimal values as shown on the Testnet UI.

---

## Author

Ravi Kant Kumar
