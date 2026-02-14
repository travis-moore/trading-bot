# AI Configuration Advisor Package

Generated: 2026-02-14 | Period: 2026-01-15 to 2026-02-14

## 1. SYSTEM CONTEXT

This is an automated options trading bot using Interactive Brokers (IBKR). It trades stock options (calls, puts, spreads, iron condors) based on order book liquidity analysis, support/resistance detection, and market regime filtering.

### How the Bot Works
- Monitors Level 2 order books for multiple symbols to detect support/resistance zones
- Generates signals when price interacts with detected zones (rejection, breakout)
- Filters signals through market regime (bull_trend, bear_trend, range_bound, high_chaos) and sector relative strength
- Each strategy instance has its own budget, symbols, position limits, and tunable parameters
- Uses bracket orders (stop loss + take profit) with optional trailing stops
- Multiple strategy types can run simultaneously with different configurations

### Tunable Parameter Reference

#### Global Risk Management
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `risk_management.profit_target_pct` | Take profit at this % gain | 0.10-1.00 | Higher = more profit per trade but fewer exits |
| `risk_management.stop_loss_pct` | Stop loss at this % loss | 0.10-0.50 | Tighter = less loss per trade but more stop-outs |
| `risk_management.trailing_stop_enabled` | Enable trailing stops | bool | Lets winners run further |
| `risk_management.trailing_stop_activation_pct` | Profit % to start trailing | 0.05-0.30 | Lower = activates sooner |
| `risk_management.trailing_stop_distance_pct` | Trail distance from peak | 0.02-0.15 | Tighter = locks in more profit but more whipsaws |
| `risk_management.max_hold_days` | Auto-close after N days | 1-60 | Prevents capital lock-up; lower for scalping |

#### Global Trading Rules (Pattern Confidence Thresholds)
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `trading_rules.rejection_support_confidence` | Min confidence for support bounce signal | 0.50-0.90 | Lower = more signals |
| `trading_rules.breakout_up_confidence` | Min confidence for upward breakout signal | 0.50-0.90 | Lower = more signals |
| `trading_rules.rejection_resistance_confidence` | Min confidence for resistance rejection signal | 0.50-0.90 | Lower = more signals |
| `trading_rules.breakout_down_confidence` | Min confidence for downward breakout signal | 0.50-0.90 | Lower = more signals |

#### Global Option Selection
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `option_selection.min_dte` | Minimum days to expiration | 1-45 | Lower = cheaper but more theta decay |
| `option_selection.max_dte` | Maximum days to expiration | 14-90 | Higher = more expensive but less theta |
| `option_selection.call_strike_pct` | Call strike as multiple of price (1.02 = 2% OTM) | 1.00-1.10 | Higher = cheaper but less likely ITM |
| `option_selection.put_strike_pct` | Put strike as multiple of price (0.98 = 2% OTM) | 0.90-1.00 | Lower = cheaper but less likely ITM |

#### Per-Strategy Parameters (common to all types)
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `enabled` | Whether strategy is active | bool | |
| `max_positions` | Max concurrent positions for this strategy | 1-10 | |
| `allowed_regimes` | Market regimes where strategy can trade | list | Options: bull_trend, bear_trend, range_bound, high_chaos |
| `min_sector_rs` | Min sector relative strength slope | -1.0 to 1.0 | 0.0 = only outperforming sectors |
| `daily_loss_limit` | Stop strategy for day after this $ loss | 50-1000 | Per-strategy safety |
| `entry_price_bias` | Entry price: -1=BID, 0=MID, 1=ASK | -1.0 to 1.0 | Negative = better fills, less likely to fill |
| `contract_cost_basis` | Max $ per contract (price*100) | 50-500 | Caps individual contract cost |

#### Swing Trading Specific
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `zone_proximity_pct` | Price must be within this % of level | 0.001-0.02 | Wider = more signals, less precise |
| `min_confidence` | Min confidence to generate signal | 0.50-0.90 | Primary quality filter |
| `zscore_threshold` | Z-score for filtering significant levels | 1.5-5.0 | Higher = fewer but stronger levels |
| `level_confirmation_minutes` | Minutes a level must persist | 1-15 | Higher = more confirmed levels |
| `exclusion_zone_pct` | Ignore levels within this % of price | 0.001-0.01 | Prevents trading at current price |
| `historical_bounce_enabled` | Use historical price levels | bool | Adds "Power Level" detection |
| `swing_window` | Bars on each side for swing detection | 3-10 | Higher = fewer but more significant swings |
| `bounce_proximity_pct` | Clustering tolerance for swing points | 0.0005-0.003 | |
| `min_bounces` | Min tests to form a level | 2-5 | Higher = stronger levels only |
| `decay_type` | How older bounces lose strength | linear/exponential | |
| `power_level_proximity_pct` | Alignment tolerance (historical+depth) | 0.003-0.01 | |
| `power_level_confidence_boost` | Confidence boost for power levels | 0.05-0.30 | |
| `performance_feedback_enabled` | Auto-adjust confidence from results | bool | |
| `performance_lookback_days` | Days of history for feedback | 3-30 | |
| `min_trades_for_feedback` | Min trades before feedback activates | 3-20 | |

#### Scalping Specific
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `imbalance_entry_threshold` | Order book imbalance to trigger entry | 0.5-0.9 | Higher = stronger signal required |
| `max_ticks_without_progress` | Exit if no favorable movement after N ticks | 1-10 | Lower = faster exit |

#### VIX Momentum ORB Specific
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `orb_minutes` | Minutes after open for opening range | 5-30 | |
| `trading_window_minutes` | Minutes after ORB to accept signals | 15-60 | |
| `target_profit` | Dollar profit target per trade | 100-1000 | |
| `vix_slope_minutes` | Minutes of VIX history for slope | 3-15 | |
| `spread_threshold_pct` | Skip if spread exceeds this % | 0.01-0.10 | |

#### Spread & Multi-Leg Specific
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `short_put_delta` / `long_put_delta` | Delta for spread legs | 5-50 | |
| `short_call_delta` / `long_call_delta` | Delta for condor call legs | 5-50 | |
| `exit_at_pct_profit` | Close at this % of max credit | 0.25-0.75 | |
| `exit_at_dte` | Close when this many DTE remain | 7-30 | Iron condor time exit |
| `absorption_confidence` | Min confidence for breakdown signals | 0.60-0.90 | |
| `put_delta` | Delta for long put purchases | 30-70 | Higher = more ATM, more expensive |

### Do Not Change (User Decisions)
These parameters should NOT be suggested for changes — they reflect user capital allocation, infrastructure, and risk tolerance:
- `ib_connection.*` (host, port, client_id)
- `strategies.*.budget` (user's capital allocation per strategy)
- `strategies.*.symbols` (user's market preference)
- `notifications.discord_webhook`
- `safety.max_daily_loss` (user's global risk limit)
- `safety.emergency_stop`, `safety.require_manual_approval`
- `operation.*` (scan_interval, log_level, etc.)

## 2. PREVIOUS CYCLE

First package — no previous cycle data.

## 3. CURRENT PERIOD DATA (2026-01-15 to 2026-02-14)

### Overall Performance

No trades in this period.

### Per-Strategy Performance

No strategy trades in this period.

### Per-Symbol Performance

No symbol data in this period.

### Exit Reason Distribution

No exit data in this period.

### Signal Utilization

No signal data in this period.

### Trade Frequency Analysis

No trades in this period.

### Budget Status

| Strategy | Budget | Drawdown | Committed | Available | % Available |
|----------|--------|----------|-----------|-----------|-------------|
| bear_put_spread_1 | $2000 | $0.00 | $0.00 | $2000.00 | 100.0% |
| bull_put_spread_1 | $2000 | $0.00 | $0.00 | $2000.00 | 100.0% |
| iron_condor_1 | $2500 | $0.00 | $0.00 | $2500.00 | 100.0% |
| long_put_1 | $1500 | $0.00 | $0.00 | $1500.00 | 100.0% |
| scalp_patient | $1500 | $0.00 | $0.00 | $1500.00 | 100.0% |
| scalp_quick | $1000 | $0.00 | $0.00 | $1000.00 | 100.0% |
| swing_aggressive | $1500 | $0.00 | $0.00 | $1500.00 | 100.0% |
| swing_conservative | $2000 | $0.00 | $0.00 | $2000.00 | 100.0% |
| vix_orb_1 | $2000 | $0.00 | $0.00 | $2000.00 | 100.0% |

### Worst 10 Trades

No trades in this period.

### Best 10 Trades

No trades in this period.

### Daily P&L Trend

No daily data in this period.

### Market Regime

Current: **N/A (standalone mode)**

## 4. CURRENT CONFIGURATION

```yaml
liquidity_analysis:
  liquidity_threshold: 500
  zone_proximity: 0.5
  imbalance_threshold: 0.6
  num_levels: 50
trading_rules:
  rejection_support_confidence: 0.65
  breakout_up_confidence: 0.7
  rejection_resistance_confidence: 0.65
  breakout_down_confidence: 0.7
risk_management:
  max_position_size: 2000
  max_positions: 3
  position_size_pct: 0.02
  profit_target_pct: 0.5
  stop_loss_pct: 0.3
  trailing_stop_enabled: true
  trailing_stop_activation_pct: 0.1
  trailing_stop_distance_pct: 0.05
  max_hold_days: 30
order_management:
  use_bracket_orders: true
  order_timeout_seconds: 60
  price_drift_threshold: 0.1
option_selection:
  min_dte: 14
  max_dte: 45
  call_strike_pct: 1.02
  put_strike_pct: 0.98
market_regime:
  update_interval_minutes: 30
  high_chaos_vix_threshold: 30.0
  high_chaos_vix_change_pct: 0.2
  high_chaos_spy_vol_pct: 0.02
  bull_trend_vix_threshold: 20.0
  range_bound_vix_min: 15.0
  range_bound_vix_max: 25.0
sector_rotation:
  update_interval_minutes: 60
  bar_size: 1 hour
  duration: 5 D
  rs_window: 5
strategies:
  swing_conservative:
    type: swing_trading
    enabled: true
    budget: 2000
    symbols:
    - NVDA
    - AAPL
    - TSLA
    - QQQ
    - XSP
    max_positions: 2
    level_confirmation_minutes: 1
    exclusion_zone_pct: 0.001
    zone_proximity_pct: 0.005
    min_confidence: 0.75
    zscore_threshold: 3.5
    allowed_regimes:
    - bull_trend
    - range_bound
    min_sector_rs: 0.0
    historical_bounce_enabled: true
    historical_lookback_days: 30
    historical_bar_size: 15 mins
    swing_window: 5
    bounce_proximity_pct: 0.001
    min_bounces: 2
    decay_type: linear
    linear_decay_days: 30
    power_level_proximity_pct: 0.005
    power_level_confidence_boost: 0.15
    symbol_overrides:
      NVDA:
        zone_proximity_pct: 0.008
    performance_feedback_enabled: true
    performance_lookback_days: 14
    min_trades_for_feedback: 5
  swing_aggressive:
    type: swing_trading
    enabled: true
    budget: 1500
    symbols:
    - NVDA
    - TSLA
    - QQQ
    - XSP
    daily_loss_limit: 200.0
    max_positions: 2
    level_confirmation_minutes: 1
    exclusion_zone_pct: 0.001
    zone_proximity_pct: 0.003
    min_confidence: 0.65
    zscore_threshold: 2.5
    allowed_regimes:
    - bull_trend
    - bear_trend
    - range_bound
    historical_bounce_enabled: true
    historical_lookback_days: 20
    historical_bar_size: 15 mins
    swing_window: 3
    bounce_proximity_pct: 0.0015
    min_bounces: 2
    decay_type: exponential
    exponential_half_life_days: 10
    power_level_proximity_pct: 0.007
    power_level_confidence_boost: 0.2
    performance_feedback_enabled: true
    performance_lookback_days: 7
    min_trades_for_feedback: 3
    max_confidence_penalty: 0.25
  scalp_quick:
    type: scalping
    enabled: true
    symbols:
    - NVDA
    - TSLA
    - QQQ
    - XSP
    budget: 1000
    daily_loss_limit: 150.0
    max_positions: 1
    imbalance_entry_threshold: 0.7
    max_ticks_without_progress: 3
    allowed_regimes:
    - bull_trend
    - bear_trend
    - range_bound
    - high_chaos
    max_hold_days: 5
    entry_price_bias: 0.0
    performance_feedback_enabled: true
    performance_lookback_days: 7
    min_trades_for_feedback: 10
    pnl_baseline: 20.0
  scalp_patient:
    type: scalping
    enabled: true
    symbols:
    - NVDA
    - AAPL
    - QQQ
    - XSP
    budget: 1500
    max_positions: 1
    imbalance_entry_threshold: 0.8
    max_ticks_without_progress: 7
    max_hold_days: 5
    allowed_regimes:
    - bull_trend
    - bear_trend
    - range_bound
    performance_feedback_enabled: true
    performance_lookback_days: 10
    min_trades_for_feedback: 8
    pnl_baseline: 25.0
  vix_orb_1:
    type: vix_momentum_orb
    enabled: true
    one_trade_per_day: true
    symbols:
    - XSP
    - QQQ
    budget: 2000
    orb_minutes: 15
    trading_window_minutes: 30
    target_profit: 300.0
    contract_cost_basis: 150.0
    max_hold_days: 1
    entry_price_bias: 0.0
    vix_symbol: VIX
    vix_slope_minutes: 5
    spread_threshold_pct: 0.05
    allowed_regimes:
    - bull_trend
    - bear_trend
    - high_chaos
  bull_put_spread_1:
    type: bull_put_spread
    enabled: true
    symbols:
    - AAPL
    - NVDA
    - QQQ
    - XSP
    budget: 2000
    max_positions: 2
    zone_proximity_pct: 0.005
    rejection_support_confidence: 0.7
    short_put_delta: 30
    long_put_delta: 15
    exit_at_pct_profit: 0.5
    allowed_regimes:
    - bull_trend
    - range_bound
  bear_put_spread_1:
    type: bear_put_spread
    enabled: true
    symbols:
    - TSLA
    - NVDA
    - QQQ
    - XSP
    budget: 2000
    max_positions: 2
    zone_proximity_pct: 0.005
    absorption_confidence: 0.7
    long_put_delta: 50
    short_put_delta: 30
    allowed_regimes:
    - bear_trend
  long_put_1:
    type: long_put
    enabled: true
    symbols:
    - TSLA
    - QQQ
    - XSP
    budget: 1500
    max_positions: 2
    zone_proximity_pct: 0.005
    absorption_confidence: 0.75
    put_delta: 50
    allowed_regimes:
    - bear_trend
    - high_chaos
  iron_condor_1:
    type: iron_condor
    enabled: true
    symbols:
    - AAPL
    - MSFT
    - QQQ
    - XSP
    budget: 2500
    max_positions: 2
    zone_proximity_pct: 0.005
    min_confidence: 0.8
    short_put_delta: 15
    long_put_delta: 5
    short_call_delta: 15
    long_call_delta: 5
    exit_at_pct_profit: 0.5
    exit_at_dte: 21
    allowed_regimes:
    - range_bound
```

## 5. AI INSTRUCTIONS

You are analyzing performance data from an automated options trading bot. Your task is to suggest configuration changes that would improve performance.

### What to Produce

Provide **1-3 ranked** configuration suggestions. For each:

**Suggestion N: [Brief title]**
- **Confidence**: High / Medium / Low
- **Parameter(s)**: `section.parameter_name`
- **Current value**: X
- **Suggested value**: Y
- **Reasoning**: 2-3 sentences referencing specific data from Section 3 (e.g., "stop_loss_filled accounts for 38% of exits with avg loss of -$23.50, suggesting stops may be too tight")
- **Expected impact**: What metric should improve (e.g., "win rate should increase by ~5%")
- **Risk**: What could go wrong if this change is counterproductive

### Constraints

1. **Prefer fewer high-confidence changes** over many speculative ones. It's better to make 1-2 clear improvements than 5 uncertain ones, so we can attribute results.
2. **Do NOT suggest changes** to parameters in the "Do Not Change" list (Section 1). Budget amounts, symbols, safety limits, and connection settings are user decisions.
3. **Reference specific data** when justifying suggestions. Cite exit reason percentages, win rates, signal utilization, or specific losing trade patterns.
4. **Consider parameter interactions**. Widening `zone_proximity_pct` increases signals, which may require raising `min_confidence` to filter quality. Changing `stop_loss_pct` affects win rate AND average loss.
5. **Budget model**: `available = budget - drawdown - committed`. Wins reduce drawdown (recover budget), losses increase drawdown. Profits above the cap don't increase available budget. Do not suggest budget changes.
6. **If performance is satisfactory**, say so. Not every cycle needs changes. Stability has value.
7. **Consider market conditions**. Poor performance during unfavorable regimes may not indicate a config problem.

### After Your Suggestions

End with a brief summary: "Priority change: [X]. Monitor: [Y metric] over the next period."

## 6. AI RESPONSE

<!-- After receiving suggestions from the AI, paste the full response below the marker line. -->
<!-- This section will be included in the next package's "Previous Cycle" for continuity. -->

---PASTE AI RESPONSE BELOW THIS LINE---

