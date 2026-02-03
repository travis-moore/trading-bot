"""
Base Strategy Interface

All trading strategies must inherit from BaseStrategy and implement
the required abstract methods.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum


class TradeDirection(Enum):
    """Direction for a trade signal."""
    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    NO_TRADE = "no_trade"


@dataclass
class StrategySignal:
    """
    Signal output from a strategy.

    This is the contract between strategies and the trading engine.
    Strategies produce signals, the engine decides whether to act on them.
    """
    # Required fields
    direction: TradeDirection       # What action to take
    confidence: float               # 0.0 to 1.0, how confident the strategy is

    # Optional context
    pattern_name: str = ""          # Human-readable pattern description
    price_level: Optional[float] = None   # Key price level (support/resistance)

    # Strategy-specific metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate signal."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be 0-1, got {self.confidence}")


@dataclass
class StrategyConfig:
    """
    Configuration for a strategy.

    Strategies define their own config schema via get_default_config().
    """
    name: str                       # Strategy identifier
    enabled: bool = True            # Whether strategy is active
    parameters: Dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    Strategies are responsible for:
    - Analyzing market data (order book, price action)
    - Generating trade signals with confidence levels
    - Defining their own configuration parameters

    Strategies should NOT:
    - Place orders directly
    - Manage positions
    - Handle risk management (that's the engine's job)

    Example implementation:

        class MyStrategy(BaseStrategy):
            @property
            def name(self) -> str:
                return "my_strategy"

            @property
            def description(self) -> str:
                return "My custom trading strategy"

            def analyze(self, ticker, current_price, context) -> Optional[StrategySignal]:
                # Your analysis logic here
                if some_condition:
                    return StrategySignal(
                        direction=TradeDirection.LONG_CALL,
                        confidence=0.8,
                        pattern_name="My Pattern"
                    )
                return None
    """

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize strategy with configuration.

        Args:
            config: Strategy-specific configuration parameters.
                   If None, uses get_default_config().
        """
        self._config = config or self.get_default_config()

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique identifier for this strategy.
        Used for config lookup and logging.
        """
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """
        Human-readable description of what this strategy does.
        """
        pass

    @property
    def version(self) -> str:
        """Strategy version for tracking changes."""
        return "1.0.0"

    @abstractmethod
    def get_default_config(self) -> Dict[str, Any]:
        """
        Return default configuration for this strategy.

        This defines the schema of parameters the strategy accepts.
        Users can override these in config.yaml under strategies.<name>.

        Returns:
            Dict of parameter names to default values.
        """
        pass

    @abstractmethod
    def analyze(self, ticker: Any, current_price: float,
                context: Dict[str, Any] = None) -> Optional[StrategySignal]:
        """
        Analyze market data and generate a trade signal.

        This is the main entry point called by the trading engine.

        Args:
            ticker: ib_insync Ticker object with market data.
                   Contains: domBids, domAsks (order book depth),
                            bid, ask, last (current quotes)
            current_price: Current stock price.
            context: Optional dict with additional context:
                    - 'positions': List of current Position objects
                    - 'account_value': Current account value
                    - 'symbol': The symbol being analyzed

        Returns:
            StrategySignal if a trade opportunity is detected,
            None if no signal (or NO_TRADE direction).
        """
        pass

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a configuration parameter."""
        return self._config.get(key, default)

    def set_config(self, key: str, value: Any):
        """Set a configuration parameter."""
        self._config[key] = value

    @property
    def config(self) -> Dict[str, Any]:
        """Get full configuration."""
        return self._config.copy()

    def validate_config(self) -> List[str]:
        """
        Validate current configuration.

        Override to add custom validation logic.

        Returns:
            List of validation error messages (empty if valid).
        """
        errors = []
        defaults = self.get_default_config()

        for key in defaults:
            if key not in self._config:
                errors.append(f"Missing required config: {key}")

        return errors

    def on_position_opened(self, position: Any):
        """
        Called when a position is opened based on this strategy's signal.

        Override to track state or adjust behavior.

        Args:
            position: The Position object that was opened.
        """
        pass

    def on_position_closed(self, position: Any, reason: str):
        """
        Called when a position is closed.

        Override to track state or learn from outcomes.

        Args:
            position: The Position object that was closed.
            reason: Why it was closed (profit_target, stop_loss, etc.)
        """
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name='{self.name}' v{self.version}>"
