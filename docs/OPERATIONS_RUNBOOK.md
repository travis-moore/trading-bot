# Operations Runbook

Day-to-day operational procedures for running the Swing Trading Bot.

---

## Daily Operations

### Morning Startup (Before Market Open)

1. **Start TWS or IB Gateway** and log in
2. **Verify API connection** — check that API is enabled and port is correct
3. **Start the bot**:
   ```bash
   python main.py
   ```
4. **Verify startup**:
   - Check for "Connected to IB" in logs
   - Run `/status` to confirm account value and connection
   - Run `/strategies` to confirm all desired strategies are enabled
   - Run `/budgets` to check available budget per strategy
5. **Check market regime**: `/status` shows current regime (Bull Trend, Bear Trend, Range Bound, High Chaos)

### During Market Hours

- **Monitor positions**: `/positions` shows open positions with live P&L
- **Monitor performance**: `/pnl` for strategy-level P&L breakdown
- **Check for alerts**: Discord notifications for trades, errors, and loss limits
- **Emergency response**: If needed, see [Incident Response](INCIDENT_RESPONSE.md)

### End of Day

1. The bot handles most EOD tasks automatically:
   - Positions are held overnight (unless `max_hold_days` is 1)
   - Trailing stops remain active server-side via IB
2. **Review the day**:
   ```
   /metrics            # Overall performance
   /trades             # Recent trades
   /pnl                # P&L by strategy
   /budgets            # Budget status
   ```
3. **Optional**: Export reports
   ```
   /export trades      # CSV of all trades
   /export report      # Full performance report
   ```
4. **Stop the bot** if not running overnight: `/quit` or Ctrl+C

### Overnight / Weekend

- The bot can run 24/7 but will not enter trades outside market hours (if `trading_hours_only: true`)
- TWS may auto-log out overnight — consider using IB Gateway for unattended operation
- Bracket orders (stop loss / take profit) remain active on IB's servers even if the bot is stopped

---

## Strategy Management

### Enable / Disable a Strategy

```
/disable swing_aggressive     # Stop new signals, existing positions drain naturally
/enable swing_aggressive      # Resume generating signals
```

Disabling a strategy does **not** close existing positions. They continue to be managed (trailing stops, TP/SL) until they exit naturally.

### Reload Strategies After Code Changes

```
/reload                       # Reload all strategies from disk
/reload swing_trading         # Reload a specific strategy
```

Hot reload allows code changes without restarting the bot. If reload fails (syntax error), the previous version continues running.

### Add a New Strategy

1. Create the strategy file in `strategies/` (use `template_strategy.py` as a starting point)
2. Add configuration to `config.yaml`
3. Run `/discover` to find the new file
4. Run `/enable <name>` to activate it

### Discover New Strategy Files

```
/discover                     # Lists .py files in strategies/ not yet loaded
```

---

## Budget Management

### View Budget Status

```
/budgets
```

Shows per-strategy: budget cap, drawdown, committed capital, and available budget.

### Understanding the Budget Model

```
available = budget - drawdown - committed

- Enter trade:  committed += trade_cost
- Exit winner:  committed -= trade_cost, drawdown decreases (recovers budget)
- Exit loser:   committed -= trade_cost, drawdown increases (less budget available)
```

Drawdown cannot go below 0. Profits beyond the budget cap do not increase available budget.

### Reset a Strategy's Budget

If a strategy's budget is exhausted from losses and you want to reset it:

```bash
sqlite3 trading_bot.db "UPDATE strategy_budgets SET drawdown = 0, committed = 0 WHERE strategy_name = 'swing_conservative';"
```

> **Warning**: Only reset budgets when there are no open positions for that strategy. Check `/positions` first.

Alternatively, increase the `budget` value in `config.yaml` and restart.

---

## Database Operations

### Backup

SQLite with WAL mode supports safe hot backups while the bot is running:

```bash
sqlite3 trading_bot.db ".backup trading_bot_backup.db"
```

Consider scheduling daily backups before market open.

### View Open Positions (SQL)

```bash
sqlite3 trading_bot.db "SELECT symbol, local_symbol, strategy, entry_price, status FROM positions;"
```

### View Recent Trade History

```bash
sqlite3 trading_bot.db "SELECT local_symbol, strategy, direction, pnl, exit_reason FROM trade_history ORDER BY exit_time DESC LIMIT 20;"
```

### Check Signal Utilization

```bash
sqlite3 trading_bot.db "
SELECT strategy,
       COUNT(*) as total,
       SUM(CASE WHEN outcome = 'executed' THEN 1 ELSE 0 END) as executed,
       ROUND(100.0 * SUM(CASE WHEN outcome = 'executed' THEN 1 ELSE 0 END) / COUNT(*), 1) as util_pct
FROM signal_logs GROUP BY strategy;
"
```

### Purge Old Historical Bar Cache

The historical bar cache grows over time. To clear stale data:

```bash
sqlite3 trading_bot.db "DELETE FROM historical_bars WHERE fetched_at < datetime('now', '-7 days');"
```

---

## Performance Analysis

### Execution Quality Report

Requires `pandas`. Analyzes all market snapshots for slippage and latency:

```bash
python snapshot_analyzer.py --report
```

### Single Trade Slippage Analysis

```bash
python snapshot_analyzer.py SWINGBOT-1738600000-1
```

Shows:
- Entry vs fill price slippage
- Order book state at signal and execution
- Execution latency
- Spread at time of trade

### Export Data for External Analysis

```
/export trades          # Exports to CSV with all trade history
/export report          # Exports summary report CSV
```

---

## Configuration Changes

### Changes That Take Effect Immediately

- `/enable <name>` / `/disable <name>` — strategy state
- `/reload` — strategy code (hot reload)

### Changes That Require Restart

- `ib_connection` settings (host, port, client_id)
- `safety` settings
- `market_regime` settings
- `sector_rotation` settings
- Adding/removing strategy instances in config
- `operation.log_level`

### Safe Config Change Process

1. Review the change in `config.yaml`
2. Stop the bot gracefully: `/quit`
3. Verify no pending orders: check logs for clean shutdown message
4. Apply the config change
5. Restart: `python main.py`
6. Verify with `/status` and `/strategies`

---

## Monitoring Checklist

### What to Watch

| Metric | Check With | Warning Sign |
|--------|-----------|--------------|
| Open positions | `/positions` | Positions stuck for many days |
| Daily P&L | `/pnl` | Approaching `max_daily_loss` |
| Budget available | `/budgets` | Budget nearly exhausted |
| Market regime | `/status` | Unexpected regime (e.g., High Chaos) |
| Signal utilization | SQL query | Very low utilization (<5%) |
| Win rate | `/metrics` | Sustained win rate below 30% |
| Profit factor | `/metrics` | Profit factor below 1.0 |

### Discord Alerts to Watch For

| Alert | Urgency | Action |
|-------|---------|--------|
| `STRATEGY PAUSED: hit daily loss limit` | Medium | Review losing trades. Strategy resumes next day |
| `ORDER FAILED` | Medium | Check logs for cause. May need config adjustment |
| `ORDER REJECTED` | Medium | IB rejected the order. Check account permissions/margin |
| `PERFORMANCE ALERT: Daily loss limit reached` | High | Global daily loss hit. All trading paused until next day |
| `CRITICAL ERROR: Bot crashed!` | Critical | Restart the bot. Check logs for root cause |

---

## Logs

### Log Location

- **Console**: Real-time output
- **File**: `trading_bot.log` (rotates daily)

### Useful Log Patterns to Search

```bash
# Find all trade entries
grep "TRADE ENTERED" trading_bot.log

# Find all exits
grep "POSITION CLOSED" trading_bot.log

# Find errors
grep "ERROR" trading_bot.log

# Find a specific symbol
grep "NVDA" trading_bot.log

# Find regime changes
grep "Market regime" trading_bot.log
```

### Adjusting Log Verbosity

In `config.yaml`:
```yaml
operation:
  log_level: "DEBUG"    # Maximum detail (very verbose)
  log_level: "INFO"     # Normal operation (recommended)
  log_level: "WARNING"  # Only warnings and errors
  log_level: "ERROR"    # Only errors
```
