# Incident Response Procedures

How to handle failures, unexpected behavior, and emergencies while the bot is running.

---

## Severity Levels

| Level | Description | Examples | Response Time |
|-------|-------------|----------|---------------|
| **Critical** | Bot down, uncontrolled risk | Bot crash, connection loss with open positions | Immediate |
| **High** | Active trading impaired | Order failures, strategy pause from losses | Within minutes |
| **Medium** | Degraded but functional | Missed signals, slow execution | Within hours |
| **Low** | Cosmetic or minor | Log warnings, notification delays | Next maintenance window |

---

## Critical Incidents

### Bot Crash

**Detection**: Discord alert `CRITICAL ERROR: Bot crashed!`, or process exits.

**Immediate Actions**:
1. **Check if bracket orders are active** — Open TWS and verify that stop loss / take profit orders for open positions are still on IB's servers. They should be, since bracket orders are server-side
2. **Check logs** for the crash reason:
   ```bash
   # Last 50 lines of log
   tail -50 trading_bot.log
   ```
3. **Restart the bot**:
   ```bash
   python main.py
   ```
4. **Verify reconciliation** — On startup, the bot reconciles positions with IB:
   - Run `/positions` to confirm all positions were restored
   - Check logs for "Reconciled N positions" messages

**If crash keeps recurring**:
1. Enable debug logging: `operation.log_level: "DEBUG"`
2. Check for pattern: is it crashing on a specific symbol, strategy, or time?
3. Disable problematic strategy: edit config, set `enabled: false`
4. Restart and monitor

### Connection Loss With Open Positions

**Detection**: "Connection lost" in logs, or bot is not responsive.

**Why this is usually OK**:
- **Bracket orders** (TP + SL) are server-side on IB — they remain active even if the bot disconnects
- **Trailing stops** placed as IB TRAIL orders also remain active server-side
- Positions are protected even without the bot running

**Actions**:
1. **Check TWS/Gateway** — Is it still running? Is it still logged in?
2. If TWS/Gateway crashed:
   - Restart TWS/Gateway and log in
   - Restart the bot — it will reconnect and reconcile
3. If TWS/Gateway is running but bot disconnected:
   - The bot should reconnect automatically
   - If it doesn't, restart the bot

**When it's NOT OK**:
- Positions managed by `max_hold_days` (time-based exit) won't be monitored
- Trailing stop **activation** (the bot detects when to place the trail order) won't work for positions that haven't yet activated trailing stops
- New signals won't be detected

### IB Account Margin Call / Liquidation

**This is outside the bot's control.** IB will liquidate positions automatically if margin requirements aren't met.

**Prevention**:
- Keep `max_position_size` and `max_positions` conservative
- Monitor account value with `/status`
- Ensure `position_size_pct` is appropriate for your account

---

## High Severity Incidents

### Order Failures

**Detection**: Discord alert `ORDER FAILED: ...`, or logs showing order placement errors.

**Diagnosis**:
```bash
# Check recent order failures in trade history
sqlite3 trading_bot.db "SELECT * FROM trade_history WHERE exit_reason LIKE 'order%' ORDER BY exit_time DESC LIMIT 10;"
```

**Common causes and fixes**:

| Cause | Fix |
|-------|-----|
| Insufficient margin | Reduce `max_position_size` or close positions |
| Invalid contract | Check option selection params (DTE, strike) |
| Market closed | Verify `trading_hours_only: true` |
| API error | Check TWS for error messages, restart if needed |

### Order Rejections

**Detection**: Discord alert `ORDER REJECTED: ...`.

**Common rejection reasons**:
- **No trading permissions** — Enable options trading in IB Account Management
- **Short selling not permitted** — Check that the strategy isn't trying to short
- **Price outside limits** — IB has price reasonability checks; your limit price may be too far from market

### Strategy Hitting Daily Loss Limit

**Detection**: Discord alert `STRATEGY PAUSED: hit daily loss limit`.

**This is working as intended.** The strategy will resume next trading day.

**Actions**:
1. Review the losing trades: `/trades losers`
2. Check if the losses are from a strategy misconfiguration or genuinely bad market conditions
3. If the limit is too tight, increase `daily_loss_limit` in the strategy config
4. If the strategy is underperforming, consider disabling it: `/disable <name>`

### Global Daily Loss Limit Reached

**Detection**: Discord alert `PERFORMANCE ALERT: Daily loss limit reached`.

**All trading is paused.** No new trades will be entered until the next trading day.

**Actions**:
1. Review all losses for the day: `/trades losers`
2. Verify existing positions have bracket orders active in TWS
3. No action needed — bot resumes next trading day
4. If the limit is frequently hit, review risk parameters

---

## Medium Severity Incidents

### No Signals Being Generated

**Detection**: Bot running for hours with no signals in `/status` counters.

**Diagnosis checklist**:
1. `/status` — Check "Signals detected" counter
2. Is market open? Check time and `trading_hours_only`
3. Is emergency stop on? Check `safety.emergency_stop`
4. What's the market regime? Some strategies only trade in specific regimes
5. Is market depth data flowing? Check logs for "depth" messages at DEBUG level
6. Are strategies enabled? `/strategies`

### Execution Slippage Too High

**Detection**: Reviewing snapshot analysis shows high slippage.

**Diagnosis**:
```bash
python snapshot_analyzer.py --report
```

**Fixes**:
- Adjust `entry_price_bias` toward BID (negative values) for less aggressive fills
- Add `contract_cost_basis` limits to skip expensive contracts
- Add `spread_threshold_pct` to skip wide-spread options (ORB strategy)
- Trade more liquid symbols

### Position Stuck (Not Exiting)

**Detection**: A position has been open much longer than `max_hold_days`.

**Diagnosis**:
1. Check if bracket orders exist in TWS for this position
2. Check if the option has become illiquid (no buyers)
3. Check logs for exit attempt errors

**Fix**:
- Close the position manually in TWS
- On next bot scan or restart, reconciliation will detect it and mark as `manual_close`

---

## Low Severity Incidents

### Discord Notifications Delayed or Missing

**Possible causes**:
- Discord API rate limiting
- Webhook URL changed or deleted
- Network issue

**Fix**: Test with `/test_notify`. If it works, the issue was transient. If not, check/recreate the webhook URL.

### Log Warnings About Missing Data

Common harmless warnings:
- "No depth data for SYMBOL" — Level 2 not subscribed or market closed
- "Could not determine sector for SYMBOL" — IB didn't return industry info
- "Historical bars cache expired" — Will refresh on next scan

These are informational and don't require action.

---

## Emergency Procedures

### Immediate Stop All Trading

**Option 1: Terminal command**
```
/quit
```

**Option 2: Config change**
```yaml
# config.yaml
safety:
  emergency_stop: true
```
Then restart the bot. It will not enter new trades but will continue monitoring existing positions.

**Option 3: Force kill**
Press Ctrl+C twice (second press force-exits immediately).

**Option 4: Kill the process**
```bash
# Windows
taskkill /f /im python.exe

# Linux/Mac
kill -9 $(pgrep -f "python main.py")
```

> **Reminder**: Bracket orders remain active on IB servers. Your open positions are still protected by stop losses and take profits even after killing the bot.

### Close All Positions Immediately

The bot does not have a "close all" command. To close everything:

1. **Open TWS** (Trader Workstation)
2. Go to the Portfolio tab
3. Close all positions with `SWINGBOT-*` order references
4. Or: right-click each position > Close Position

On next bot restart, reconciliation will handle the bookkeeping.

### Recover From Bad State

If the database is inconsistent with IB:

1. Stop the bot
2. Back up: `cp trading_bot.db trading_bot_backup.db`
3. Start the bot — reconciliation runs automatically on startup
4. Check `/positions` matches what's in TWS
5. If positions are still wrong:
   ```bash
   # Nuclear option: remove all DB positions and let reconciliation rebuild
   sqlite3 trading_bot.db "DELETE FROM positions;"
   ```
   Restart the bot — it will detect positions from IB portfolio

---

## Post-Incident Review

After resolving any High or Critical incident:

1. **Document what happened**: What was the timeline? What triggered the incident?
2. **Review logs**: Save relevant log sections for analysis
3. **Check trade history**: Were any trades impacted? What was the P&L impact?
4. **Identify root cause**: Configuration issue? Code bug? External factor?
5. **Prevent recurrence**: Update config, add safety limits, or fix code as needed
6. **Test the fix**: Run in paper mode to verify before re-deploying live
