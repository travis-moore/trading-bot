# API Reference

## Current State

The bot **does not currently expose an HTTP/REST/WebSocket API**. It operates as a standalone terminal application with two external interfaces:

1. **Interactive Terminal Commands** — typed directly into the running terminal
2. **Discord Webhook Notifications** — outbound-only alerts

All interaction with the trading system happens through the terminal commands documented below, or by directly querying the SQLite database.

---

## Interactive Command API

These commands are typed into the terminal while the bot is running. They are processed in the main loop between scan cycles.

### Bot Control

| Command | Description | Output |
|---------|-------------|--------|
| `/help` | List all available commands | Help text |
| `/status` | Show uptime, scan count, open positions, account value, P&L | Status block |
| `/quit` or `/stop` | Graceful shutdown | Stops main loop |

### Position Management

| Command | Description | Output |
|---------|-------------|--------|
| `/positions` | Show all open positions with live P&L, strategy, SL/TP, days held | Position table |

### Strategy Management

| Command | Description | Output |
|---------|-------------|--------|
| `/strategies` | List all loaded strategies with enabled/disabled status | Strategy table |
| `/enable <name>` | Enable a loaded strategy (or load+enable if not loaded) | Confirmation |
| `/disable <name>` | Disable a strategy (stops new signals, existing positions drain) | Confirmation |
| `/reload` | Hot-reload all strategies from disk | Success/failure count |
| `/reload <name>` | Reload a specific strategy | Success/failure |
| `/discover` | Find new strategy files not yet loaded | List of new files |

### Performance & Reporting

| Command | Description | Output |
|---------|-------------|--------|
| `/pnl` | P&L breakdown by strategy (wins, losses, total) | P&L table |
| `/budgets` | Show per-strategy budget, committed, drawdown, available | Budget table |
| `/metrics` | Overall performance metrics (win rate, profit factor, etc.) | Metrics block |
| `/metrics <SYMBOL>` | Performance metrics filtered by symbol | Metrics block |
| `/trades` | Show last 20 trades | Trade table |
| `/trades <SYMBOL>` | Filter trades by symbol | Trade table |
| `/trades winners` | Show only profitable trades | Trade table |
| `/trades losers` | Show only losing trades | Trade table |
| `/trades <SYMBOL> winners 50` | Combined filters with custom limit | Trade table |
| `/export trades` | Export trade history to CSV file | File path |
| `/export report` | Export full performance report to CSV | File path |

### Notifications

| Command | Description |
|---------|-------------|
| `/test_notify` | Send a test message to the configured Discord webhook |

---

## Discord Notification API (Outbound)

The bot sends notifications to Discord via webhook. These are outbound-only (the bot does not receive commands from Discord).

### Message Types

| Event | Format | Example |
|-------|--------|---------|
| Bot Start | Text | `Swing Trading Bot Started` |
| Bot Stop | Text | `Swing Trading Bot Stopped` |
| Trade Fill | Rich Embed | Symbol, direction, fill price, time |
| Order Failed | Text | `ORDER FAILED: Bracket order failed for NVDA...` |
| Order Rejected | Text | `ORDER REJECTED: NVDA...` |
| Strategy Paused | Text | `STRATEGY PAUSED: Strategy 'scalp_quick' paused: hit daily loss limit` |
| Daily Loss Alert | Text | `PERFORMANCE ALERT: Daily loss limit reached` |
| Bot Crash | Text | `CRITICAL ERROR: Bot crashed! <error message>` |

### Trade Alert Embed

```json
{
  "title": "Trade Alert: NVDA 250221C150",
  "description": "LONG_CALL triggered by rejection_at_support",
  "color": 5763719,
  "fields": [
    {"name": "Price", "value": "$2.45", "inline": true},
    {"name": "Time", "value": "10:32:15", "inline": true}
  ],
  "footer": {"text": "Swing Trading Bot"}
}
```

Color: `5763719` (green) for calls/long, `15548997` (red) for puts/short.

---

## Python Internal API

### TradeDatabase

Key methods available for direct use or scripting:

```python
from trade_db import TradeDatabase
db = TradeDatabase("trading_bot.db")

# Query trades with flexible filtering
trades = db.query_trades(
    symbol="NVDA",
    strategy="swing_conservative",
    start_date="2026-01-01",
    winners_only=True,
    limit=50
)

# Performance metrics
metrics = db.get_performance_metrics(strategy="swing_conservative")
# Returns: total_trades, winners, losers, win_rate, total_pnl, avg_pnl,
#          profit_factor, avg_hold_hours, best_trade, worst_trade

# Daily P&L with cumulative tracking
daily = db.get_daily_pnl(start_date="2026-01-01")
# Returns: [{date, trade_count, wins, losses, daily_pnl, cumulative_pnl}]

# Frequency analysis
freq = db.get_frequency_analysis(strategy="swing_conservative")
# Returns: trades_per_day, trades_per_hour, opportunity_utilization_pct

# Export to CSV
db.export_trades_to_csv("trades.csv", strategy="swing_conservative")
db.export_performance_report("report.csv")

# Budget management
budget = db.get_strategy_budget("swing_conservative")
# Returns: {budget, drawdown, committed, available}
db.recalculate_budget_from_history("swing_conservative", 2000.0)
```

### SnapshotAnalyzer

```python
from snapshot_analyzer import SnapshotAnalyzer
analyzer = SnapshotAnalyzer("snapshots")

# Analyze single trade slippage
analyzer.analyze_trade_slippage("SWINGBOT-1738600000-1")

# Generate global execution report (requires pandas)
analyzer.generate_global_report()
```

### Command Line

```bash
# Run the bot
python main.py

# Analyze a specific trade's slippage
python snapshot_analyzer.py SWINGBOT-1738600000-1

# Generate execution quality report
python snapshot_analyzer.py --report
```

---

## Should We Add an HTTP API?

### Recommendation: Not Now, but Consider Later

The bot currently serves a single-operator use case well. An HTTP API would add complexity, security surface area, and a dependency (Flask/FastAPI) without clear immediate benefit.

### When an API Would Be Valuable

| Use Case | Benefit |
|----------|---------|
| **Web Dashboard** | Real-time position monitoring, P&L charts from a browser |
| **Mobile Alerts** | Query positions/P&L from a phone without terminal access |
| **Multi-Bot Coordination** | Central controller managing multiple bot instances |
| **External Integrations** | Connect to TradingView, custom alerting systems, or risk dashboards |
| **Remote Management** | Enable/disable strategies, adjust config without SSH access |

### Suggested API Endpoints (If Implemented)

```
GET  /api/status            # Bot status, uptime, account value
GET  /api/positions         # Open positions with live P&L
GET  /api/strategies        # Strategy status and config
POST /api/strategies/:name/enable   # Enable a strategy
POST /api/strategies/:name/disable  # Disable a strategy
GET  /api/pnl               # P&L by strategy
GET  /api/metrics            # Performance metrics
GET  /api/trades             # Trade history with filters
GET  /api/budgets            # Strategy budget status
POST /api/emergency-stop     # Activate emergency stop
GET  /api/health             # Health check endpoint
```

### Implementation Notes

- Use FastAPI for async compatibility with `ib_insync`
- Add API key authentication (at minimum)
- Read-only endpoints first, write endpoints later
- WebSocket for real-time position/price streaming
- Run on a separate thread or process to not block the main trading loop
