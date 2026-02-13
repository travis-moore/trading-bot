# Automated Options Trading System: Logic & Strategy

## 1. The Core Philosophy
Unlike standard bots that rely on lagging indicators (like Moving Averages or RSI) on a price chart, this system trades based on **Liquidity** and **Order Flow**. It looks at the "depth" of the market—the pending buy and sell orders—to identify where institutional players are positioning themselves before the price even moves.

<details>
<summary><strong>How it sees the market (The "X-Ray Vision")</strong></summary>

Most traders look at a line chart. This bot looks at the **Order Book** (Level 2 Data).

*   **The "Wall":** It identifies massive clusters of buy orders (Support) or sell orders (Resistance).
*   **The "Fake-out":** It uses statistical analysis to ignore "spoof" orders that disappear when price gets close.
*   **The "Imbalance":** It measures if buyers are being more aggressive than sellers in real-time.

<details>
<summary><strong>Deep Dive: Liquidity Analysis Mechanics</strong></summary>

1.  **Z-Score Filtering:** The bot calculates the average volume at every price level. It only pays attention to levels that are statistically significant (e.g., > 3 standard deviations above normal). This filters out noise.
2.  **Time Persistence:** A "wall" of orders must sit there for at least 5 minutes to be considered real. Flash orders are ignored.
3.  **Exclusion Zone:** It ignores orders right next to the current price (Market Maker noise) to focus on the structural levels further out.

</details>
</details>

---

## 2. Trading Strategies

The bot runs multiple strategies simultaneously, acting like a team of traders where each has a specific specialty. Each strategy instance gets its own budget, position limits, and configuration.

---

<details>
<summary><strong>Strategy A: Swing Trading (Support & Resistance)</strong></summary>

This strategy waits for price to hit a "wall" and bounce. It's like playing ping-pong against a brick wall.

*   **Bullish:** Price drops to a massive Buy Wall (Support). The wall holds. Price bounces up. -> **Buy Call Options**.
*   **Bearish:** Price rallies to a massive Sell Wall (Resistance). Buyers can't break through. Price rejects down. -> **Buy Put Options**.

<details>
<summary><strong>Entry Conditions</strong></summary>

#### Rejection at Support (Long Call)
| Condition | Description | Parameter | Configurable | Default |
|-----------|-------------|-----------|:---:|---------|
| Price in Zone | Price within proximity of confirmed support level | `zone_proximity_pct` | Yes | `0.005` (0.5%) |
| Level Significance | Order book level must be statistically significant (Z-score) | `zscore_threshold` | Yes | `3.0` |
| Level Persistence | Level must exist for N minutes before it's considered real | `level_confirmation_minutes` | Yes | `5` |
| Exclusion Zone | Ignore levels too close to current price (MM noise) | `exclusion_zone_pct` | Yes | `0.005` (0.5%) |
| Positive Imbalance | More buyers than sellers (imbalance flip detected) | `rejection_imbalance_flip` | Yes | `0.60` |
| Confidence Threshold | Minimum confidence to trigger entry | `rejection_support_confidence` | Yes | `0.65` |
| Imbalance Weight | How much order book imbalance modifies confidence | `imbalance_weight` | Yes | `0.3` |

#### Rejection at Resistance (Long Put)
Same as above but inverted: price near resistance, negative imbalance, sellers dominating.

| Parameter | Configurable | Default |
|-----------|:---:|---------|
| `rejection_resistance_confidence` | Yes | `0.65` |

#### Absorption Breakout (Long Call or Long Put)
| Condition | Description | Parameter | Configurable | Default |
|-----------|-------------|-----------|:---:|---------|
| Volume Absorbed | Wall size decreases significantly (orders consumed) | `absorption_threshold_pct` | Yes | `0.20` (20%) |
| Price Holds | Price stays at level while wall is absorbed | - | No | - |
| Confidence Threshold | Higher confidence required for breakouts | `absorption_confidence` | Yes | `0.75` |

#### Historical Power Level Boost
| Condition | Description | Parameter | Configurable | Default |
|-----------|-------------|-----------|:---:|---------|
| Enabled | Toggle historical analysis on/off | `historical_bounce_enabled` | Yes | `true` |
| Lookback | Days of historical candlestick data to analyze | `historical_lookback_days` | Yes | `30` |
| Bar Size | Candlestick timeframe for historical data | `historical_bar_size` | Yes | `'15 mins'` |
| Swing Window | Bars on each side for swing high/low detection | `swing_window` | Yes | `5` |
| Bounce Clustering | Tolerance for grouping nearby swings into one level | `bounce_proximity_pct` | Yes | `0.001` (0.1%) |
| Min Bounces | Minimum tests to form a bounce level | `min_bounces` | Yes | `2` |
| Decay Type | How older bounces lose weight | `decay_type` | Yes | `'linear'` or `'exponential'` |
| Linear Decay | Days to full decay (linear mode) | `linear_decay_days` | Yes | `30` |
| Exp Half-Life | Half-life in days (exponential mode) | `exponential_half_life_days` | Yes | `15.0` |
| Power Proximity | Max distance for historical + depth convergence | `power_level_proximity_pct` | Yes | `0.005` (0.5%) |
| Power Boost | Extra confidence added when power level detected | `power_level_confidence_boost` | Yes | `0.15` |
| Weak Depth | Skip trade if depth at power level is below this ratio | `weak_depth_threshold` | Yes | `0.5` |
| Strong Depth | Extra confidence if depth is above this ratio | `strong_depth_threshold` | Yes | `1.5` |
| Cache TTL | Hours before refreshing historical data from IB | `historical_cache_ttl_hours` | Yes | `24` |

#### Performance Feedback
| Parameter | Description | Configurable | Default |
|-----------|-------------|:---:|---------|
| `performance_feedback_enabled` | Adjust confidence based on recent win rate/P&L | Yes | `true` |
| `performance_lookback_days` | Days of trade history to evaluate | Yes | `14` |
| `min_trades_for_feedback` | Min closed trades before adjusting | Yes | `5` |
| `win_rate_boost_threshold` | Win rate above this boosts confidence | Yes | `0.60` |
| `win_rate_penalty_threshold` | Win rate below this penalizes confidence | Yes | `0.40` |
| `max_confidence_boost` | Maximum confidence boost for good performance | Yes | `+15%` |
| `max_confidence_penalty` | Maximum confidence penalty for poor performance | Yes | `-20%` |
| `pnl_weight` | How much P&L vs win rate matters (0.3 = 30% P&L) | Yes | `0.3` |
| `pnl_baseline` | Average profit that counts as "good" | Yes | `$50` |

</details>

<details>
<summary><strong>Exit Conditions</strong></summary>

All exits are managed by the **Trading Engine**, not the strategy itself.

| Exit Type | How It Works | Parameter | Configurable | Default |
|-----------|-------------|-----------|:---:|---------|
| Take Profit | Bracket order sells at entry + X% | `profit_target_pct` | Yes | `0.50` (50%) |
| Stop Loss | Bracket order sells at entry - X% | `stop_loss_pct` | Yes | `0.30` (30%) |
| Trailing Stop | After +10% profit, trail peak by 5%. Only moves in favorable direction | `trailing_stop_enabled` | Yes | `true` |
| Trail Activation | Profit % needed to activate trailing stop | `trailing_stop_activation_pct` | Yes | `0.10` (10%) |
| Trail Distance | How far below peak to set trailing stop | `trailing_stop_distance_pct` | Yes | `0.05` (5%) |
| Time Limit | Auto-close after N days | `max_hold_days` | Yes | `30` |
| Manual Close | Detected when position disappears from IB portfolio | - | No | - |
| Bracket Fill | TP/SL orders are OCA (One-Cancels-All) — when one fills, the other cancels | - | No | - |

**Trailing Stop Detail:** The engine tracks `peak_price` for each position. For LONG_CALL, peak is the highest mid-price seen since entry. For LONG_PUT, peak is the lowest. Trail only moves in the profitable direction (never retreats).

</details>

<details>
<summary><strong>Position Selection</strong></summary>

Option selection is handled by `TradingEngine.select_option()` and `enter_trade()`.

| Step | How It Works | Parameter | Configurable | Default |
|------|-------------|-----------|:---:|---------|
| Expiry Range | Filters option chain to contracts within DTE window | `min_dte` / `max_dte` | Yes | `14` / `45` days |
| Expiry Selection | Uses nearest valid expiry within range | - | No | First available |
| Strike (Call) | Target strike = current price * strike_pct | `call_strike_pct` | Yes | `1.02` (2% OTM) |
| Strike (Put) | Target strike = current price * strike_pct | `put_strike_pct` | Yes | `0.98` (2% OTM) |
| Strike Rounding | Picks closest available strike to target | - | No | Nearest in chain |
| Contract Qualification | Tries up to 30 strikes across 3 expirations to find valid contract | - | No | - |
| Quantity | `(account_value * position_size_pct * confidence) / (option_price * 100)` | `position_size_pct` | Yes | `0.02` (2%) |
| Quantity Cap | Capped by max position size in dollars | `max_position_size` | Yes | `$2000` |
| Budget Check | If strategy has a budget, reduce quantity to fit available budget | `budget` | Yes | Per-strategy |
| Cost Basis | Skip option if per-contract cost exceeds max | `contract_cost_basis` | Yes | None (no limit) |
| Entry Price | Bid/mid/ask blend, rounded to $0.05 tick | `entry_price_bias` | Yes | `0.0` (mid-price) |

**Entry Price Bias:** `-1` = BID (cheaper, slower fill), `0` = MID (default), `1` = ASK (more expensive, faster fill). Values between are blended linearly.

**Per-Strategy Engine Overrides:** All position selection params (`min_dte`, `max_dte`, `call_strike_pct`, `put_strike_pct`, `profit_target_pct`, `stop_loss_pct`, `max_hold_days`, `entry_price_bias`, `contract_cost_basis`) can be overridden in each strategy's config section. Per-symbol overrides are also supported via `symbol_overrides`.

**Note:** Strike selection is percentage-based (% OTM), NOT delta-based. No Greeks calculation is performed for vanilla swing/scalp trades.

</details>

<details>
<summary><strong>Stop Loss & Take Profit</strong></summary>

| Value | Formula | Parameter | Configurable | Default |
|-------|---------|-----------|:---:|---------|
| Take Profit Price | `entry_price * (1 + profit_target_pct)` | `profit_target_pct` | Yes | `0.50` (+50%) |
| Stop Loss Price | `entry_price * (1 - stop_loss_pct)` | `stop_loss_pct` | Yes | `0.30` (-30%) |
| Price Rounding | Both rounded to nearest $0.05 tick | - | No | - |
| Order Type | Bracket order (OCA group): Entry LMT + TP LMT + SL STP | `use_bracket_orders` | Yes | `true` |
| Time in Force | All bracket orders are Good-Til-Cancelled | - | No | `GTC` |

</details>

<details>
<summary><strong>Operational Parameters</strong></summary>

| Parameter | What It Controls | Configurable | Default | Source |
|-----------|-----------------|:---:|---------|--------|
| `enabled` | Strategy on/off | Yes | `true` | config.yaml |
| `budget` | Max capital allocated to this strategy instance | Yes | Per-strategy | config.yaml |
| `max_positions` | Max concurrent positions for this instance | Yes | `2` | config.yaml |
| `symbols` | Which symbols this instance monitors | Yes | All symbols | config.yaml |
| `daily_loss_limit` | Stop new trades if realized P&L hits this today | Yes | None | config.yaml |
| `max_consecutive_losses` | Pause after N consecutive losing trades | Yes | None | config.yaml |
| `one_trade_per_day` | Only one trade per symbol per day | Yes | `false` | config.yaml |
| `allowed_regimes` | Market regimes where this strategy can trade | Yes | All | config.yaml |
| `min_sector_rs` | Minimum sector relative strength to allow trade | Yes | None | config.yaml |
| `symbol_overrides` | Per-symbol parameter overrides (e.g., wider zones for NVDA) | Yes | None | config.yaml |
| Global: `max_positions` | Global cap across all strategies | Yes | `3` | risk_management |
| Global: `max_daily_loss` | Stop all trading if total daily loss hits this | Yes | `$500` | safety |
| Global: `emergency_stop` | Kill switch for all trading | Yes | `false` | safety |
| Global: `trading_hours_only` | Only trade 9:30 AM - 4:00 PM ET | Yes | `true` | safety |

**Veto Logic** (Trading Engine): Even if a strategy produces a signal, the engine can block it:
- Bullish signals blocked during `Bear_Trend` regime
- Bearish signals blocked during `Bull_Trend` regime
- All Swing/Options signals blocked during `High_Chaos` (only Scalping and ORB allowed)
- Trades blocked if symbol's sector is underperforming SPY (negative RS slope)

</details>
</details>

---

<details>
<summary><strong>Strategy B: Scalping (Momentum)</strong></summary>

This strategy is for speed. It doesn't care about levels; it cares about **Aggression**.

*   **Concept:** If 70%+ of the orders in the book are Buys, price is likely to tick up in the next few seconds/minutes.
*   **Action:** Jump in, grab a small profit, jump out.

<details>
<summary><strong>Entry Conditions</strong></summary>

| Condition | Description | Parameter | Configurable | Default |
|-----------|-------------|-----------|:---:|---------|
| Bullish Imbalance | Order book imbalance > threshold (bids >> asks) | `imbalance_entry_threshold` | Yes | `0.7` (70%) |
| Bearish Imbalance | Order book imbalance < -threshold (asks >> bids) | `imbalance_entry_threshold` | Yes | `0.7` (70%) |
| Confidence | Imbalance value used directly as confidence (capped at 1.0) | - | No | `= abs(imbalance)` |
| Min Confidence | Must exceed this threshold | `min_confidence` | Yes | `0.70` |
| Performance Feedback | Same performance adjustment system as Swing (see above) | `performance_feedback_enabled` | Yes | `true` |

**Imbalance formula:** `(total_bid_volume - total_ask_volume) / (total_bid_volume + total_ask_volume)`

Values range from -1.0 (all sellers) to +1.0 (all buyers).

</details>

<details>
<summary><strong>Exit Conditions</strong></summary>

| Exit Type | How It Works | Parameter | Configurable | Default |
|-----------|-------------|-----------|:---:|---------|
| Take Profit | Same bracket order as Swing | `profit_target_pct` | Yes | `0.50` (50%) |
| Stop Loss | Same bracket order as Swing | `stop_loss_pct` | Yes | `0.30` (30%) |
| Stall Exit (Time Decay) | If price doesn't move favorably within N ticks, signal exit | `max_ticks_without_progress` | Yes | `5` |
| Min Progress | Minimum % move in favorable direction per tick | `min_progress_pct` | Yes | `0.001` (0.1%) |
| Trailing Stop | Same trailing stop logic as Swing (engine-managed) | See Swing | Yes | See Swing |
| Time Limit | Same max hold days | `max_hold_days` | Yes | `30` |

**Time Decay Logic:** The strategy tracks `tick_count` and `entry_price` per symbol. If after N ticks the price hasn't moved at least `min_progress_pct` in the favorable direction, the strategy will generate an exit signal.

</details>

<details>
<summary><strong>Position Selection</strong></summary>

Identical to Swing Trading. See Strategy A for full details. Uses the same `select_option()` and `enter_trade()` flow with % OTM strike selection.

</details>

<details>
<summary><strong>Stop Loss & Take Profit</strong></summary>

Identical to Swing Trading. See Strategy A for full details.

</details>

<details>
<summary><strong>Operational Parameters</strong></summary>

| Parameter | What It Controls | Configurable | Default |
|-----------|-----------------|:---:|---------|
| `max_positions` | Scalping typically limited to 1 at a time | Yes | `1` |
| `budget` | Smaller budget for scalping | Yes | `$1000-1500` |
| `daily_loss_limit` | Tighter daily stop for scalping | Yes | `$150` |
| `allowed_regimes` | Works in all regimes including High Chaos | Yes | All four |
| `pnl_baseline` | Lower baseline for performance feedback (scalp profits are smaller) | Yes | `$20-30` |

Same global safety nets and veto logic as Swing Trading. Both Scalping and ORB are allowed during `High_Chaos`.

</details>
</details>

---

<details>
<summary><strong>Strategy C: VIX Momentum ORB (Opening Range Breakout)</strong></summary>

This strategy watches the "Fear Gauge" (VIX) to confirm moves in the indices (QQQ/SPY).

*   **The Setup:** It marks the high and low price of the first 15 minutes of trading (9:30-9:45 AM).
*   **The Trigger:** If price breaks that range *AND* the VIX confirms it.

<details>
<summary><strong>Entry Conditions</strong></summary>

| Condition | Description | Parameter | Configurable | Default |
|-----------|-------------|-----------|:---:|---------|
| ORB Window | First N minutes define the high/low range | `orb_minutes` | Yes | `15` (9:30-9:45 AM) |
| Trading Window | Minutes after ORB ends to accept signals | `trading_window_minutes` | Yes | `30` (9:45-10:15 AM ET) |
| Bullish Breakout | Price > ORB High AND VIX slope negative (fear decreasing) | - | No | - |
| Bearish Breakout | Price < ORB Low AND VIX slope positive (fear increasing) | - | No | - |
| VIX Slope Window | Minutes of VIX history used to calculate slope | `vix_slope_minutes` | Yes | `5` |
| VIX Divergence | If SPY/QQQ breaks high but VIX also rising = low confidence | `check_vix_divergence` | Yes | `true` |
| Spread Check | Skip trade if bid-ask spread > X% of contract price | `spread_threshold_pct` | Yes | `0.05` (5%) |
| One-and-Done | Only one trade per symbol per day (resets at market open) | `one_trade_per_day` | Yes | `true` |
| VIX Symbol | Which VIX index to monitor | `vix_symbol` | Yes | `'VIX'` |

**Confidence formula:** `min(0.95, 0.8 + abs(vix_slope) * 10)` — steeper VIX slope = higher confidence.

**VIX Slope formula:** `(vix_end - vix_start) / duration_minutes` — simple linear slope over last 5 minutes.

</details>

<details>
<summary><strong>Exit Conditions</strong></summary>

| Exit Type | How It Works | Parameter | Configurable | Default |
|-----------|-------------|-----------|:---:|---------|
| Profit Target | Fixed dollar profit target per position | `target_profit` | Yes | `$300` |
| Stop Loss | Standard bracket order (30% of entry) | `stop_loss_pct` | Yes | `0.30` (30%) |
| Trailing Stop | Engine-managed trailing stop (same as Swing) | See Swing | Yes | See Swing |
| Time Limit | Max hold days (intraday by default) | `max_hold_days` | Yes | `1` |

</details>

<details>
<summary><strong>Position Selection</strong></summary>

| Step | How It Works | Parameter | Configurable | Default |
|------|-------------|-----------|:---:|---------|
| Symbols | Only monitors specific symbols | `symbols` | Yes | `["XSP", "QQQ"]` |
| Cost Basis | Max contract cost — skips options exceeding this | `contract_cost_basis` | Yes | `$150` |
| Expiry/Strike | Same % OTM selection as Swing Trading (per-strategy overrides supported) | See Swing | Yes | See Swing |
| Quantity | Same confidence-scaled sizing as Swing Trading | See Swing | Yes | See Swing |

</details>

<details>
<summary><strong>Operational Parameters</strong></summary>

| Parameter | What It Controls | Configurable | Default |
|-----------|-----------------|:---:|---------|
| `allowed_regimes` | Works during trends and chaos | Yes | `["bull_trend", "bear_trend", "high_chaos"]` |
| `budget` | Capital allocated | Yes | `$2000` |
| State: `_trade_executed_today` | Internal flag per symbol, resets each morning | No | - |
| State: `_orb_high` / `_orb_low` | Tracked per symbol during ORB window | No | - |

**Requires IB Wrapper dependency** (`set_ib_wrapper()`) to subscribe to VIX market data.

**Countdown logging:** Outside of trading windows, logs time until next ORB session (e.g., "ORB ends in 14h 23m (Monday)").

</details>
</details>

---

<details>
<summary><strong>Strategy D: Market Regime Fitted Option Strategies</strong></summary>

These strategies are specialized variations that use **Market Regimes** to select the perfect instrument. Instead of just buying a Call or Put, they trade spreads to lower cost or profit from time decay. All four inherit from `SwingTradingStrategy` and reuse its liquidity analysis.

<details>
<summary><strong>D1: Bull Put Spread (Credit Spread)</strong></summary>

Sell a put spread when price bounces off support in a bullish market.

<details>
<summary><strong>Entry Conditions</strong></summary>

| Condition | Description | Parameter | Configurable | Default |
|-----------|-------------|-----------|:---:|---------|
| Market Regime | Must be `Bull_Trend` | `allowed_regimes` | Yes | `["bull_trend", "range_bound"]` |
| Pattern | Rejection at Support (from Swing analysis) | All Swing params | Yes | See Strategy A |
| Direction Filter | Only accepts bullish signals (LONG_CALL from parent) | - | No | - |
| Confidence | Minimum confidence for support rejection | `rejection_support_confidence` | Yes | `0.70` |
| Signal Conversion | Converts LONG_CALL to BULL_PUT_SPREAD direction | - | No | - |

**Spread legs passed in metadata:** `{short_delta: 30, long_delta: 15, type: 'put'}`

</details>

<details>
<summary><strong>Exit Conditions</strong></summary>

| Exit Type | How It Works | Parameter | Configurable | Default |
|-----------|-------------|-----------|:---:|---------|
| Max Profit | Close at X% of maximum possible credit received | `exit_at_pct_profit` | Yes | `0.50` (50%) |
| Stop Loss | Standard bracket (30%) | `stop_loss_pct` | Yes | `0.30` |

</details>

<details>
<summary><strong>Position Selection</strong></summary>

| Step | How It Works | Parameter | Configurable | Default |
|------|-------------|-----------|:---:|---------|
| Short Leg | Sell put at short_put_delta | `short_put_delta` | Yes | `30` |
| Long Leg | Buy put at long_put_delta (protection) | `long_put_delta` | Yes | `15` |
| Same Expiry | Both legs share the same expiration | - | No | - |
| Expiry/Quantity | Same engine-level selection as Swing Trading | See Swing | Yes | See Swing |

**Note:** Delta-based strike selection is specified in signal metadata but actual execution depends on trading engine support for spread orders.

</details>

<details>
<summary><strong>Operational Parameters</strong></summary>

| Parameter | Default |
|-----------|---------|
| `max_positions` | `2` |
| `budget` | `$2000` |
| `symbols` | `["AAPL", "NVDA", "QQQ", "XSP"]` |
| `min_sector_rs` | Inherited from config |

</details>
</details>

<details>
<summary><strong>D2: Bear Put Spread (Debit Spread)</strong></summary>

Buy a put spread when support breaks down in a bearish market.

<details>
<summary><strong>Entry Conditions</strong></summary>

| Condition | Description | Parameter | Configurable | Default |
|-----------|-------------|-----------|:---:|---------|
| Market Regime | Must be `Bear_Trend` | `allowed_regimes` | Yes | `["bear_trend"]` |
| Pattern | Absorption Breakout Down (from Swing analysis) | All Swing params | Yes | See Strategy A |
| Pattern Filter | Only accepts bearish breakout/absorption patterns | - | No | Pattern name must contain "breakout" or "absorption" |
| Direction Filter | Only accepts LONG_PUT signals from parent | - | No | - |
| Confidence | Minimum confidence for breakout down | `absorption_confidence` | Yes | `0.70` |
| Signal Conversion | Converts LONG_PUT to BEAR_PUT_SPREAD direction | - | No | - |

**Spread legs:** `{long_delta: 50, short_delta: 30, type: 'put'}`

</details>

<details>
<summary><strong>Exit Conditions</strong></summary>

| Exit Type | How It Works | Parameter | Configurable | Default |
|-----------|-------------|-----------|:---:|---------|
| Take Profit | Standard bracket (50%) | `profit_target_pct` | Yes | `0.50` |
| Stop Loss | Standard bracket (30%) | `stop_loss_pct` | Yes | `0.30` |

</details>

<details>
<summary><strong>Position Selection</strong></summary>

| Step | How It Works | Parameter | Configurable | Default |
|------|-------------|-----------|:---:|---------|
| Long Leg | Buy put at long_put_delta (near ATM) | `long_put_delta` | Yes | `50` |
| Short Leg | Sell put at short_put_delta (further OTM) | `short_put_delta` | Yes | `30` |
| Same Expiry | Both legs share the same expiration | - | No | - |

</details>
</details>

<details>
<summary><strong>D3: Long Put (Crash Protection)</strong></summary>

Buy a straight ATM put when the market is breaking down.

<details>
<summary><strong>Entry Conditions</strong></summary>

| Condition | Description | Parameter | Configurable | Default |
|-----------|-------------|-----------|:---:|---------|
| Market Regime | Must be `Bear_Trend` or `High_Chaos` | `allowed_regimes` | Yes | `["bear_trend", "high_chaos"]` |
| Pattern | Absorption Breakout Down (from Swing analysis) | All Swing params | Yes | See Strategy A |
| Pattern Filter | Only breakout/absorption patterns | - | No | Pattern name must contain "breakout" or "absorption" |
| Confidence | Min confidence for absorption breakout (warns if set below 0.75) | `absorption_confidence` | Yes | `0.75` |
| Signal Conversion | Converts LONG_PUT to LONG_PUT_STRAIGHT direction | - | No | - |

**Legs:** `{long_delta: 50, type: 'put'}` — single ATM put.

</details>

<details>
<summary><strong>Exit Conditions</strong></summary>

Same as Swing Trading (bracket TP/SL + trailing stop + time limit).

</details>

<details>
<summary><strong>Operational Parameters</strong></summary>

| Parameter | Default |
|-----------|---------|
| `max_positions` | `2` |
| `budget` | `$1500` |
| `symbols` | `["TSLA", "QQQ", "XSP"]` |

</details>
</details>

<details>
<summary><strong>D4: Iron Condor</strong></summary>

Sell premium on both sides when the market is range-bound.

<details>
<summary><strong>Entry Conditions</strong></summary>

| Condition | Description | Parameter | Configurable | Default |
|-----------|-------------|-----------|:---:|---------|
| Market Regime | Must be `Range_Bound` ONLY | `allowed_regimes` | Yes | `["range_bound"]` |
| Consolidation | Price must be in middle 50% of nearest support/resistance range | - | No | `dist_to_midpoint < range_width * 0.25` |
| Support/Resistance | Must have both confirmed support AND resistance from book analysis | All Swing params | Yes | See Strategy A |
| Confidence | Fixed high confidence when conditions met | `min_confidence` | Yes | `0.80` |

</details>

<details>
<summary><strong>Exit Conditions</strong></summary>

| Exit Type | How It Works | Parameter | Configurable | Default |
|-----------|-------------|-----------|:---:|---------|
| Max Profit | Close at X% of credit received | `exit_at_pct_profit` | Yes | `0.50` (50%) |
| DTE Exit | Auto-close when N days remain to expiration | `exit_at_dte` | Yes | `21` DTE |
| Stop Loss | Standard bracket | `stop_loss_pct` | Yes | `0.30` |

</details>

<details>
<summary><strong>Position Selection</strong></summary>

| Step | How It Works | Parameter | Configurable | Default |
|------|-------------|-----------|:---:|---------|
| Short Put | Sell put at short_put_delta | `short_put_delta` | Yes | `15` |
| Long Put | Buy put at long_put_delta (wing protection) | `long_put_delta` | Yes | `5` |
| Short Call | Sell call at short_call_delta | `short_call_delta` | Yes | `15` |
| Long Call | Buy call at long_call_delta (wing protection) | `long_call_delta` | Yes | `5` |
| All Same Expiry | All four legs share the same expiration | - | No | - |

</details>

<details>
<summary><strong>Operational Parameters</strong></summary>

| Parameter | Default |
|-----------|---------|
| `max_positions` | `2` |
| `budget` | `$2500` |
| `symbols` | `["AAPL", "MSFT", "QQQ", "XSP"]` (stable stocks) |

</details>
</details>
</details>

---

## 3. Market Regime Detection

The bot checks the "weather" before going outside. Two global context modules run on a schedule and provide information to all strategies.

<details>
<summary><strong>Market Regime Detector</strong></summary>

Uses SPY and VIX historical data to classify the market into one of four states.

| Regime | Conditions | Effect on Strategies |
|--------|-----------|---------------------|
| **Bull Trend** | SPY > 200-day MA AND VIX < 20 | Bullish strategies allowed. Bearish vetoed |
| **Bear Trend** | SPY < 200-day MA OR VIX > 30 | Bearish strategies allowed. Bullish vetoed |
| **Range Bound** | SPY in 2% range over 10 days AND VIX 15-25 | Iron Condor allowed. Standard strategies OK |
| **High Chaos** | VIX spike > 20% in 5 days OR SPY daily vol > 2% OR VIX > 30 | Only Scalping and ORB allowed. All other strategies blocked |

**Priority order:** High Chaos > Bear Trend > Range Bound > Bull Trend

<details>
<summary><strong>Parameters</strong></summary>

| Parameter | Description | Configurable | Default | Source |
|-----------|-------------|:---:|---------|--------|
| `high_chaos_vix_threshold` | VIX level that triggers High Chaos | Yes | `30.0` | market_regime config |
| `high_chaos_vix_change_pct` | VIX spike % over 5 days for High Chaos | Yes | `0.20` (20%) | market_regime config |
| `high_chaos_spy_vol_pct` | SPY daily realized vol threshold | Yes | `0.02` (2%) | market_regime config |
| `bull_trend_vix_threshold` | Max VIX for Bull Trend | Yes | `20.0` | market_regime config |
| `range_bound_vix_min` | Min VIX for Range Bound | Yes | `15.0` | market_regime config |
| `range_bound_vix_max` | Max VIX for Range Bound | Yes | `25.0` | market_regime config |
| SPY 200-day SMA | Calculated from 1 year of daily bars | No | - | IB historical data |
| Update frequency | Recalculated every N minutes | Yes | `30` min (`update_interval_minutes`) | market_regime config |

</details>
</details>

<details>
<summary><strong>Sector Rotation Manager</strong></summary>

Calculates Relative Strength of 11 Sector ETFs vs SPY. Used to veto trades in weak sectors.

**Sectors tracked:** XLK, XLE, XLF, XLV, XLI, XLP, XLY, XLB, XLU, XLRE, XLC

**RS Formula:** `Sector_Price / SPY_Price` ratio. A positive slope = Outperforming.

| Parameter | Description | Configurable | Default |
|-----------|-------------|:---:|---------|
| RS Window | Number of periods for slope calculation | Yes | `5` (`rs_window`) |
| Bar Size | Candlestick timeframe for RS data | Yes | `'1 hour'` (`bar_size`) |
| Duration | Lookback duration for RS data | Yes | `'5 D'` (`duration`) |
| Update Frequency | How often rotation is recalculated | Yes | `60` min (`update_interval_minutes`) |
| `min_sector_rs` | Per-strategy config: minimum RS slope to allow trade | Yes | `0.0` or None |
| Symbol-Sector Map | Maps stock symbols to sector ETFs | Yes | Via IB industry or `symbol_sector_overrides` config |

**Slope formula:** `(last_ratio - first_ratio) / num_periods`

</details>

---

## 4. Risk Management & Safety

The bot is paranoid by design. It assumes every trade could be a loser.

<details>
<summary><strong>The Safety Nets</strong></summary>

### Global Safety
| Feature | Description | Parameter | Configurable | Default |
|---------|-------------|-----------|:---:|---------|
| Emergency Stop | Kill switch — blocks ALL trading | `emergency_stop` | Yes | `false` |
| Max Daily Loss | Stop all new trades if total daily P&L hits limit | `max_daily_loss` | Yes | `$500` |
| Max Consecutive Losses | Pause all trading after N consecutive losses | `max_consecutive_losses` | Yes | None |
| Market Hours Only | Only trade 9:30 AM - 4:00 PM ET | `trading_hours_only` | Yes | `true` |
| Manual Approval | Require human confirmation before each trade | `require_manual_approval` | Yes | `false` |
| IB Connection Check | Skip position management if IB disconnected | - | No | - |

### Per-Strategy Safety
| Feature | Description | Parameter | Configurable | Default |
|---------|-------------|-----------|:---:|---------|
| Strategy Budget | Max capital committed to a strategy instance | `budget` | Yes | Per-strategy |
| Strategy Max Positions | Max concurrent positions per strategy | `max_positions` | Yes | Per-strategy |
| Strategy Daily Loss | Stop strategy if it loses $X today | `daily_loss_limit` | Yes | None |
| Strategy Consecutive Losses | Pause strategy after N consecutive losses | `max_consecutive_losses` | Yes | None |
| One Trade Per Day | Limit to one trade per symbol per day | `one_trade_per_day` | Yes | `false` |

### Bracket Orders (Position-Level)
| Feature | Description | Parameter | Configurable | Default |
|---------|-------------|-----------|:---:|---------|
| Entry Order | Limit order at biased price (rounded to $0.05) | `entry_price_bias` | Yes | `0.0` (mid) |
| Stop Loss | Attached stop order (OCA with TP) | `stop_loss_pct` | Yes | `0.30` (30%) |
| Take Profit | Attached limit order (OCA with SL) | `profit_target_pct` | Yes | `0.50` (50%) |
| Trailing Stop | Engine-managed, adjusts based on peak price | `trailing_stop_enabled` | Yes | `true` |
| Order Timeout | Cancel unfilled entry orders after N seconds | `order_timeout_seconds` | Yes | `60` |
| Price Drift | Cancel if price moves > X% from limit | `price_drift_threshold` | Yes | `0.10` (10%) |

### The "Drain" Rule
When a strategy is disallowed by market regime or daily loss limit, the engine does NOT force-close existing positions. It simply blocks NEW entries, allowing open positions to exit naturally via their TP/SL/trailing stop.

</details>

---
*Generated for engineering review — reflects actual implementation.*
