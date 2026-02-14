# Architecture Documentation

## System Overview

The Swing Trading Bot is an automated options trading system that uses real-time order book (Level 2) analysis to detect trading opportunities. It connects to Interactive Brokers via the `ib_insync` library, runs multiple configurable strategy instances simultaneously, and manages positions with bracket orders, trailing stops, and per-strategy budgets.

```
                      +-----------------+
                      |    config.yaml  |
                      +--------+--------+
                               |
                      +--------v--------+
                      |     main.py     |  <- Orchestrator, CLI, Lifecycle
                      | SwingTradingBot |
                      +--------+--------+
                               |
        +----------+-----------+----------+-----------+
        |          |           |          |           |
   +----v----+ +---v---+ +----v----+ +---v----+ +----v-----+
   |   IB    | |Liqui- | |Trading  | |Trade   | | Strategy |
   | Wrapper | |dity   | | Engine  | |Database| | Manager  |
   |         | |Analyz.| |         | |(SQLite)| |          |
   +---------+ +-------+ +---------+ +--------+ +----------+
        |                      |                      |
        |                +-----+-----+         +------+------+
        |                |           |         |      |      |
        |          +-----v---+ +----v----+  +--v--+ +-v--+ +-v--+
        |          | Market  | | Market  |  |Swing| |Scal| |ORB |
        |          | Regime  | | Snap-   |  |Trad.| |ping| |    |
        |          |Detector | | shots   |  +-----+ +----+ +----+
        |          +---------+ +---------+    |
        |                                     +-- Options Strategies
        |                                         (Bull Put, Bear Put,
        +--> Discord Notifier                      Long Put, Iron Condor)
```

## Component Responsibilities

### main.py — `SwingTradingBot`

The top-level coordinator. Handles:

- **Lifecycle**: `initialize()` -> `run()` -> `shutdown()`
- **Main Loop**: Scan for signals -> Check positions -> Process commands -> Sleep
- **Configuration**: Loads `config.yaml`, passes sections to each component
- **Signal Handling**: Ctrl+C graceful shutdown (second Ctrl+C force-exits)
- **Interactive Commands**: `/status`, `/positions`, `/strategies`, `/pnl`, etc.
- **Position Reconciliation**: On startup, syncs database with IB account state
- **Market Data Subscriptions**: Level 1 (price) and Level 2 (depth) per symbol
- **Context Scheduling**: Periodically refreshes Market Regime and Sector Rotation

### ib_wrapper.py — `IBWrapper`

Clean interface over `ib_insync` for all broker operations:

- **Connection**: Connect/disconnect, connection health checks
- **Market Data**: Subscribe to Level 1 (price) and Level 2 (depth), historical bars
- **Order Management**: Buy/sell options, bracket orders, trailing stops, order modification/cancellation
- **Account**: Portfolio queries, account value, positions
- **Option Chain**: Fetch chains, filter by DTE, find specific contracts

Includes a patch for an `ib_insync` bug where `updateMktDepthL2` crashes on out-of-range positions.

### liquidity_analyzer.py — `LiquidityAnalyzer`

Analyzes order book depth to identify trading patterns (legacy system, used as fallback):

- **Zone Detection**: Identifies support/resistance levels from bid/ask liquidity clusters
- **Imbalance Calculation**: Measures buy vs. sell pressure (-1 to +1)
- **Pattern Detection**: Classifies market state (support test, resistance test, breakout, consolidation)
- **Confidence Scoring**: Combines zone strength with imbalance confirmation

### trading_engine.py — `TradingEngine`

Core trading logic and execution:

- **Signal Evaluation**: Applies veto logic (regime, sector RS, position limits)
- **Option Selection**: Finds appropriate contracts by % OTM, DTE range
- **Order Placement**: Bracket orders with entry + stop loss + take profit
- **Position Management**: Tracks pending orders and open positions
- **Exit Logic**: Checks bracket fills, trailing stops, time limits, manual closes
- **Budget Enforcement**: Checks strategy budgets before entering trades
- **Market Snapshots**: Records order book state at signal and execution phases
- **Per-Strategy Overrides**: Engine parameters can be overridden per-strategy and per-symbol

### trade_db.py — `TradeDatabase`

SQLite persistence layer:

- **Position CRUD**: Insert, update, close positions atomically
- **Trade History**: Full audit trail with P&L
- **Strategy Budgets**: Drawdown-based budget model with committed capital tracking
- **Signal Logging**: Records all signals for opportunity utilization analysis
- **Historical Bar Cache**: Caches IB historical data to reduce API calls
- **Reporting**: Performance metrics, daily P&L, frequency analysis, CSV export

### strategies/ — Plugin System

#### StrategyManager

Loads, configures, and orchestrates strategy plugins:

- **Dynamic Loading**: Discovers `.py` files in strategies directory
- **Multi-Instance**: Same strategy type with different configs (e.g., `swing_conservative`, `swing_aggressive`)
- **Hot Reload**: Reload strategies from disk without restarting
- **Auto-Discovery**: Periodically scans for new strategy files

#### BaseStrategy (Abstract)

Interface contract for all strategies:

- `analyze(ticker, price, context)` -> `StrategySignal` or `None`
- `get_default_config()` -> default parameter dict
- Built-in helpers: `is_price_near_level()`, `is_significant_level()`, `calculate_zscore()`
- Performance feedback system: adjusts confidence based on recent win rate/P&L

#### Strategy Implementations

| Strategy | Type Key | Description |
|----------|----------|-------------|
| SwingTradingStrategy | `swing_trading` | Support/resistance bounce detection with historical power levels |
| ScalpingStrategy | `scalping` | Order book imbalance momentum trading |
| VIXMomentumORB | `vix_momentum_orb` | Opening range breakout with VIX confirmation |
| BullPutSpreadStrategy | `bull_put_spread` | Credit spread at support in bull markets |
| BearPutSpreadStrategy | `bear_put_spread` | Debit spread on breakdowns in bear markets |
| LongPutStrategy | `long_put` | Straight put on breakdowns in bear/chaos markets |
| IronCondorStrategy | `iron_condor` | Premium selling in range-bound markets |

### market_context.py

Two global context managers:

- **MarketRegimeDetector**: Classifies market as Bull Trend, Bear Trend, Range Bound, or High Chaos using SPY 200-day SMA, VIX level, and realized volatility
- **SectorRotationManager**: Calculates relative strength slopes for 11 sector ETFs vs SPY

### notifications.py — `DiscordNotifier`

Sends alerts to Discord via webhook:

- Simple text messages (bot start/stop, alerts)
- Formatted trade alert embeds with color coding (green = calls, red = puts)

### market_snapshot.py — `MarketSnapshot`

Captures market state at critical moments:

- **Signal Phase**: Order book, spread, regime at time of signal
- **Execution Phase**: Fill price, latency, post-fill order book
- Saved as JSON files in `snapshots/` directory asynchronously (non-blocking)

### snapshot_analyzer.py — `SnapshotAnalyzer`

Post-trade analysis utility:

- Single-trade slippage analysis with order book wall visualization
- Global execution quality report (requires pandas)

## Data Flow

### Signal Detection to Trade Execution

```
1. Main Loop (scan_for_signals)
   |
2. Get current price (Level 1 ticker)
   |
3. StrategyManager.analyze_all(ticker, price, context)
   |-- Each enabled strategy runs analyze()
   |-- Returns list of StrategySignal objects
   |
4. For each signal:
   |-- Engine.evaluate_signal(signal)
   |   |-- Check market regime vs allowed_regimes
   |   |-- Check sector RS vs min_sector_rs
   |   |-- Apply veto logic
   |   |-- Return TradeDirection or None
   |
5. If direction valid:
   |-- Engine.enter_trade(symbol, direction, signal)
   |   |-- Check per-strategy max_positions
   |   |-- Check duplicate symbol/strategy
   |   |-- Check one_trade_per_day rule
   |   |-- Select option contract (% OTM, DTE range)
   |   |-- Calculate entry price with bias
   |   |-- Check contract_cost_basis limit
   |   |-- Check strategy budget
   |   |-- Record signal snapshot
   |   |-- Insert pending position in DB
   |   |-- Place bracket order via IB
   |   |-- Track as PendingOrder
   |
6. check_pending_orders() (each loop iteration)
   |-- Check for fills -> convert to Position
   |-- Check for cancellation/rejection
   |-- Check for timeout with price drift
   |-- On fill: commit budget, record execution snapshot, notify Discord
   |
7. check_exits() (each loop iteration)
   |-- Check bracket order fills (TP/SL)
   |-- Detect manual closes from IB portfolio
   |-- Check trailing stop activation
   |-- Check max hold days
   |-- On exit: release budget, record in trade_history
```

### Budget Flow

```
Strategy Config: budget = $2000
                    |
            +-------v--------+
            | strategy_budgets|  available = budget - drawdown - committed
            +-------+--------+
                    |
    Enter Trade ----+----> commit_budget(cost)    committed += cost
                    |
    Exit Trade  ----+----> release_budget(cost, exit_value)
                    |          committed -= cost
                    |          drawdown = max(0, drawdown - pnl)
                    |
    Win: drawdown decreases (recovers budget up to cap)
    Loss: drawdown increases (reduces available budget)
```

## Concurrency Model

- **Single-threaded main loop**: All IB API calls and strategy analysis run synchronously in the main thread via `ib_insync`'s event loop
- **Command reader thread**: Background daemon thread reads stdin for interactive commands
- **Snapshot writer threads**: Market snapshots saved asynchronously via daemon threads
- **Interruptible sleep**: Main loop sleep broken into 0.5s chunks checking `self.running`

## External Dependencies

| Dependency | Purpose |
|-----------|---------|
| Interactive Brokers TWS/Gateway | Broker connection (must be running locally) |
| Discord Webhook (optional) | Trade notifications and alerts |
| SQLite | Local database (no server required) |

## File Organization

```
trading-bot/
  main.py                     # Entry point, orchestrator
  config.yaml                 # All configuration
  ib_wrapper.py               # IB API interface
  liquidity_analyzer.py       # Order book analysis
  trading_engine.py           # Trade execution & position management
  trade_db.py                 # SQLite persistence
  market_context.py           # Regime detection & sector rotation
  market_snapshot.py          # Snapshot data structures
  snapshot_analyzer.py        # Post-trade analysis CLI
  notifications.py            # Discord notifications
  requirements.txt            # Python dependencies
  trading_bot.db              # SQLite database (generated)
  trading_bot.log             # Log file (rotated daily)
  snapshots/                  # Market snapshot JSON files
  strategies/
    __init__.py               # Package exports
    base_strategy.py          # Abstract base class
    strategy_manager.py       # Plugin loader
    swing_trading.py          # Swing trading strategy
    scalping.py               # Scalping strategy
    vix_momentum_orb.py       # VIX ORB strategy
    options_strategies.py     # Bull/Bear Put Spread, Long Put, Iron Condor
    template_strategy.py      # Template for creating new strategies
  docs/                       # Documentation
  TRADING_LOGIC.md            # Detailed trading logic reference
  SNAPSHOT_README.md          # Market snapshot system docs
```
