"""
Swing Trading Strategy

Analyzes order book liquidity to identify support/resistance zones
and generates trade signals based on price action at these levels.

This strategy looks for:
- Price bouncing off support (bullish - buy calls)
- Price rejecting at resistance (bearish - buy puts)
- Order book imbalance suggesting breakout
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

from .base_strategy import BaseStrategy, StrategySignal, TradeDirection

logger = logging.getLogger(__name__)


class Pattern(Enum):
    """Trading pattern types detected by this strategy."""
    TESTING_SUPPORT = "testing_support"
    TESTING_RESISTANCE = "testing_resistance"
    POTENTIAL_BREAKOUT_UP = "potential_breakout_up"
    POTENTIAL_BREAKOUT_DOWN = "potential_breakout_down"
    CONSOLIDATION = "consolidation"
    REJECTION_AT_SUPPORT = "rejection_at_support"
    REJECTION_AT_RESISTANCE = "rejection_at_resistance"


@dataclass
class LiquidityZone:
    """Represents a liquidity zone in the order book."""
    price: float
    size: int
    zone_type: str  # 'support' or 'resistance'
    strength: float  # Relative strength (0-1)


class SwingTradingStrategy(BaseStrategy):
    """
    Swing trading strategy based on order book liquidity analysis.

    Identifies support/resistance zones from Level 2 order book data
    and generates signals when price interacts with these zones.

    Trading Logic:
    - REJECTION_AT_SUPPORT → LONG_CALL (bullish bounce)
    - REJECTION_AT_RESISTANCE → LONG_PUT (bearish rejection)
    - POTENTIAL_BREAKOUT_UP → LONG_CALL (momentum)
    - POTENTIAL_BREAKOUT_DOWN → LONG_PUT (momentum)

    Requires Level 2 market data subscription for full functionality.
    """

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)

        # Initialize internal state
        self.previous_price: Dict[str, float] = {}  # symbol -> last price

        # Trading rules: pattern -> (direction, min_confidence)
        self._rules = {
            Pattern.REJECTION_AT_SUPPORT: (
                TradeDirection.LONG_CALL,
                self.get_config('rejection_support_confidence', 0.65)
            ),
            Pattern.REJECTION_AT_RESISTANCE: (
                TradeDirection.LONG_PUT,
                self.get_config('rejection_resistance_confidence', 0.65)
            ),
            Pattern.POTENTIAL_BREAKOUT_UP: (
                TradeDirection.LONG_CALL,
                self.get_config('breakout_up_confidence', 0.70)
            ),
            Pattern.POTENTIAL_BREAKOUT_DOWN: (
                TradeDirection.LONG_PUT,
                self.get_config('breakout_down_confidence', 0.70)
            ),
        }

    @property
    def name(self) -> str:
        return "swing_trading"

    @property
    def description(self) -> str:
        return (
            "Swing trading strategy using order book liquidity analysis. "
            "Identifies support/resistance zones and trades bounces/rejections."
        )

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_default_config(self) -> Dict[str, Any]:
        """Return default configuration for swing trading strategy."""
        return {
            # Liquidity analysis parameters
            'liquidity_threshold': 1000,    # Min size for zone identification
            'zone_proximity': 0.10,         # Distance to trigger detection ($)
            'imbalance_threshold': 0.6,     # Imbalance cutoff for breakout
            'num_levels': 10,               # Depth levels to analyze

            # Confidence thresholds for each pattern
            'rejection_support_confidence': 0.65,
            'rejection_resistance_confidence': 0.65,
            'breakout_up_confidence': 0.70,
            'breakout_down_confidence': 0.70,
        }

    def analyze(self, ticker: Any, current_price: float,
                context: Dict[str, Any] = None) -> Optional[StrategySignal]:
        """
        Analyze order book and generate trade signal.

        Args:
            ticker: ib_insync Ticker with domBids/domAsks
            current_price: Current stock price
            context: Optional context with 'symbol' key

        Returns:
            StrategySignal if opportunity detected, None otherwise
        """
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')

        # Detect pattern from order book
        pattern_result = self._detect_pattern(ticker, current_price, symbol)

        if pattern_result is None:
            return None

        pattern, confidence, price_level, imbalance, metadata = pattern_result

        # Check if pattern maps to a trade
        if pattern not in self._rules:
            return None

        direction, min_confidence = self._rules[pattern]

        # Check confidence threshold
        if confidence < min_confidence:
            logger.debug(
                f"{symbol}: {pattern.value} confidence {confidence:.2f} "
                f"below threshold {min_confidence:.2f}"
            )
            return None

        # Generate signal
        return StrategySignal(
            direction=direction,
            confidence=confidence,
            pattern_name=pattern.value,
            price_level=price_level,
            metadata={
                'imbalance': imbalance,
                'pattern': pattern.value,
                **metadata
            }
        )

    def _detect_pattern(self, ticker: Any, current_price: float,
                        symbol: str) -> Optional[tuple]:
        """
        Detect trading pattern from order book.

        Returns:
            Tuple of (pattern, confidence, price_level, imbalance, metadata)
            or None if only consolidation detected
        """
        # Analyze order book
        analysis = self._analyze_book(ticker)

        # Check for support zone interaction
        for zone in analysis['support']:
            distance = abs(current_price - zone.price)
            if distance <= self.get_config('zone_proximity', 0.10):
                if self._is_bouncing_off_support(current_price, zone.price, symbol):
                    return (
                        Pattern.REJECTION_AT_SUPPORT,
                        zone.strength,
                        zone.price,
                        analysis['imbalance'],
                        {'zone_size': zone.size}
                    )
                else:
                    return (
                        Pattern.TESTING_SUPPORT,
                        zone.strength * 0.7,
                        zone.price,
                        analysis['imbalance'],
                        {'zone_size': zone.size}
                    )

        # Check for resistance zone interaction
        for zone in analysis['resistance']:
            distance = abs(current_price - zone.price)
            if distance <= self.get_config('zone_proximity', 0.10):
                if self._is_rejecting_at_resistance(current_price, zone.price, symbol):
                    return (
                        Pattern.REJECTION_AT_RESISTANCE,
                        zone.strength,
                        zone.price,
                        analysis['imbalance'],
                        {'zone_size': zone.size}
                    )
                else:
                    return (
                        Pattern.TESTING_RESISTANCE,
                        zone.strength * 0.7,
                        zone.price,
                        analysis['imbalance'],
                        {'zone_size': zone.size}
                    )

        # Check for breakout based on imbalance
        imbalance_threshold = self.get_config('imbalance_threshold', 0.6)

        if analysis['imbalance'] > imbalance_threshold:
            return (
                Pattern.POTENTIAL_BREAKOUT_UP,
                abs(analysis['imbalance']),
                None,
                analysis['imbalance'],
                {'bid_depth': analysis['bid_depth_total']}
            )

        if analysis['imbalance'] < -imbalance_threshold:
            return (
                Pattern.POTENTIAL_BREAKOUT_DOWN,
                abs(analysis['imbalance']),
                None,
                analysis['imbalance'],
                {'ask_depth': analysis['ask_depth_total']}
            )

        # Consolidation - no actionable signal
        return None

    def _analyze_book(self, ticker: Any) -> Dict:
        """Analyze order book to identify liquidity zones."""
        if not ticker.domBids or not ticker.domAsks:
            return {
                'support': [],
                'resistance': [],
                'bid_depth_total': 0,
                'ask_depth_total': 0,
                'imbalance': 0
            }

        # Extract liquidity by price level
        bid_liquidity = {bid.price: bid.size for bid in ticker.domBids if bid.price > 0}
        ask_liquidity = {ask.price: ask.size for ask in ticker.domAsks if ask.price > 0}

        # Identify significant liquidity zones
        support_zones = self._identify_zones(bid_liquidity, 'support')
        resistance_zones = self._identify_zones(ask_liquidity, 'resistance')

        # Calculate metrics
        total_bid = sum(bid_liquidity.values())
        total_ask = sum(ask_liquidity.values())
        imbalance = self._calculate_imbalance(total_bid, total_ask)

        return {
            'support': support_zones,
            'resistance': resistance_zones,
            'bid_depth_total': total_bid,
            'ask_depth_total': total_ask,
            'imbalance': imbalance,
        }

    def _identify_zones(self, liquidity: Dict[float, int],
                        zone_type: str) -> List[LiquidityZone]:
        """Identify significant liquidity zones."""
        if not liquidity:
            return []

        zones = []
        max_size = max(liquidity.values()) if liquidity else 1
        threshold = self.get_config('liquidity_threshold', 1000)

        for price, size in liquidity.items():
            if size >= threshold:
                strength = size / max_size
                zones.append(LiquidityZone(
                    price=price,
                    size=size,
                    zone_type=zone_type,
                    strength=strength
                ))

        # Sort by strength (strongest first)
        zones.sort(key=lambda z: z.strength, reverse=True)
        return zones

    def _calculate_imbalance(self, total_bid: int, total_ask: int) -> float:
        """Calculate order book imbalance (-1 to 1)."""
        total = total_bid + total_ask
        if total == 0:
            return 0.0
        return (total_bid - total_ask) / total

    def _is_bouncing_off_support(self, current_price: float,
                                  support_level: float, symbol: str) -> bool:
        """Detect if price is bouncing off support."""
        previous = self.previous_price.get(symbol)
        self.previous_price[symbol] = current_price

        if previous is None:
            return False

        # Price was at/below support and is now moving up
        return previous <= support_level and current_price > support_level

    def _is_rejecting_at_resistance(self, current_price: float,
                                     resistance_level: float, symbol: str) -> bool:
        """Detect if price is rejecting at resistance."""
        previous = self.previous_price.get(symbol)
        self.previous_price[symbol] = current_price

        if previous is None:
            return False

        # Price was at/above resistance and is now moving down
        return previous >= resistance_level and current_price < resistance_level

    def get_analysis(self, ticker: Any, current_price: float) -> Dict:
        """
        Get detailed order book analysis without generating a signal.

        Useful for debugging or displaying market state.
        """
        analysis = self._analyze_book(ticker)
        return {
            'support_zones': [
                {'price': z.price, 'size': z.size, 'strength': z.strength}
                for z in analysis['support']
            ],
            'resistance_zones': [
                {'price': z.price, 'size': z.size, 'strength': z.strength}
                for z in analysis['resistance']
            ],
            'bid_depth': analysis['bid_depth_total'],
            'ask_depth': analysis['ask_depth_total'],
            'imbalance': analysis['imbalance'],
            'current_price': current_price,
        }
