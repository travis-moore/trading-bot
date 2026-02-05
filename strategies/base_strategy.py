"""
Base Strategy Interface

All trading strategies must inherit from BaseStrategy and implement
the required abstract methods.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
import statistics


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

    def __init__(self, config: Optional[Dict[str, Any]] = None):
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

        Missing keys are NOT errors - they use defaults from get_default_config().
        Override to add custom validation logic for invalid values.

        Returns:
            List of validation error messages (empty if valid).
        """
        # By default, no validation errors.
        # Subclasses can override to check for invalid values.
        # Missing keys just use defaults, so they're not errors.
        return []

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

    # =========================================================================
    # Proportional Calculation Methods (inherited by all strategies)
    # =========================================================================

    def is_price_near_level(self, price: float, level: float,
                            proximity_pct: Optional[float] = None,
                            atr: Optional[float] = None,
                            atr_multiplier: float = 0.5) -> bool:
        """
        Check if price is within proximity of a level using proportional scaling.

        Uses percentage-based proximity by default, or ATR-based if ATR is provided.

        Args:
            price: Current price
            level: The price level to check against
            proximity_pct: Percentage proximity (e.g., 0.005 = 0.5%)
                          If None, uses config 'zone_proximity_pct'
            atr: Average True Range value (optional, for volatility-adjusted proximity)
            atr_multiplier: Multiplier for ATR-based proximity (default 0.5)

        Returns:
            True if price is within the proximity zone of the level
        """
        pct = proximity_pct if proximity_pct is not None else self.get_config('zone_proximity_pct', 0.005)

        # Calculate proximity distance
        if atr is not None and atr > 0:
            # ATR-based proximity: use atr_multiplier * ATR
            proximity_distance = atr * atr_multiplier
        else:
            # Percentage-based proximity: |P - L| <= P * proximity_pct
            proximity_distance = price * pct

        distance = abs(price - level)
        return distance <= proximity_distance

    def get_proximity_distance(self, price: float,
                               proximity_pct: Optional[float] = None,
                               atr: Optional[float] = None,
                               atr_multiplier: float = 0.5) -> float:
        """
        Calculate the proximity distance for a given price.

        Args:
            price: Current price
            proximity_pct: Percentage proximity (e.g., 0.005 = 0.5%)
            atr: Average True Range value (optional)
            atr_multiplier: Multiplier for ATR-based proximity

        Returns:
            The proximity distance in dollars
        """
        pct = proximity_pct if proximity_pct is not None else self.get_config('zone_proximity_pct', 0.005)

        if atr is not None and atr > 0:
            return atr * atr_multiplier
        else:
            return price * pct

    def is_in_exclusion_zone(self, price: float, level: float,
                             exclusion_pct: Optional[float] = None) -> bool:
        """
        Check if a level is within the exclusion zone around current price.

        The exclusion zone filters out market maker noise near the current price.

        Args:
            price: Current price
            level: The price level to check
            exclusion_pct: Exclusion zone as percentage (default 0.5% = 0.005)

        Returns:
            True if level is within the exclusion zone (should be ignored)
        """
        pct = exclusion_pct if exclusion_pct is not None else self.get_config('exclusion_zone_pct', 0.005)

        exclusion_distance = price * pct
        distance = abs(price - level)
        return distance <= exclusion_distance

    def calculate_zscore(self, value: float, values: List[float]) -> float:
        """
        Calculate z-score of a value relative to a list of values.

        Args:
            value: The value to calculate z-score for
            values: List of reference values

        Returns:
            Z-score (number of standard deviations from mean)
        """
        if len(values) < 2:
            return 0.0

        mean = statistics.mean(values)
        stdev = statistics.stdev(values)

        if stdev == 0:
            return 0.0

        return (value - mean) / stdev

    def is_significant_level(self, volume: int, nearby_volumes: List[int],
                             zscore_threshold: Optional[float] = None) -> bool:
        """
        Determine if a volume level is statistically significant.

        Uses z-score filtering: only levels with volume > N standard deviations
        above the local average are considered significant.

        Args:
            volume: Volume at the price level to check
            nearby_volumes: List of volumes at nearby price levels
            zscore_threshold: Minimum z-score to be significant (default 3.0)

        Returns:
            True if the volume is statistically significant
        """
        threshold = zscore_threshold if zscore_threshold is not None else self.get_config('zscore_threshold', 3.0)

        if len(nearby_volumes) < 2:
            return volume > 0

        zscore = self.calculate_zscore(float(volume), [float(v) for v in nearby_volumes])
        return zscore >= threshold
