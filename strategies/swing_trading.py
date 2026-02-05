"""
Swing Trading Strategy

Analyzes order book liquidity to identify support/resistance zones
and generates trade signals based on price action at these levels.

Enhanced Features:
- Z-Score filtering for statistically significant levels
- Time-persistence confirmation (levels must hold for 5 minutes)
- Dynamic exclusion zone to filter market maker noise
- Interaction state machine (Absorption, Rejection, Spoofing detection)
- Proportional proximity using percentage-based calculations

This strategy looks for:
- Price bouncing off confirmed support (bullish - buy calls)
- Price rejecting at confirmed resistance (bearish - buy puts)
- Imbalance is used as a confidence multiplier, NOT as entry trigger
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta
import statistics

from .base_strategy import BaseStrategy, StrategySignal, TradeDirection

logger = logging.getLogger(__name__)


class Pattern(Enum):
    """Trading pattern types detected by this strategy."""
    TESTING_SUPPORT = "testing_support"
    TESTING_RESISTANCE = "testing_resistance"
    REJECTION_AT_SUPPORT = "rejection_at_support"
    REJECTION_AT_RESISTANCE = "rejection_at_resistance"
    ABSORPTION_BREAKOUT_UP = "absorption_breakout_up"
    ABSORPTION_BREAKOUT_DOWN = "absorption_breakout_down"
    CONSOLIDATION = "consolidation"
    SPOOFING_DETECTED = "spoofing_detected"


class LevelState(Enum):
    """State of a price level in the interaction state machine."""
    PENDING = "pending"          # Level detected but not confirmed
    CONFIRMED = "confirmed"      # Level held for required time
    ABSORBING = "absorbing"      # Volume being absorbed (iceberg)
    REJECTED = "rejected"        # Price rejected at level
    INVALIDATED = "invalidated"  # Level spoofed or broken


@dataclass
class LiquidityZone:
    """Represents a liquidity zone in the order book."""
    price: float
    size: int
    zone_type: str  # 'support' or 'resistance'
    strength: float  # Relative strength (0-1)
    zscore: float = 0.0  # Statistical significance


@dataclass
class TrackedLevel:
    """A price level being tracked for confirmation and state transitions."""
    price: float
    zone_type: str  # 'support' or 'resistance'
    first_seen: datetime
    last_seen: datetime
    initial_volume: int
    current_volume: int
    volume_traded: int = 0  # Volume absorbed at this level
    state: LevelState = LevelState.PENDING
    refresh_count: int = 0  # Times volume refreshed (iceberg behavior)


class SwingTradingStrategy(BaseStrategy):
    """
    Swing trading strategy based on order book liquidity analysis.

    Enhanced with:
    - Z-score filtering for statistically significant levels (>3σ)
    - Time-persistence: levels must hold for 5 minutes to be confirmed
    - Dynamic exclusion zone: ±0.5% dead zone around current price
    - Interaction state machine for Absorption/Rejection/Spoofing

    Trading Logic:
    - REJECTION_AT_SUPPORT → LONG_CALL (bullish bounce)
    - REJECTION_AT_RESISTANCE → LONG_PUT (bearish rejection)
    - ABSORPTION_BREAKOUT → Trade in direction of absorption

    Imbalance is used as a confidence multiplier, not an entry trigger.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

        # Price history for pattern detection
        self.previous_price: Dict[str, float] = {}  # symbol -> last price

        # Level tracking for time-persistence and state machine
        self._tracked_levels: Dict[str, Dict[float, TrackedLevel]] = {}  # symbol -> {price: level}

        # Volume history for absorption detection
        self._volume_history: Dict[str, Dict[float, List[int]]] = {}  # symbol -> {price: [volumes]}

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
            Pattern.ABSORPTION_BREAKOUT_UP: (
                TradeDirection.LONG_CALL,
                self.get_config('absorption_confidence', 0.75)
            ),
            Pattern.ABSORPTION_BREAKOUT_DOWN: (
                TradeDirection.LONG_PUT,
                self.get_config('absorption_confidence', 0.75)
            ),
        }

    @property
    def name(self) -> str:
        return "swing_trading"

    @property
    def description(self) -> str:
        return (
            "Swing trading strategy using order book liquidity analysis. "
            "Identifies confirmed support/resistance zones with Z-score filtering "
            "and trades bounces/rejections with imbalance-adjusted confidence."
        )

    @property
    def version(self) -> str:
        return "2.0.0"

    def get_default_config(self) -> Dict[str, Any]:
        """Return default configuration for swing trading strategy."""
        return {
            # Position limits (per strategy instance)
            'max_positions': 2,                 # Max concurrent positions for this strategy

            # Liquidity analysis parameters
            'liquidity_threshold': 1000,        # Base min size for zone identification
            'num_levels': 10,                   # Depth levels to analyze for local stats

            # Proportional proximity (percentage-based)
            'zone_proximity_pct': 0.005,        # 0.5% proximity to trigger detection
            'exclusion_zone_pct': 0.005,        # 0.5% dead zone around price

            # Z-score filtering
            'zscore_threshold': 3.0,            # Min standard deviations for significance
            'zscore_levels_count': 10,          # Number of nearby levels for local average

            # Time-persistence
            'level_confirmation_minutes': 5,    # Minutes level must persist to confirm

            # Interaction state machine
            'absorption_threshold_pct': 0.20,   # 20% volume traded = absorption
            'rejection_imbalance_flip': 0.60,   # 60% imbalance flip = rejection
            'spoofing_distance_ticks': 3,       # Cancel within 3 ticks = spoofing

            # Confidence thresholds for each pattern
            'rejection_support_confidence': 0.65,
            'rejection_resistance_confidence': 0.65,
            'absorption_confidence': 0.75,

            # Imbalance weighting (not entry trigger, just confidence modifier)
            'imbalance_weight': 0.3,            # How much imbalance affects confidence
        }

    def analyze(self, ticker: Any, current_price: float,
                context: Optional[Dict[str, Any]] = None) -> Optional[StrategySignal]:
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
        now = datetime.now()

        # Initialize tracking for this symbol
        if symbol not in self._tracked_levels:
            self._tracked_levels[symbol] = {}
        if symbol not in self._volume_history:
            self._volume_history[symbol] = {}

        # Analyze order book with Z-score filtering
        analysis = self._analyze_book_advanced(ticker, current_price, symbol)

        # Update level tracking and state machine
        self._update_level_tracking(symbol, analysis, current_price, now)

        # Check for spoofing
        spoofed_levels = self._detect_spoofing(symbol, analysis, current_price)
        instance_name = self.get_config('instance_name', self.name)
        for level_price in spoofed_levels:
            logger.info(f"{instance_name} ({symbol}): Spoofing detected at ${level_price:.2f}")

        # Get confirmed levels only
        confirmed_support = self._get_confirmed_levels(symbol, 'support')
        confirmed_resistance = self._get_confirmed_levels(symbol, 'resistance')

        # Log current state
        support_str = f"${confirmed_support[0].price:.2f}" if confirmed_support else "none"
        resistance_str = f"${confirmed_resistance[0].price:.2f}" if confirmed_resistance else "none"

        # Detect pattern from confirmed levels
        pattern_result = self._detect_pattern(
            ticker, current_price, symbol, analysis,
            confirmed_support, confirmed_resistance
        )

        # Determine pattern name and confidence for logging
        if pattern_result is None:
            pattern_name = "consolidation"
            confidence_val = 0.0
        else:
            pattern, confidence_val, price_level, imbalance, metadata = pattern_result
            pattern_name = pattern.value

        # Use instance_name from config for logging (falls back to strategy type name)
        instance_name = self.get_config('instance_name', self.name)
        logger.info(
            f"{instance_name} ({symbol}): price=${current_price:.2f}, "
            f"support={support_str}, resistance={resistance_str}, "
            f"pattern={pattern_name}, confidence={confidence_val:.2f}"
        )

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
                'strategy_type': 'swing_trading',
                **metadata
            }
        )

    def _analyze_book_advanced(self, ticker: Any, current_price: float,
                                symbol: str) -> Dict:
        """
        Analyze order book with Z-score filtering and exclusion zone.

        Returns zones that are:
        - Statistically significant (>3σ above local average)
        - Outside the exclusion zone (±0.5% from current price)
        """
        if not ticker.domBids or not ticker.domAsks:
            return {
                'support': [],
                'resistance': [],
                'bid_depth_total': 0,
                'ask_depth_total': 0,
                'imbalance': 0,
                'raw_bids': {},
                'raw_asks': {}
            }

        # Extract raw liquidity
        bid_liquidity = {bid.price: bid.size for bid in ticker.domBids if bid.price > 0}
        ask_liquidity = {ask.price: ask.size for ask in ticker.domAsks if ask.price > 0}

        # Calculate exclusion zone
        exclusion_pct = self.get_config('exclusion_zone_pct', 0.005)

        # Identify significant zones with Z-score filtering
        support_zones = self._identify_zones_zscore(
            bid_liquidity, 'support', current_price, exclusion_pct
        )
        resistance_zones = self._identify_zones_zscore(
            ask_liquidity, 'resistance', current_price, exclusion_pct
        )

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
            'raw_bids': bid_liquidity,
            'raw_asks': ask_liquidity
        }

    def _identify_zones_zscore(self, liquidity: Dict[float, int], zone_type: str,
                                current_price: float, exclusion_pct: float) -> List[LiquidityZone]:
        """
        Identify significant liquidity zones using Z-score filtering.

        Only zones with volume >3σ above local average are considered.
        Zones within the exclusion zone are filtered out.
        """
        if not liquidity:
            return []

        zones = []
        prices = sorted(liquidity.keys())
        volumes = [liquidity[p] for p in prices]

        if len(volumes) < 2:
            return []

        # Calculate local statistics for Z-score
        zscore_levels = self.get_config('zscore_levels_count', 10)
        zscore_threshold = self.get_config('zscore_threshold', 3.0)
        liquidity_threshold = self.get_config('liquidity_threshold', 1000)
        max_size = max(volumes) if volumes else 1

        for i, price in enumerate(prices):
            size = liquidity[price]

            # Skip if below base threshold
            if size < liquidity_threshold:
                continue

            # Skip if in exclusion zone
            if self.is_in_exclusion_zone(current_price, price, exclusion_pct):
                continue

            # Get nearby volumes for local Z-score calculation
            start_idx = max(0, i - zscore_levels // 2)
            end_idx = min(len(volumes), i + zscore_levels // 2 + 1)
            nearby = volumes[start_idx:end_idx]

            # Calculate Z-score
            if len(nearby) >= 2:
                zscore = self.calculate_zscore(float(size), [float(v) for v in nearby])
            else:
                zscore = 0.0

            # Only include if statistically significant
            if zscore >= zscore_threshold:
                strength = size / max_size
                zones.append(LiquidityZone(
                    price=price,
                    size=size,
                    zone_type=zone_type,
                    strength=strength,
                    zscore=zscore
                ))

        # Sort by strength
        zones.sort(key=lambda z: z.strength, reverse=True)
        return zones

    def _update_level_tracking(self, symbol: str, analysis: Dict,
                                current_price: float, now: datetime):
        """
        Update tracking for level time-persistence and state machine.

        Levels must persist for 5 minutes to become confirmed.
        """
        tracked = self._tracked_levels[symbol]
        confirmation_time = timedelta(minutes=self.get_config('level_confirmation_minutes', 5))

        # Track all significant zones from current analysis
        all_zones = analysis['support'] + analysis['resistance']
        current_prices = {z.price for z in all_zones}

        # Update existing tracked levels
        for price in list(tracked.keys()):
            level = tracked[price]

            if price in current_prices:
                # Level still exists - update it
                zone = next(z for z in all_zones if z.price == price)
                level.last_seen = now
                level.current_volume = zone.size

                # Check for volume refresh (iceberg behavior)
                if zone.size > level.current_volume * 0.8:
                    level.refresh_count += 1

                # Update volume history for absorption detection
                if price not in self._volume_history[symbol]:
                    self._volume_history[symbol][price] = []
                self._volume_history[symbol][price].append(zone.size)
                # Keep only last 20 observations
                self._volume_history[symbol][price] = self._volume_history[symbol][price][-20:]

                # Check for confirmation
                if level.state == LevelState.PENDING:
                    if now - level.first_seen >= confirmation_time:
                        level.state = LevelState.CONFIRMED
                        logger.debug(f"Level confirmed: ${price:.2f} ({level.zone_type})")

            else:
                # Level disappeared
                age = now - level.last_seen
                if age > timedelta(seconds=30):
                    # Level gone for 30+ seconds - could be spoofing or broken
                    if level.state == LevelState.CONFIRMED:
                        level.state = LevelState.INVALIDATED
                    del tracked[price]

        # Add new levels
        for zone in all_zones:
            if zone.price not in tracked:
                tracked[zone.price] = TrackedLevel(
                    price=zone.price,
                    zone_type=zone.zone_type,
                    first_seen=now,
                    last_seen=now,
                    initial_volume=zone.size,
                    current_volume=zone.size,
                    state=LevelState.PENDING
                )

    def _detect_spoofing(self, symbol: str, analysis: Dict,
                          current_price: float) -> List[float]:
        """
        Detect potential spoofing: large orders pulled as price approaches.

        Returns list of prices where spoofing was detected.
        """
        spoofed = []
        tracked = self._tracked_levels[symbol]
        spoof_distance = self.get_config('spoofing_distance_ticks', 3)

        # Calculate approximate tick size (0.01 for most stocks)
        tick_size = 0.01
        spoof_range = spoof_distance * tick_size

        for price, level in list(tracked.items()):
            if level.state != LevelState.CONFIRMED:
                continue

            distance = abs(current_price - price)

            # Check if price is within spoof range and level disappeared
            if distance <= spoof_range:
                # Check if this level's volume dropped significantly
                history = self._volume_history.get(symbol, {}).get(price, [])
                if len(history) >= 2:
                    recent_vol = history[-1] if history else 0
                    prev_vol = history[-2] if len(history) >= 2 else level.initial_volume

                    # Volume dropped by >50% as price approached
                    if recent_vol < prev_vol * 0.5:
                        spoofed.append(price)
                        level.state = LevelState.INVALIDATED
                        logger.warning(f"Spoofing detected at ${price:.2f}")

        return spoofed

    def _get_confirmed_levels(self, symbol: str,
                               zone_type: str) -> List[TrackedLevel]:
        """Get confirmed levels of specified type, sorted by strength."""
        tracked = self._tracked_levels.get(symbol, {})
        confirmed = [
            level for level in tracked.values()
            if level.zone_type == zone_type and level.state == LevelState.CONFIRMED
        ]
        # Sort by current volume (proxy for strength)
        confirmed.sort(key=lambda l: l.current_volume, reverse=True)
        return confirmed

    def _detect_pattern(self, ticker: Any, current_price: float, symbol: str,
                        analysis: Dict, confirmed_support: List[TrackedLevel],
                        confirmed_resistance: List[TrackedLevel]) -> Optional[tuple]:
        """
        Detect trading pattern from confirmed levels and state machine.

        Returns:
            Tuple of (pattern, confidence, price_level, imbalance, metadata)
            or None if only consolidation detected
        """
        imbalance = analysis['imbalance']
        proximity_pct = self.get_config('zone_proximity_pct', 0.005)
        absorption_threshold = self.get_config('absorption_threshold_pct', 0.20)
        rejection_flip = self.get_config('rejection_imbalance_flip', 0.60)

        # Check support zones
        for level in confirmed_support:
            if self.is_price_near_level(current_price, level.price, proximity_pct):
                # Check for absorption (breakout signal)
                if self._is_absorbing(symbol, level, absorption_threshold):
                    confidence = self._adjust_confidence_by_imbalance(
                        level.current_volume / level.initial_volume,
                        imbalance, bullish=True
                    )
                    return (
                        Pattern.ABSORPTION_BREAKOUT_UP,
                        confidence,
                        level.price,
                        imbalance,
                        {'absorption': True, 'refresh_count': level.refresh_count}
                    )

                # Check for rejection (bounce signal)
                if self._is_bouncing_off_support(current_price, level.price, symbol):
                    # Check imbalance confirms the bounce
                    if imbalance > -rejection_flip:  # Not heavily bearish
                        base_confidence = min(1.0, level.current_volume / 10000)
                        confidence = self._adjust_confidence_by_imbalance(
                            base_confidence, imbalance, bullish=True
                        )
                        return (
                            Pattern.REJECTION_AT_SUPPORT,
                            confidence,
                            level.price,
                            imbalance,
                            {'zone_size': level.current_volume}
                        )
                else:
                    # Just testing support
                    base_confidence = min(1.0, level.current_volume / 10000) * 0.7
                    return (
                        Pattern.TESTING_SUPPORT,
                        base_confidence,
                        level.price,
                        imbalance,
                        {'zone_size': level.current_volume}
                    )

        # Check resistance zones
        for level in confirmed_resistance:
            if self.is_price_near_level(current_price, level.price, proximity_pct):
                # Check for absorption (breakout signal)
                if self._is_absorbing(symbol, level, absorption_threshold):
                    confidence = self._adjust_confidence_by_imbalance(
                        level.current_volume / level.initial_volume,
                        imbalance, bullish=False
                    )
                    return (
                        Pattern.ABSORPTION_BREAKOUT_DOWN,
                        confidence,
                        level.price,
                        imbalance,
                        {'absorption': True, 'refresh_count': level.refresh_count}
                    )

                # Check for rejection
                if self._is_rejecting_at_resistance(current_price, level.price, symbol):
                    # Check imbalance confirms the rejection
                    if imbalance < rejection_flip:  # Not heavily bullish
                        base_confidence = min(1.0, level.current_volume / 10000)
                        confidence = self._adjust_confidence_by_imbalance(
                            base_confidence, imbalance, bullish=False
                        )
                        return (
                            Pattern.REJECTION_AT_RESISTANCE,
                            confidence,
                            level.price,
                            imbalance,
                            {'zone_size': level.current_volume}
                        )
                else:
                    # Just testing resistance
                    base_confidence = min(1.0, level.current_volume / 10000) * 0.7
                    return (
                        Pattern.TESTING_RESISTANCE,
                        base_confidence,
                        level.price,
                        imbalance,
                        {'zone_size': level.current_volume}
                    )

        # No pattern at confirmed levels
        return None

    def _is_absorbing(self, symbol: str, level: TrackedLevel,
                       threshold: float) -> bool:
        """
        Detect if a level is absorbing volume (iceberg behavior).

        Absorption = volume being traded but level refreshing.
        """
        # Need refresh behavior + volume consumption
        if level.refresh_count < 2:
            return False

        # Check volume history for consumption pattern
        history = self._volume_history.get(symbol, {}).get(level.price, [])
        if len(history) < 3:
            return False

        # Volume should be fluctuating (being consumed and refreshed)
        vol_variance = statistics.variance(history) if len(history) >= 2 else 0
        avg_vol = statistics.mean(history)

        # High variance relative to mean indicates absorption
        cv = (vol_variance ** 0.5) / avg_vol if avg_vol > 0 else 0
        return cv > 0.3  # Coefficient of variation > 30%

    def _calculate_imbalance(self, total_bid: int, total_ask: int) -> float:
        """Calculate order book imbalance (-1 to 1)."""
        total = total_bid + total_ask
        if total == 0:
            return 0.0
        return (total_bid - total_ask) / total

    def _adjust_confidence_by_imbalance(self, base_confidence: float,
                                         imbalance: float, bullish: bool) -> float:
        """
        Adjust confidence based on whether imbalance confirms signal.

        Imbalance is a confidence MULTIPLIER, not an entry trigger.
        """
        weight = self.get_config('imbalance_weight', 0.3)

        if bullish:
            adjustment = imbalance * weight
        else:
            adjustment = -imbalance * weight

        adjusted = base_confidence + adjustment
        return max(0.1, min(1.0, adjusted))

    def _is_bouncing_off_support(self, current_price: float,
                                  support_level: float, symbol: str) -> bool:
        """Detect if price is bouncing off support."""
        previous = self.previous_price.get(symbol)
        self.previous_price[symbol] = current_price

        if previous is None:
            return False

        proximity = self.get_proximity_distance(current_price)
        was_near = abs(previous - support_level) <= proximity
        moving_up = current_price > previous
        min_move = proximity * 0.2
        move_size = current_price - previous

        return was_near and moving_up and move_size >= min_move

    def _is_rejecting_at_resistance(self, current_price: float,
                                     resistance_level: float, symbol: str) -> bool:
        """Detect if price is rejecting at resistance."""
        previous = self.previous_price.get(symbol)
        self.previous_price[symbol] = current_price

        if previous is None:
            return False

        proximity = self.get_proximity_distance(current_price)
        was_near = abs(previous - resistance_level) <= proximity
        moving_down = current_price < previous
        min_move = proximity * 0.2
        move_size = previous - current_price

        return was_near and moving_down and move_size >= min_move

    def get_analysis(self, ticker: Any, current_price: float,
                     symbol: str = 'UNKNOWN') -> Dict:
        """
        Get detailed order book analysis without generating a signal.

        Useful for debugging or displaying market state.
        """
        analysis = self._analyze_book_advanced(ticker, current_price, symbol)
        confirmed_support = self._get_confirmed_levels(symbol, 'support')
        confirmed_resistance = self._get_confirmed_levels(symbol, 'resistance')

        return {
            'support_zones': [
                {'price': z.price, 'size': z.size, 'strength': z.strength, 'zscore': z.zscore}
                for z in analysis['support']
            ],
            'resistance_zones': [
                {'price': z.price, 'size': z.size, 'strength': z.strength, 'zscore': z.zscore}
                for z in analysis['resistance']
            ],
            'confirmed_support': [
                {'price': l.price, 'volume': l.current_volume, 'state': l.state.value}
                for l in confirmed_support
            ],
            'confirmed_resistance': [
                {'price': l.price, 'volume': l.current_volume, 'state': l.state.value}
                for l in confirmed_resistance
            ],
            'bid_depth': analysis['bid_depth_total'],
            'ask_depth': analysis['ask_depth_total'],
            'imbalance': analysis['imbalance'],
            'current_price': current_price,
        }
