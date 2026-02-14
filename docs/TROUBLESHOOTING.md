# Common Issues & Troubleshooting

## Connection Issues

### "Failed to connect to IB" / Connection Refused

**Symptoms**: Bot fails on startup with connection error.

**Causes & Fixes**:

1. **TWS/Gateway not running** — Start TWS or IB Gateway and log in
2. **Wrong port** — Verify `ib_connection.port` in `config.yaml` matches TWS settings:
   - TWS Paper: `7497`, TWS Live: `7496`
   - Gateway Paper: `4002`, Gateway Live: `4001`
3. **API not enabled** — In TWS: Edit > Global Configuration > API > Settings > Check "Enable ActiveX and Socket Clients"
4. **Trusted IP missing** — Add `127.0.0.1` to Trusted IPs in TWS API settings
5. **Another client connected** — Each `client_id` can only have one connection. Change `client_id` or disconnect the other client
6. **Firewall blocking** — Ensure your firewall allows connections on the API port

### Connection Drops Mid-Session

**Symptoms**: Bot loses connection during market hours.

**Fixes**:
- TWS has an auto-logout timer. Disable it: Edit > Global Configuration > Lock and Exit > Never auto-logoff
- IB Gateway is more stable for long-running sessions
- The bot will attempt to reconnect automatically

---

## Market Data Issues

### "No market depth data" / Empty Order Book

**Symptoms**: Strategies receive no signals because depth data is empty.

**Causes & Fixes**:

1. **No Level 2 subscription** — Market depth requires a paid subscription (e.g., NASDAQ TotalView ~$15/mo). Check your subscriptions in IB Account Management
2. **Market closed** — Level 2 data is only available during market hours
3. **Symbol not subscribed** — Verify the symbol is listed in at least one enabled strategy's `symbols` list
4. **Market data farm connection** — Check TWS for "Market data farm connection is broken" messages. Usually resolves on its own

### "Could not get option price" / No Contract Found

**Symptoms**: Bot finds a signal but can't execute because no option contract is available.

**Causes & Fixes**:

1. **Illiquid options** — The option chain for the target strike/DTE may be illiquid. Try:
   - Widening DTE range: increase `max_dte`, decrease `min_dte`
   - Adjusting strike: change `call_strike_pct` / `put_strike_pct` closer to ATM
2. **No matching expiry** — The symbol may not have weekly options. Adjust DTE range
3. **After hours** — Option prices may not be available outside market hours
4. **Market data permissions** — You may need US Securities options data permissions in IB

### Only 3 Symbols Getting Data (Market Data Limits)

**Symptoms**: Some symbols get data while others don't. IB error about too many market data lines.

**Fix**: Set `sequential_scanning: true` in `ib_connection`. This scans symbols one at a time instead of subscribing to all simultaneously. IB paper accounts often have a limit of 3 concurrent Level 2 streams.

---

## Trading Issues

### "Maximum positions reached"

**Symptoms**: Bot logs "Maximum positions reached" and skips signals.

**Fixes**:
- Increase `max_positions` in the strategy config or `risk_management` section
- Wait for existing positions to exit
- Check `/positions` to see current open positions

### "Budget exhausted" / "Insufficient budget"

**Symptoms**: Strategy has no available budget to enter trades.

**Fixes**:
- Check budget status: `/budgets`
- Increase the strategy's `budget` in config
- Reset drawdown if needed (see [Operations Runbook](OPERATIONS_RUNBOOK.md))
- Winning trades will gradually recover budget (reduce drawdown)

### Orders Timing Out

**Symptoms**: Entry orders are placed but never filled, then cancelled after timeout.

**Causes & Fixes**:

1. **Price moved away** — The limit price was too far from market. Adjust `entry_price_bias`:
   - `-1` = BID (most conservative, best fill price, least likely to fill)
   - `0` = MID (balanced, default)
   - `1` = ASK (most aggressive, worst fill price, most likely to fill)
2. **Timeout too short** — Increase `order_management.order_timeout_seconds`
3. **Illiquid option** — The option has a wide bid-ask spread. Check `spread_threshold_pct` on ORB strategy

### "Strategy paused: hit daily loss limit"

**Symptoms**: A strategy stops trading mid-day.

**Explanation**: The strategy's `daily_loss_limit` was reached. This is a safety feature. The strategy will resume the next trading day. To override:
- Increase or remove `daily_loss_limit` from the strategy config
- The global `safety.max_daily_loss` applies separately

---

## Strategy Issues

### Strategy Shows as "unloaded" in `/strategies`

**Symptoms**: `/strategies` lists a strategy type as "Not loaded (available)".

**Fixes**:
- Check that the strategy file exists in `strategies/` directory
- Check that the `type` key in config matches a registered strategy type
- Look for Python syntax errors in the strategy file: `python -c "import strategies.swing_trading"`
- Use `/reload` to attempt a reload and see error messages

### `/discover` Shows No New Files

**Expected behavior**: `/discover` only shows strategy files that aren't already loaded. If all `.py` files in `strategies/` are loaded, it correctly shows nothing.

### Hot Reload Fails

**Symptoms**: `/reload` or `/reload <name>` shows an error.

**Fixes**:
- Check for Python syntax errors in the modified file
- The error message will show the traceback — fix the code and try again
- Existing running instances continue with old code if reload fails

### No Signals Generated

**Symptoms**: Bot runs but never generates any trading signals.

**Possible causes**:
1. **Market regime veto** — Current regime not in `allowed_regimes`. Check `/status` for current regime
2. **Confidence too high** — Lower `min_confidence` on the strategy
3. **No Level 2 data** — See "No market depth data" above
4. **Outside trading hours** — Check `safety.trading_hours_only`
5. **Emergency stop active** — Check `safety.emergency_stop` in config
6. **Symbols not volatile** — During calm markets, fewer signals are generated. This is normal

---

## Database Issues

### Database Locked

**Symptoms**: SQLite "database is locked" error.

**Fixes**:
- The bot uses WAL (Write-Ahead Logging) mode which should prevent this
- Ensure only one bot instance is writing to the same `trading_bot.db`
- Close any other tools (DB Browser, sqlite3 CLI) that have the file open with a write lock

### Positions Out of Sync

**Symptoms**: Bot shows positions that don't match what's in IB.

**Fixes**:
- Restart the bot — it reconciles positions with IB on startup
- Positions in the database but missing from IB are marked as `manual_close`
- IB positions not in the database are ignored (treated as manual trades)

### Corrupted Database

**Symptoms**: SQLite errors about malformed database.

**Fix**:
```bash
# Attempt repair
sqlite3 trading_bot.db "PRAGMA integrity_check;"

# If corrupt, restore from backup
cp trading_bot_backup.db trading_bot.db

# If no backup, start fresh (you lose trade history)
mv trading_bot.db trading_bot_corrupt.db
# Bot will create a new database on next start
```

---

## Notification Issues

### Discord Notifications Not Working

**Symptoms**: No messages appear in Discord.

**Fixes**:
1. Verify webhook URL in `config.yaml` is correct and complete
2. Test with `/test_notify` command
3. Check that the webhook hasn't been deleted in Discord server settings
4. Check bot logs for HTTP errors (4xx/5xx status codes)
5. Discord webhooks have rate limits — if sending many alerts rapidly, some may be dropped

---

## Performance Issues

### Bot Using High CPU

**Symptoms**: Python process consuming excessive CPU.

**Causes**:
- `scan_interval` set too low (e.g., 1 second). Increase to 5-10 seconds
- Too many symbols subscribed with Level 2 data
- `data_collection_mode: true` generates heavy disk I/O — disable in production

### Slow Startup

**Symptoms**: Bot takes a long time to start.

**Causes**:
- Downloading historical data for all symbols (initial cache fill)
- Large number of open positions being reconciled
- Sector rotation initial calculation fetches data for 11 ETFs
- Subsequent startups are faster due to `historical_bars` cache

---

## Log File Issues

### Log File Growing Too Large

The bot uses a rotating file handler. By default, `trading_bot.log` rotates daily. Old logs are not automatically deleted.

**Fix**: Periodically clean up old log files:
```bash
# Keep last 7 days of logs (example)
# On Linux/Mac:
find . -name "trading_bot.log.*" -mtime +7 -delete
# On Windows:
forfiles /p . /m "trading_bot.log.*" /d -7 /c "cmd /c del @path"
```

### Debug Logging Too Verbose

Set `operation.log_level` to `"INFO"` or `"WARNING"` in config. `"DEBUG"` logs every scan cycle, every depth update, and every level detection.
