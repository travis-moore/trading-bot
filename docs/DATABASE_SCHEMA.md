# Database Schema

The bot uses SQLite (`trading_bot.db`) with WAL journal mode for concurrent read performance. All tables are created automatically on first run. Schema migrations are applied automatically for backward compatibility.

## Tables

### positions

Active (open or pending) positions tracked by the bot.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | No | AUTOINCREMENT | Primary key |
| `symbol` | TEXT | No | | Underlying symbol (e.g., `NVDA`) |
| `local_symbol` | TEXT | No | | IB local symbol (e.g., `NVDA  250221C00150000`) |
| `con_id` | INTEGER | No | | IB contract ID (unique identifier for the specific option) |
| `strike` | REAL | No | | Option strike price |
| `expiry` | TEXT | No | | Expiration date (`YYYYMMDD` format) |
| `right` | TEXT | No | | Option type: `C` (call) or `P` (put) |
| `exchange` | TEXT | No | `SMART` | Exchange for the contract |
| `entry_price` | REAL | No | | Entry price per contract |
| `entry_time` | TEXT | No | | ISO-8601 timestamp of entry |
| `quantity` | INTEGER | No | | Number of contracts |
| `direction` | TEXT | No | | Trade direction enum value (e.g., `long_call`, `long_put`) |
| `stop_loss` | REAL | No | | Stop loss price |
| `profit_target` | REAL | No | | Take profit price |
| `pattern` | TEXT | No | | Pattern that triggered the trade |
| `strategy` | TEXT | No | `swing_trading` | Strategy instance name |
| `entry_order_id` | INTEGER | Yes | | IB order ID for the entry order |
| `order_ref` | TEXT | No | | Unique order reference (e.g., `SWINGBOT-1738600000-1`) |
| `status` | TEXT | No | `open` | Position status: `open`, `pending_fill` |
| `peak_price` | REAL | Yes | | Highest price seen since entry (for trailing stops) |
| `created_at` | TEXT | No | `datetime('now')` | Row creation timestamp |
| `updated_at` | TEXT | No | `datetime('now')` | Last update timestamp |

**Notes:**
- Rows are deleted from this table when a position is closed (moved to `trade_history`)
- `pending_fill` status means the entry order has been placed but not yet filled
- `peak_price` is updated on every scan cycle while the position is open

---

### trade_history

Permanent record of all closed trades. Positions are atomically moved here on close.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | No | AUTOINCREMENT | Primary key |
| `position_id` | INTEGER | Yes | | Original position ID from `positions` table |
| `symbol` | TEXT | No | | Underlying symbol |
| `local_symbol` | TEXT | No | | IB local symbol |
| `con_id` | INTEGER | No | | IB contract ID |
| `strike` | REAL | No | | Option strike price |
| `expiry` | TEXT | No | | Expiration date |
| `right` | TEXT | No | | Option type: `C` or `P` |
| `direction` | TEXT | No | | Trade direction |
| `pattern` | TEXT | No | | Pattern that triggered entry |
| `strategy` | TEXT | No | `swing_trading` | Strategy instance name |
| `quantity` | INTEGER | No | | Number of contracts |
| `entry_price` | REAL | No | | Entry price per contract |
| `entry_time` | TEXT | No | | Entry timestamp |
| `entry_order_id` | INTEGER | Yes | | IB entry order ID |
| `order_ref` | TEXT | No | | Order reference tag |
| `exit_price` | REAL | Yes | | Exit price per contract |
| `exit_time` | TEXT | Yes | | Exit timestamp |
| `exit_reason` | TEXT | Yes | | Why the position was closed (see below) |
| `exit_order_id` | INTEGER | Yes | | IB exit order ID |
| `pnl` | REAL | Yes | | Dollar P&L: `(exit_price - entry_price) * quantity * 100` |
| `pnl_pct` | REAL | Yes | | Percentage P&L: `(exit_price - entry_price) / entry_price * 100` |
| `created_at` | TEXT | No | `datetime('now')` | Row creation timestamp |

**Exit Reasons:**

| Reason | Description |
|--------|-------------|
| `take_profit_filled` | Take profit bracket order filled |
| `stop_loss_filled` | Stop loss bracket order filled |
| `Profit target reached` | Engine-detected TP hit (non-bracket) |
| `Stop loss hit` | Engine-detected SL hit (non-bracket) |
| `Max hold period reached` | Time limit (max_hold_days) exceeded |
| `manual_close` | Position disappeared from IB (user closed in TWS) |
| `reconciliation_not_found` | Position not in IB on startup reconciliation |
| `order_failed` | Entry order placement failed |
| `order_cancelled` | Entry order was cancelled externally |
| `order_rejected` | Entry order rejected by IB |
| `order_timeout_drift` | Entry order timed out with price drift |
| `order_timeout_no_price` | Entry order timed out, couldn't get price |
| `order_no_fills` | Pending order had zero fills |
| `unknown_fill` | Detected via IB execution cache |

---

### strategy_budgets

Tracks per-strategy budget state using a drawdown model.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `strategy_name` | TEXT | No | | **Primary key**. Strategy instance name |
| `budget` | REAL | No | | Maximum budget cap (from config) |
| `drawdown` | REAL | No | `0` | Cumulative losses (0 = no losses) |
| `committed` | REAL | No | `0` | Capital locked in open positions |
| `created_at` | TEXT | No | `datetime('now')` | Row creation timestamp |
| `updated_at` | TEXT | No | `datetime('now')` | Last update timestamp |

**Budget Model:**

```
available = budget - drawdown - committed

On trade entry:  committed += trade_cost
On trade exit:   committed -= trade_cost
                 drawdown = max(0, drawdown - pnl)
                   Win (+pnl):  drawdown decreases (recovers budget)
                   Loss (-pnl): drawdown increases (reduces budget)
```

Profits beyond the cap do not increase available budget — `drawdown` cannot go below 0.

---

### historical_bars

Cache for historical OHLCV price data fetched from IB API.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | No | AUTOINCREMENT | Primary key |
| `symbol` | TEXT | No | | Stock ticker symbol |
| `bar_size` | TEXT | No | | Bar timeframe (e.g., `15 mins`, `1 hour`) |
| `timestamp` | TEXT | No | | Bar timestamp (ISO-8601) |
| `open` | REAL | No | | Open price |
| `high` | REAL | No | | High price |
| `low` | REAL | No | | Low price |
| `close` | REAL | No | | Close price |
| `volume` | INTEGER | No | | Bar volume |
| `fetched_at` | TEXT | No | `datetime('now')` | When data was fetched from IB |

**Constraints:**
- `UNIQUE(symbol, bar_size, timestamp)` — prevents duplicate bars
- Index: `idx_hist_bars_symbol_time ON (symbol, bar_size, timestamp)`

**Cache Behavior:**
- On refresh, all existing bars for a symbol/bar_size pair are deleted and replaced
- Stale data (older than `historical_cache_ttl_hours`, default 24h) is not returned by `get_cached_bars()`

---

### signal_logs

Records every trading signal generated for opportunity utilization analysis.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | No | AUTOINCREMENT | Primary key |
| `symbol` | TEXT | No | | Underlying symbol |
| `strategy` | TEXT | No | | Strategy instance that generated the signal |
| `pattern` | TEXT | No | | Pattern name |
| `confidence` | REAL | No | | Signal confidence (0.0-1.0) |
| `price` | REAL | No | | Price at time of signal |
| `outcome` | TEXT | No | | What happened: `executed`, `rejected`, `failed_entry` |
| `timestamp` | TEXT | No | `datetime('now')` | When the signal was generated |

**Outcomes:**

| Outcome | Meaning |
|---------|---------|
| `executed` | Signal passed all checks and trade was placed |
| `rejected` | Signal did not meet trading rules (regime veto, confidence too low, etc.) |
| `failed_entry` | Signal passed rules but trade entry failed (no contract, budget exhausted, etc.) |

## Schema Migrations

The database applies migrations automatically on startup:

1. `_migrate_add_strategy_column()`: Adds `strategy` column to `positions` and `trade_history` if missing (backward compatibility with pre-strategy versions)
2. `_migrate_add_peak_price_column()`: Adds `peak_price` column to `positions` if missing (for trailing stop tracking)
3. `committed` column added to `strategy_budgets` if missing

## Maintenance

### Viewing Data

```bash
# Open database
sqlite3 trading_bot.db

# View open positions
SELECT symbol, local_symbol, strategy, entry_price, status FROM positions;

# View recent trades
SELECT local_symbol, strategy, direction, pnl, exit_reason
FROM trade_history ORDER BY exit_time DESC LIMIT 20;

# Check strategy budgets
SELECT * FROM strategy_budgets;

# Signal utilization rate
SELECT strategy,
       COUNT(*) as total,
       SUM(CASE WHEN outcome = 'executed' THEN 1 ELSE 0 END) as executed,
       ROUND(100.0 * SUM(CASE WHEN outcome = 'executed' THEN 1 ELSE 0 END) / COUNT(*), 1) as util_pct
FROM signal_logs GROUP BY strategy;
```

### Backup

```bash
# SQLite hot backup (safe while bot is running due to WAL mode)
sqlite3 trading_bot.db ".backup trading_bot_backup.db"
```

### Reset Strategy Budget

```bash
# Reset a strategy's drawdown (via bot's interactive commands or direct SQL)
sqlite3 trading_bot.db "UPDATE strategy_budgets SET drawdown = 0, committed = 0 WHERE strategy_name = 'swing_conservative';"
```
