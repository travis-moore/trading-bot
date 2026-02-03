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

Add your strategy to `config.yaml`:

```yaml
strategies:
  swing_trading:
    enabled: true
    liquidity_threshold: 1000
    zone_proximity: 0.10

  my_strategy:
    enabled: true
    threshold: 0.8
```

## Built-in Strategies

### SwingTradingStrategy (`swing_trading`)

Analyzes Level 2 order book data to identify support/resistance zones
and trades bounces/rejections at these levels.

**Signals:**
- `REJECTION_AT_SUPPORT` → LONG_CALL (bullish bounce)
- `REJECTION_AT_RESISTANCE` → LONG_PUT (bearish rejection)
- `POTENTIAL_BREAKOUT_UP` → LONG_CALL (momentum)
- `POTENTIAL_BREAKOUT_DOWN` → LONG_PUT (momentum)

**Config parameters:**
- `liquidity_threshold`: Min size for zone identification (default: 1000)
- `zone_proximity`: Distance to trigger detection in $ (default: 0.10)
- `imbalance_threshold`: Order imbalance cutoff (default: 0.6)
- `rejection_support_confidence`: Min confidence for support bounce (default: 0.65)
- `rejection_resistance_confidence`: Min confidence for resistance rejection (default: 0.65)
- `breakout_up_confidence`: Min confidence for bullish breakout (default: 0.70)
- `breakout_down_confidence`: Min confidence for bearish breakout (default: 0.70)

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
