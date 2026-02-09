# Trading Strategies

This directory contains plugin-based trading strategies for the trading bot.

## Architecture

```
strategies/
├── __init__.py           # Package exports
├── base_strategy.py      # Abstract base class (interface)
├── strategy_manager.py   # Plugin loader and orchestrator
├── swing_trading.py      # Built-in swing trading strategy
├── template_strategy.py  # Template for creating new strategies
└── README.md             # This file
```

## Creating a New Strategy

1. Copy `template_strategy.py` to `my_strategy.py`
2. Rename the class to `MyStrategy`
3. Update the `name`, `description`, and `version` properties
4. Define your config parameters in `get_default_config()`
5. Implement your trading logic in `analyze()`

### Example

```python
from .base_strategy import BaseStrategy, StrategySignal, TradeDirection

class MyStrategy(BaseStrategy):
    @property
    def name(self) -> str:
        return "my_strategy"

    @property
    def description(self) -> str:
        return "My custom trading strategy"

    def get_default_config(self):
        return {
            'enabled': True,
            'threshold': 0.7,
        }

    def analyze(self, ticker, current_price, context=None):
        # Your analysis logic here
        if some_bullish_condition:
            return StrategySignal(
                direction=TradeDirection.LONG_CALL,
                confidence=0.8,
                pattern_name="my_pattern"
            )
        return None
```

## Configuration

Add your strategy to `config.yaml`. You can run **multiple instances** of the same strategy type with different configurations:

```yaml
strategies:
  # Multiple instances of same strategy type
  swing_conservative:
    type: swing_trading           # Strategy type
    enabled: true
    budget: 2000                  # Per-strategy budget ($)
    zone_proximity_pct: 0.005     # 0.5% - wider proximity
    min_confidence: 0.75          # Higher confidence required

  swing_aggressive:
    type: swing_trading           # Same type, different config
    enabled: true
    budget: 1500
    zone_proximity_pct: 0.003     # 0.3% - tighter proximity
    min_confidence: 0.65          # Lower confidence threshold

  # Backward compatible: if 'type' not specified, instance name = type
  my_strategy:
    enabled: true
    budget: 1000
    threshold: 0.8
```

### Strategy Instance vs Type

- **Instance name**: Unique identifier (e.g., `swing_conservative`, `swing_aggressive`)
- **Strategy type**: The actual strategy class (e.g., `swing_trading`, `scalping`)
- Multiple instances of the same type can run with different configurations
- Each instance has its own budget and tracks P&L separately

## Per-Strategy Budgets

Each strategy instance can have its own budget with drawdown tracking:

```yaml
strategies:
  swing_conservative:
    type: swing_trading
    budget: 2000    # Maximum budget for this strategy
```

**Budget model:**
- **Losses** reduce available budget (increase drawdown)
- **Wins** recover budget up to the cap (decrease drawdown)
- **Profits beyond the cap** don't increase available budget
- Formula: `available = budget - drawdown`

Use `/budgets` command to see current budget status for all strategies.

## Built-in Strategies

### SwingTradingStrategy (`swing_trading`)

Analyzes Level 2 order book data to identify support/resistance zones
and trades bounces/rejections at these levels. Uses time-persistence and
state machine tracking for level confirmation.

**Signals:**
- `REJECTION_AT_SUPPORT` → LONG_CALL (bullish bounce)
- `REJECTION_AT_RESISTANCE` → LONG_PUT (bearish rejection)
- `ABSORPTION_BREAKOUT` → Trade in direction of absorption

**Config parameters:**
- `zone_proximity_pct`: Proximity as % of price (default: 0.005 = 0.5%)
- `min_confidence`: Minimum confidence to generate signal (default: 0.70)
- `zscore_threshold`: Z-score for level significance (default: 3.0)
- `rejection_support_confidence`: Min confidence for support bounce (default: 0.65)
- `rejection_resistance_confidence`: Min confidence for resistance rejection (default: 0.65)
- `imbalance_weight`: How much imbalance affects confidence (default: 0.3)

### ScalpingStrategy (`scalping`)

High-frequency strategy based on order book imbalance. Looks for strong
directional pressure for quick momentum trades.

**Signals:**
- Strong positive imbalance (bids >> asks) → LONG_CALL
- Strong negative imbalance (asks >> bids) → LONG_PUT

**Config parameters:**
- `imbalance_entry_threshold`: Min imbalance to enter (default: 0.7)
- `imbalance_exit_threshold`: Imbalance to trigger exit (default: 0.3)
- `max_ticks_without_progress`: Ticks before time-decay exit (default: 5)
- `min_confidence`: Minimum confidence (default: 0.70)
- `zone_proximity_pct`: Proximity as % of price (default: 0.0005 = 0.05%)

### VIXMomentumORB (`vix_momentum_orb`)

15-minute Opening Range Breakout (ORB) strategy filtered by VIX momentum.

**Signals:**
- `ORB_BREAKOUT_BULLISH` → LONG_CALL (Price > ORB High & VIX down)
- `ORB_BREAKOUT_BEARISH` → LONG_PUT (Price < ORB Low & VIX up)

**Config parameters:**
- `orb_minutes`: Duration of opening range (default: 15)
- `vix_symbol`: Symbol for VIX data (default: VIX)
- `vix_slope_minutes`: Lookback for VIX trend (default: 5)
- `check_vix_divergence`: Enable divergence filter (default: True)

## Strategy Interface

### Required Methods

| Method | Description |
|--------|-------------|
| `name` | Unique strategy identifier (property) |
| `description` | Human-readable description (property) |
| `get_default_config()` | Return default configuration dict |
| `analyze(ticker, price, context)` | Analyze and return signal or None |

### Optional Methods

| Method | Description |
|--------|-------------|
| `version` | Strategy version string (property, default "1.0.0") |
| `validate_config()` | Return list of config errors |
| `on_position_opened(position)` | Called when position opens |
| `on_position_closed(position, reason)` | Called when position closes |

### StrategySignal

```python
@dataclass
class StrategySignal:
    direction: TradeDirection    # LONG_CALL, LONG_PUT, or NO_TRADE
    confidence: float            # 0.0 to 1.0
    pattern_name: str = ""       # Human-readable name
    price_level: float = None    # Key price level
    metadata: dict = {}          # Extra data
```

### Context Dict

The `context` argument passed to `analyze()` contains:

```python
{
    'symbol': 'AAPL',           # Stock symbol
    'positions': [...],         # Current Position objects
    'account_value': 100000.0,  # Account value
}
```

## Multi-Strategy Support

The StrategyManager can run multiple strategies simultaneously:

```python
from strategies import StrategyManager

manager = StrategyManager(config)
manager.load_all_configured()

# Get signals from all enabled strategies
signals = manager.analyze_all(ticker, price, context)

# Or get just the highest confidence signal
best_signal = manager.get_best_signal(ticker, price, context)
```

## Testing Your Strategy

Add tests to `test_integration.py` or create a separate test file:

```python
from strategies import SwingTradingStrategy

strategy = SwingTradingStrategy({'liquidity_threshold': 500})
signal = strategy.analyze(ticker, current_price, {'symbol': 'AAPL'})

if signal:
    print(f"Signal: {signal.direction} @ {signal.confidence:.2f}")
```
