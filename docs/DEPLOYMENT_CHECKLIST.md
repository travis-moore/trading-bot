# Production Deployment Checklist

Use this checklist before switching from paper trading to live trading, or when deploying to a new environment.

---

## Pre-Deployment

### Account & Broker

- [ ] IB account funded and approved for options trading
- [ ] Market data subscriptions active (NASDAQ TotalView for Level 2)
- [ ] TWS or IB Gateway installed and tested
- [ ] API connection verified (correct port: 7496 for TWS live, 4001 for Gateway live)
- [ ] "Read-Only API" is **unchecked** in TWS settings
- [ ] `127.0.0.1` added to Trusted IPs

### Paper Trading Validation

- [ ] Bot ran successfully in paper mode for at least 1-2 weeks
- [ ] Reviewed trade history for strategy effectiveness (`/metrics`, `/pnl`)
- [ ] Win rate and profit factor acceptable for each enabled strategy
- [ ] No unexpected behavior or crashes during paper period
- [ ] Position reconciliation tested (stop bot, restart, verify positions restored)
- [ ] Signal utilization reviewed (not too many rejected signals suggesting bad config)

### Configuration Review

- [ ] `ib_connection.port` set to live port (`7496` or `4001`)
- [ ] `operation.enable_paper_trading` set to `false`
- [ ] `safety.max_daily_loss` set to an appropriate value
- [ ] `safety.trading_hours_only` set to `true`
- [ ] `safety.emergency_stop` set to `false`
- [ ] Each strategy's `budget` is appropriate for live capital
- [ ] `risk_management.max_position_size` is appropriate for account size
- [ ] `risk_management.position_size_pct` won't over-allocate
- [ ] `risk_management.max_positions` appropriate for account
- [ ] Review all `daily_loss_limit` values per strategy
- [ ] Consider starting with `safety.require_manual_approval: true`

### Strategy Configuration

- [ ] Only intended strategies are `enabled: true`
- [ ] Each strategy's `symbols` list is reviewed
- [ ] `allowed_regimes` make sense for each strategy
- [ ] `min_confidence` thresholds are not too low
- [ ] `contract_cost_basis` limits set to prevent expensive trades
- [ ] Spread strategies have appropriate delta settings
- [ ] Historical bounce detection settings reviewed if enabled

### Risk Parameters

| Parameter | Suggested Starting Point | Your Value |
|-----------|-------------------------|------------|
| `max_daily_loss` | 2-3% of account | _______ |
| `max_position_size` | 1-2% of account | _______ |
| `max_positions` (global) | 3-5 | _______ |
| `stop_loss_pct` | 0.25-0.35 | _______ |
| `profit_target_pct` | 0.40-0.60 | _______ |
| `max_hold_days` | 5-30 depending on strategy | _______ |
| Per-strategy `budget` | Size to limit total exposure | _______ |

### Notifications

- [ ] Discord webhook configured and tested (`/test_notify`)
- [ ] Webhook channel has appropriate visibility (not a public channel)
- [ ] Confirmed you receive: trade fills, order failures, daily loss alerts, crash alerts

---

## Deployment Steps

### 1. Database Preparation

```bash
# Back up paper trading database
cp trading_bot.db trading_bot_paper.db

# Start fresh for live (recommended)
mv trading_bot.db trading_bot.db.paper
# Bot will create a new empty database on startup

# OR keep existing database if you want to preserve settings
# Budget drawdowns from paper will carry over — consider resetting:
sqlite3 trading_bot.db "UPDATE strategy_budgets SET drawdown = 0, committed = 0;"
```

### 2. Configuration Switch

```yaml
# config.yaml changes for live:
ib_connection:
  port: 7496              # TWS live port (or 4001 for Gateway)

operation:
  enable_paper_trading: false

safety:
  require_manual_approval: true   # Start with manual approval
  max_daily_loss: 300             # Conservative daily limit
```

### 3. Gradual Rollout

**Phase 1: Manual Approval (Days 1-3)**
- Set `require_manual_approval: true`
- Approve each trade individually
- Verify fills, bracket orders, and exits work correctly

**Phase 2: Single Strategy (Days 4-7)**
- Enable only one strategy (e.g., `swing_conservative`)
- Disable `require_manual_approval`
- Monitor closely

**Phase 3: Additional Strategies (Week 2+)**
- Enable additional strategies one at a time
- Monitor each for a few days before adding the next
- Increase budgets gradually

**Phase 4: Full Automation (Week 3+)**
- All desired strategies enabled
- Budgets at target levels
- Daily monitoring routine established

### 4. Startup Verification

After starting the bot in live mode:

```
/status              # Verify account value, connection status
/strategies          # Verify correct strategies enabled
/budgets             # Verify budget allocation
/positions           # Should be empty on fresh start
/test_notify         # Verify Discord alerts
```

---

## Post-Deployment Monitoring

### First Day

- [ ] Watch every trade live
- [ ] Verify bracket orders appear in TWS
- [ ] Verify trailing stops activate correctly
- [ ] Confirm Discord notifications arrive for each trade
- [ ] Check that position count doesn't exceed limits
- [ ] Verify P&L calculations match IB account

### First Week

- [ ] Review daily P&L trend
- [ ] Check for any order rejections or failures
- [ ] Monitor execution quality: `/export report` or `python snapshot_analyzer.py --report`
- [ ] Verify position reconciliation works (intentionally restart once)
- [ ] Review signal utilization rate (executed vs rejected signals)

### Ongoing

- [ ] Daily budget check before market open
- [ ] Weekly performance review (`/metrics`, `/pnl`)
- [ ] Monthly strategy effectiveness review
- [ ] Database backups (at least weekly)

---

## Rollback Plan

If something goes wrong:

### Quick Stop (Seconds)
```
# In the terminal:
/quit

# Or press Ctrl+C
```
Existing bracket orders (TP/SL) remain active on IB servers.

### Emergency Stop (No Terminal Access)
1. Edit `config.yaml`: set `safety.emergency_stop: true`
2. Restart the bot — it will not enter any new trades
3. Existing positions are still managed (stops/targets active)

### Full Rollback to Paper
1. Stop the bot
2. Back up live database: `cp trading_bot.db trading_bot_live.db`
3. Change config back:
   ```yaml
   ib_connection:
     port: 7497
   operation:
     enable_paper_trading: true
   ```
4. Restart

### Close All Positions Manually
If you need to exit all positions immediately:
1. Open TWS or IB Client Portal
2. Close all bot-managed positions (tagged with `SWINGBOT-*` orderRef)
3. On next bot restart, reconciliation will mark them as `manual_close`
