# Configuration Reference

All configuration is in `config.yaml`. The bot reads this file on startup. Some settings can be adjusted at runtime via interactive commands (e.g., `/enable`, `/disable`, `/reload`).

---

## IB Connection

```yaml
ib_connection:
  host: "127.0.0.1"
  port: 7497
  client_id: 1
  sequential_scanning: true
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `host` | string | `"127.0.0.1"` | TWS/Gateway host address |
| `port` | int | `7497` | API port. TWS: 7497 (paper), 7496 (live). Gateway: 4002 (paper), 4001 (live) |
| `client_id` | int | `1` | Unique client ID. Must differ if running multiple bot instances |
| `sequential_scanning` | bool | `false` | Scan symbols one at a time instead of in parallel. Set `true` if hitting market data limits (e.g., only 3 concurrent streams) |

---

## Liquidity Analysis

```yaml
liquidity_analysis:
  liquidity_threshold: 500
  zone_proximity: 0.50
  imbalance_threshold: 0.6
  num_levels: 50
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `liquidity_threshold` | int | `500` | Minimum volume to consider a price level significant |
| `zone_proximity` | float | `0.50` | Dollar distance to group orders into the same zone |
| `imbalance_threshold` | float | `0.6` | Buy/sell imbalance ratio (0-1) to trigger directional signal |
| `num_levels` | int | `50` | Number of order book levels to analyze |

---

## Trading Rules

```yaml
trading_rules:
  rejection_support_confidence: 0.65
  breakout_up_confidence: 0.70
  rejection_resistance_confidence: 0.65
  breakout_down_confidence: 0.70
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `rejection_support_confidence` | float | `0.65` | Min confidence for support bounce (buy calls) |
| `breakout_up_confidence` | float | `0.70` | Min confidence for upward breakout (buy calls) |
| `rejection_resistance_confidence` | float | `0.65` | Min confidence for resistance rejection (buy puts) |
| `breakout_down_confidence` | float | `0.70` | Min confidence for downward breakout (buy puts) |

---

## Risk Management

```yaml
risk_management:
  max_position_size: 2000
  max_positions: 3
  position_size_pct: 0.02
  profit_target_pct: 0.50
  stop_loss_pct: 0.30
  trailing_stop_enabled: true
  trailing_stop_activation_pct: 0.10
  trailing_stop_distance_pct: 0.05
  max_hold_days: 30
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_position_size` | int | `2000` | Maximum dollar amount per position |
| `max_positions` | int | `3` | Maximum concurrent open positions (global) |
| `position_size_pct` | float | `0.02` | Position size as fraction of account value (2%) |
| `profit_target_pct` | float | `0.50` | Take profit at this % gain (50%) |
| `stop_loss_pct` | float | `0.30` | Stop loss at this % loss (30%) |
| `trailing_stop_enabled` | bool | `true` | Enable trailing stops after activation threshold |
| `trailing_stop_activation_pct` | float | `0.10` | Start trailing after this % profit (10%) |
| `trailing_stop_distance_pct` | float | `0.05` | Trail distance as % from peak (5%) |
| `max_hold_days` | int | `30` | Auto-close positions after this many days |

> **Note**: `profit_target_pct`, `stop_loss_pct`, and `max_hold_days` can be overridden per-strategy. See [Strategy Engine Overrides](#strategy-engine-overrides).

---

## Order Management

```yaml
order_management:
  use_bracket_orders: true
  order_timeout_seconds: 60
  price_drift_threshold: 0.10
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `use_bracket_orders` | bool | `true` | Attach stop loss + take profit to entry orders |
| `order_timeout_seconds` | int | `60` | Cancel unfilled entry orders after this many seconds |
| `price_drift_threshold` | float | `0.10` | Cancel if price drifts >10% from limit price |

---

## Option Selection

```yaml
option_selection:
  min_dte: 14
  max_dte: 45
  call_strike_pct: 1.02
  put_strike_pct: 0.98
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `min_dte` | int | `14` | Minimum days to expiration |
| `max_dte` | int | `45` | Maximum days to expiration |
| `call_strike_pct` | float | `1.02` | Call strike as multiple of current price (1.02 = 2% OTM) |
| `put_strike_pct` | float | `0.98` | Put strike as multiple of current price (0.98 = 2% OTM) |

> These are global defaults. Each strategy can override them. See [Strategy Engine Overrides](#strategy-engine-overrides).

---

## Bot Operation

```yaml
operation:
  scan_interval: 5
  market_data_refresh: 5
  enable_paper_trading: true
  log_level: "INFO"
  data_collection_mode: false
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `scan_interval` | int | `5` | Seconds between signal scan cycles |
| `market_data_refresh` | int | `5` | Seconds between market depth data refreshes |
| `enable_paper_trading` | bool | `true` | Use paper trading account |
| `log_level` | string | `"INFO"` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `data_collection_mode` | bool | `false` | Log detailed market data to CSV for debugging |

---

## Notifications

```yaml
notifications:
  discord_webhook: "https://discord.com/api/webhooks/..."
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `discord_webhook` | string | `""` | Discord webhook URL. Leave empty to disable notifications |

---

## Market Regime

```yaml
market_regime:
  update_interval_minutes: 30
  high_chaos_vix_threshold: 30.0
  high_chaos_vix_change_pct: 0.20
  high_chaos_spy_vol_pct: 0.02
  bull_trend_vix_threshold: 20.0
  range_bound_vix_min: 15.0
  range_bound_vix_max: 25.0
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `update_interval_minutes` | int | `30` | Minutes between regime re-assessment |
| `high_chaos_vix_threshold` | float | `30.0` | VIX level that triggers High Chaos regime |
| `high_chaos_vix_change_pct` | float | `0.20` | VIX % spike that triggers High Chaos (20%) |
| `high_chaos_spy_vol_pct` | float | `0.02` | SPY daily realized vol that triggers High Chaos (2%) |
| `bull_trend_vix_threshold` | float | `20.0` | Maximum VIX for Bull Trend classification |
| `range_bound_vix_min` | float | `15.0` | Minimum VIX for Range Bound classification |
| `range_bound_vix_max` | float | `25.0` | Maximum VIX for Range Bound classification |

### Regime Classification Logic

1. **High Chaos**: VIX > 30, OR VIX spiked >20%, OR SPY realized vol > 2%
2. **Bull Trend**: SPY above 200-day SMA AND VIX < 20
3. **Bear Trend**: SPY below 200-day SMA
4. **Range Bound**: VIX between 15-25, none of the above
5. **Unknown**: Insufficient data

---

## Sector Rotation

```yaml
sector_rotation:
  update_interval_minutes: 60
  bar_size: '1 hour'
  duration: '5 D'
  rs_window: 5
  # symbol_sector_overrides:
  #   NVDA: XLK
  #   TSLA: XLY
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `update_interval_minutes` | int | `60` | Minutes between RS recalculation |
| `bar_size` | string | `'1 hour'` | Bar timeframe for RS calculation |
| `duration` | string | `'5 D'` | Lookback duration for RS data |
| `rs_window` | int | `5` | Number of recent bars for slope calculation |
| `symbol_sector_overrides` | dict | `{}` | Manual symbol-to-sector ETF mapping (bypasses IB industry lookup) |

### Sector ETFs Tracked

XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU, XLRE, XLC, XLB (11 S&P 500 sector ETFs)

---

## Safety

```yaml
safety:
  require_manual_approval: false
  max_daily_loss: 500
  trading_hours_only: true
  emergency_stop: false
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `require_manual_approval` | bool | `false` | Prompt for confirmation before each trade |
| `max_daily_loss` | int | `500` | Stop all trading after this $ loss in a day (global) |
| `trading_hours_only` | bool | `true` | Only trade during market hours (9:30-16:00 ET) |
| `emergency_stop` | bool | `false` | Kill switch. Set `true` to stop all new trades immediately |

---

## Strategies

Strategies are defined under the `strategies:` key. Each entry is a named instance with its own configuration. Multiple instances of the same strategy type can run simultaneously with different parameters.

### Common Strategy Parameters

These parameters are available on **every** strategy type:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `type` | string | Yes | Strategy type key (see table below) |
| `enabled` | bool | Yes | Whether the strategy is active |
| `budget` | float | Yes | Maximum budget in dollars for this strategy |
| `symbols` | list | Yes | Symbols to monitor (e.g., `["NVDA", "AAPL"]`) |
| `max_positions` | int | No | Max concurrent positions for this strategy |
| `allowed_regimes` | list | No | Market regimes where this strategy can trade |
| `min_sector_rs` | float | No | Minimum sector relative strength slope |
| `daily_loss_limit` | float | No | Stop this strategy for the day after this $ loss |
| `one_trade_per_day` | bool | No | Limit to one trade per symbol per day |
| `symbol_overrides` | dict | No | Per-symbol parameter overrides (see below) |

### Strategy Types

| Type Key | Class | Description |
|----------|-------|-------------|
| `swing_trading` | SwingTradingStrategy | Support/resistance bounce with historical power levels |
| `scalping` | ScalpingStrategy | Order book imbalance momentum trading |
| `vix_momentum_orb` | VIXMomentumORB | Opening range breakout with VIX confirmation |
| `bull_put_spread` | BullPutSpreadStrategy | Credit spread at support in bull markets |
| `bear_put_spread` | BearPutSpreadStrategy | Debit spread on breakdowns in bear markets |
| `long_put` | LongPutStrategy | Directional put on breakdowns |
| `iron_condor` | IronCondorStrategy | Premium selling in range-bound markets |

### Strategy Engine Overrides

These global parameters from `risk_management` and `option_selection` can be overridden per-strategy:

| Parameter | Global Section | Description |
|-----------|---------------|-------------|
| `entry_price_bias` | — | Entry price: -1 = BID, 0 = MID (default), 1 = ASK |
| `contract_cost_basis` | — | Max $ per contract (`entry_price * 100`). Skip if exceeded |
| `min_dte` | `option_selection` | Min days to expiration |
| `max_dte` | `option_selection` | Max days to expiration |
| `call_strike_pct` | `option_selection` | Call strike as % of price |
| `put_strike_pct` | `option_selection` | Put strike as % of price |
| `profit_target_pct` | `risk_management` | Take profit percentage |
| `stop_loss_pct` | `risk_management` | Stop loss percentage |
| `max_hold_days` | `risk_management` | Max days to hold |

### Per-Symbol Overrides

Any engine override can also be set per-symbol within a strategy:

```yaml
strategies:
  swing_conservative:
    type: swing_trading
    entry_price_bias: 0.0        # Default for this strategy
    symbol_overrides:
      TSLA:
        entry_price_bias: -0.3   # Lean toward bid for TSLA
        stop_loss_pct: 0.35      # Wider stop for TSLA volatility
      NVDA:
        zone_proximity_pct: 0.008  # Wider zones for NVDA
```

**Override precedence**: symbol override > strategy override > global default

---

### Swing Trading Parameters

```yaml
swing_conservative:
  type: swing_trading
  # ... common parameters ...
  level_confirmation_minutes: 1
  exclusion_zone_pct: 0.001
  zone_proximity_pct: 0.005
  min_confidence: 0.75
  zscore_threshold: 3.5
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `level_confirmation_minutes` | int | `5` | Minutes a level must persist before being considered valid |
| `exclusion_zone_pct` | float | `0.005` | Ignore levels within this % of current price |
| `zone_proximity_pct` | float | `0.005` | Price must be within this % of a level to trigger signal |
| `min_confidence` | float | `0.65` | Minimum confidence score to generate signal |
| `zscore_threshold` | float | `3.0` | Z-score threshold for filtering significant levels |

#### Historical Bounce Detection

```yaml
  historical_bounce_enabled: true
  historical_lookback_days: 30
  historical_bar_size: '15 mins'
  swing_window: 5
  bounce_proximity_pct: 0.001
  min_bounces: 2
  decay_type: 'linear'
  linear_decay_days: 30
  power_level_proximity_pct: 0.005
  power_level_confidence_boost: 0.15
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `historical_bounce_enabled` | bool | `false` | Enable historical price level detection |
| `historical_lookback_days` | int | `30` | Days of historical data to fetch |
| `historical_bar_size` | string | `'15 mins'` | Bar timeframe for historical analysis |
| `swing_window` | int | `5` | Bars on each side for swing high/low detection |
| `bounce_proximity_pct` | float | `0.001` | Tolerance for clustering swing points into levels (0.1%) |
| `min_bounces` | int | `2` | Minimum tests to form a valid level |
| `decay_type` | string | `'linear'` | How older bounces lose strength: `linear` or `exponential` |
| `linear_decay_days` | int | `30` | Days to full decay (linear mode) |
| `exponential_half_life_days` | int | `10` | Half-life in days (exponential mode) |
| `power_level_proximity_pct` | float | `0.005` | Alignment tolerance between historical and depth levels (0.5%) |
| `power_level_confidence_boost` | float | `0.15` | Confidence boost when both historical and depth converge |

#### Performance Feedback

```yaml
  performance_feedback_enabled: true
  performance_lookback_days: 14
  min_trades_for_feedback: 5
  max_confidence_penalty: 0.15
  pnl_baseline: 50.0
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `performance_feedback_enabled` | bool | `false` | Adjust confidence based on recent P&L |
| `performance_lookback_days` | int | `14` | Days of trade history to evaluate |
| `min_trades_for_feedback` | int | `5` | Minimum trades before feedback kicks in |
| `max_confidence_penalty` | float | `0.15` | Maximum confidence reduction for poor performance |
| `pnl_baseline` | float | `50.0` | Expected average P&L per trade (for P&L ratio) |

---

### Scalping Parameters

```yaml
scalp_quick:
  type: scalping
  # ... common parameters ...
  imbalance_entry_threshold: 0.7
  max_ticks_without_progress: 3
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `imbalance_entry_threshold` | float | `0.7` | Order book imbalance ratio to trigger entry |
| `max_ticks_without_progress` | int | `5` | Exit if no favorable price movement after N ticks |

---

### VIX Momentum ORB Parameters

```yaml
vix_orb_1:
  type: vix_momentum_orb
  # ... common parameters ...
  orb_minutes: 15
  trading_window_minutes: 30
  target_profit: 300.0
  vix_symbol: 'VIX'
  vix_slope_minutes: 5
  spread_threshold_pct: 0.05
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `orb_minutes` | int | `15` | Minutes after open to establish the opening range |
| `trading_window_minutes` | int | `30` | Minutes after ORB ends to accept breakout signals |
| `target_profit` | float | `300.0` | Dollar profit target per trade |
| `vix_symbol` | string | `'VIX'` | VIX symbol for momentum confirmation |
| `vix_slope_minutes` | int | `5` | Minutes of VIX history for slope calculation |
| `spread_threshold_pct` | float | `0.05` | Skip if bid-ask spread exceeds this % (5%) |

---

### Bull Put Spread Parameters

```yaml
bull_put_spread_1:
  type: bull_put_spread
  rejection_support_confidence: 0.70
  short_put_delta: 30
  long_put_delta: 15
  exit_at_pct_profit: 0.50
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `rejection_support_confidence` | float | `0.70` | Min confidence for support rejection signal |
| `short_put_delta` | int | `30` | Delta of the put to sell (short leg) |
| `long_put_delta` | int | `15` | Delta of the put to buy (long leg / protection) |
| `exit_at_pct_profit` | float | `0.50` | Close at this % of max credit received |

---

### Bear Put Spread Parameters

```yaml
bear_put_spread_1:
  type: bear_put_spread
  absorption_confidence: 0.70
  long_put_delta: 50
  short_put_delta: 30
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `absorption_confidence` | float | `0.70` | Min confidence for breakdown signal |
| `long_put_delta` | int | `50` | Delta of the put to buy (near ATM) |
| `short_put_delta` | int | `30` | Delta of the put to sell (further OTM) |

---

### Long Put Parameters

```yaml
long_put_1:
  type: long_put
  absorption_confidence: 0.75
  put_delta: 50
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `absorption_confidence` | float | `0.75` | Min confidence for breakdown signal. Warns if set below 0.75 |
| `put_delta` | int | `50` | Delta of the put to buy (50 = approximately ATM) |

---

### Iron Condor Parameters

```yaml
iron_condor_1:
  type: iron_condor
  min_confidence: 0.80
  short_put_delta: 15
  long_put_delta: 5
  short_call_delta: 15
  long_call_delta: 5
  exit_at_pct_profit: 0.50
  exit_at_dte: 21
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `min_confidence` | float | `0.80` | Min confidence for range-bound signal |
| `short_put_delta` | int | `15` | Delta of put to sell |
| `long_put_delta` | int | `5` | Delta of put to buy (wing) |
| `short_call_delta` | int | `15` | Delta of call to sell |
| `long_call_delta` | int | `5` | Delta of call to buy (wing) |
| `exit_at_pct_profit` | float | `0.50` | Close at this % of max credit |
| `exit_at_dte` | int | `21` | Close when this many DTE remain |

---

## Example: Conservative vs Aggressive Setup

```yaml
strategies:
  # Conservative: high confidence, favorable regimes only
  swing_conservative:
    type: swing_trading
    enabled: true
    budget: 2000
    symbols: ["NVDA", "AAPL", "QQQ"]
    min_confidence: 0.75
    allowed_regimes: ["bull_trend", "range_bound"]
    min_sector_rs: 0.0

  # Aggressive: lower confidence, more regimes, shorter decay
  swing_aggressive:
    type: swing_trading
    enabled: true
    budget: 1500
    symbols: ["NVDA", "TSLA"]
    min_confidence: 0.65
    allowed_regimes: ["bull_trend", "bear_trend", "range_bound"]
    decay_type: 'exponential'
    exponential_half_life_days: 10
```
