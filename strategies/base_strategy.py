"""
Base Strategy Interface

All trading strategies must inherit from BaseStrategy and implement
the required abstract methods.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
from datetime import datetime, timedelta
import statistics
import logging

logger = logging.getLogger(__name__)


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

    def get_config(self, key: str, default: Any = None, symbol: Optional[str] = None) -> Any:
        """Get a configuration parameter, optionally checking symbol-specific overrides."""
        if symbol:
            overrides = self._config.get('symbol_overrides', {}).get(symbol, {})
            if key in overrides:
                return overrides[key]
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
                            atr_multiplier: float = 0.5,
                            symbol: Optional[str] = None) -> bool:
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
            symbol: Optional symbol for config overrides

        Returns:
            True if price is within the proximity zone of the level
        """
        pct = proximity_pct if proximity_pct is not None else self.get_config('zone_proximity_pct', 0.005, symbol=symbol)

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
                               atr_multiplier: float = 0.5,
                               symbol: Optional[str] = None) -> float:
        """
        Calculate the proximity distance for a given price.

        Args:
            price: Current price
            proximity_pct: Percentage proximity (e.g., 0.005 = 0.5%)
            atr: Average True Range value (optional)
            atr_multiplier: Multiplier for ATR-based proximity
            symbol: Optional symbol for config overrides

        Returns:
            The proximity distance in dollars
        """
        pct = proximity_pct if proximity_pct is not None else self.get_config('zone_proximity_pct', 0.005, symbol=symbol)

        if atr is not None and atr > 0:
            return atr * atr_multiplier
        else:
            return price * pct

    def is_in_exclusion_zone(self, price: float, level: float,
                             exclusion_pct: Optional[float] = None,
                             symbol: Optional[str] = None) -> bool:
        """
        Check if a level is within the exclusion zone around current price.

        The exclusion zone filters out market maker noise near the current price.

        Args:
            price: Current price
            level: The price level to check
            exclusion_pct: Exclusion zone as percentage (default 0.5% = 0.005)
            symbol: Optional symbol for config overrides

        Returns:
            True if level is within the exclusion zone (should be ignored)
        """
        pct = exclusion_pct if exclusion_pct is not None else self.get_config('exclusion_zone_pct', 0.005, symbol=symbol)

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
                             zscore_threshold: Optional[float] = None,
                             symbol: Optional[str] = None) -> bool:
        """
        Determine if a volume level is statistically significant.

        Uses z-score filtering: only levels with volume > N standard deviations
        above the local average are considered significant.

        Args:
            volume: Volume at the price level to check
            nearby_volumes: List of volumes at nearby price levels
            zscore_threshold: Minimum z-score to be significant (default 3.0)
            symbol: Optional symbol for config overrides

        Returns:
            True if the volume is statistically significant
        """
        threshold = zscore_threshold if zscore_threshold is not None else self.get_config('zscore_threshold', 3.0, symbol=symbol)

        if len(nearby_volumes) < 2:
            return volume > 0

        zscore = self.calculate_zscore(float(volume), [float(v) for v in nearby_volumes])
        return zscore >= threshold

    # =========================================================================
    # Performance Feedback System
    # =========================================================================

    def set_trade_db(self, db: Any):
        """
        Set trade database for performance feedback.

        Called by the trading engine to inject the database dependency.
        """
        self._trade_db = db

    def _get_performance_metrics(self, strategy_name: str) -> Optional[Dict[str, Any]]:
        """
        Get recent performance metrics for this strategy instance.

        Queries the trade database for closed trades within the lookback window
        and calculates win rate and P&L statistics.

        Args:
            strategy_name: The strategy instance name (e.g., 'swing_conservative')

        Returns:
            Dict with keys: win_rate, total_pnl, avg_pnl, trade_count
            Returns None if performance feedback is disabled or insufficient data
        """
        if not self.get_config('performance_feedback_enabled', False):
            return None

        if not hasattr(self, '_trade_db') or self._trade_db is None:
            return None

        lookback_days = self.get_config('performance_lookback_days', 14)
        min_trades = self.get_config('min_trades_for_feedback', 5)

        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)

        try:
            trades = self._trade_db.query_trades(
                strategy=strategy_name,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                limit=500,
            )

            if len(trades) < min_trades:
                return None

            # Calculate metrics
            wins = sum(1 for t in trades if t['pnl'] > 0)
            total_pnl = sum(t['pnl'] for t in trades)
            avg_pnl = total_pnl / len(trades)
            win_rate = wins / len(trades)

            return {
                'win_rate': win_rate,
                'total_pnl': total_pnl,
                'avg_pnl': avg_pnl,
                'trade_count': len(trades),
                'wins': wins,
                'losses': len(trades) - wins,
            }

        except Exception as e:
            logger.debug(f"Error getting performance metrics: {e}")
            return None

    def _calculate_performance_modifier(self, strategy_name: str) -> float:
        """
        Calculate confidence modifier based on recent performance.

        Uses a combination of win rate and P&L to adjust confidence:
        - Good performance (high win rate, positive P&L) → boost confidence
        - Poor performance (low win rate, negative P&L) → reduce confidence

        The modifier is multiplicative: final_confidence = base_confidence * modifier

        Args:
            strategy_name: The strategy instance name

        Returns:
            Modifier between (1 - max_penalty) and (1 + max_boost), default 1.0
        """
        metrics = self._get_performance_metrics(strategy_name)

        if metrics is None:
            return 1.0  # No adjustment

        win_rate = metrics['win_rate']
        avg_pnl = metrics['avg_pnl']

        # Get config parameters
        boost_threshold = self.get_config('win_rate_boost_threshold', 0.60)
        penalty_threshold = self.get_config('win_rate_penalty_threshold', 0.40)
        max_boost = self.get_config('max_confidence_boost', 0.15)
        max_penalty = self.get_config('max_confidence_penalty', 0.20)
        pnl_weight = self.get_config('pnl_weight', 0.3)

        modifier = 0.0

        # Win rate component (70% weight by default)
        win_rate_weight = 1.0 - pnl_weight

        if win_rate >= boost_threshold:
            # Scale boost linearly from threshold to 1.0
            boost_range = 1.0 - boost_threshold
            boost_pct = (win_rate - boost_threshold) / boost_range if boost_range > 0 else 0
            modifier += max_boost * boost_pct * win_rate_weight
        elif win_rate <= penalty_threshold:
            # Scale penalty linearly from threshold to 0.0
            penalty_range = penalty_threshold
            penalty_pct = (penalty_threshold - win_rate) / penalty_range if penalty_range > 0 else 0
            modifier -= max_penalty * penalty_pct * win_rate_weight

        # P&L component (30% weight by default)
        # Use average P&L relative to a baseline (e.g., $50 avg profit = good)
        pnl_baseline = self.get_config('pnl_baseline', 50.0)
        if avg_pnl > 0:
            # Positive P&L: boost proportional to avg_pnl / baseline, capped
            pnl_boost = min(max_boost, (avg_pnl / pnl_baseline) * max_boost)
            modifier += pnl_boost * pnl_weight
        elif avg_pnl < 0:
            # Negative P&L: penalty proportional to |avg_pnl| / baseline, capped
            pnl_penalty = min(max_penalty, (abs(avg_pnl) / pnl_baseline) * max_penalty)
            modifier -= pnl_penalty * pnl_weight

        # Convert modifier to multiplicative factor
        # modifier ranges from -max_penalty to +max_boost
        # We want result to be (1 - max_penalty) to (1 + max_boost)
        final_modifier = 1.0 + modifier

        # Clamp to reasonable bounds
        min_modifier = 1.0 - max_penalty
        max_modifier = 1.0 + max_boost
        final_modifier = max(min_modifier, min(max_modifier, final_modifier))

        # Log significant adjustments
        if abs(final_modifier - 1.0) >= 0.05:
            instance_name = self.get_config('instance_name', strategy_name)
            logger.info(
                f"{instance_name}: Performance modifier={final_modifier:.2f} "
                f"(win_rate={win_rate:.1%}, avg_pnl=${avg_pnl:.2f}, trades={metrics['trade_count']})"
            )

        return final_modifier

    def apply_performance_feedback(self, confidence: float, strategy_name: str) -> float:
        """
        Apply performance-based confidence adjustment.

        Call this method before returning a signal to adjust confidence
        based on the strategy's recent track record.

        Args:
            confidence: The raw confidence from pattern detection
            strategy_name: The strategy instance name for database lookup

        Returns:
            Adjusted confidence (still clamped to 0.0-1.0)
        """
        modifier = self._calculate_performance_modifier(strategy_name)
        adjusted = confidence * modifier
        return max(0.0, min(1.0, adjusted))
