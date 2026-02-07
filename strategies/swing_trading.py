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


# ============================================================================
# Historical Bounce Detection Data Structures
# ============================================================================

@dataclass
class SwingPoint:
    """A local extremum (swing high or low) identified in historical price data."""
    price: float
    timestamp: datetime
    swing_type: str  # 'high' or 'low'
    bar_index: int = 0  # Index in the bar array for reference


@dataclass
class HistoricalBounceLevel:
    """
    A price level that has been tested multiple times historically.

    These levels are identified from swing highs/lows that cluster within
    a small percentage range, indicating areas where price has repeatedly
    reversed (bounced).
    """
    price: float                      # Average price of the clustered swing points
    level_type: str                   # 'support' or 'resistance'
    bounce_count: int                 # Number of times tested (minimum 2)
    first_test: datetime              # When first tested
    last_test: datetime               # Most recent test
    bounce_timestamps: List[datetime] # All bounce timestamps for decay calculation
    strength: float                   # 0.0 to 1.0 based on bounce count (raw)
    decayed_strength: float = 0.0     # Strength after applying time decay


@dataclass
class PowerLevel:
    """
    A 'Power Level' where historical bounce and real-time depth converge.

    Power Levels are high-confidence trading zones where:
    1. Historical price data shows repeated bounces
    2. Current order book depth confirms significant liquidity
    """
    price: float                      # Averaged price of historical + depth
    level_type: str                   # 'support' or 'resistance'
    historical_level: HistoricalBounceLevel
    depth_level: TrackedLevel         # The real-time depth level
    combined_confidence: float        # Enhanced confidence score
    depth_strength: str               # 'strong', 'average', or 'weak'
    is_valid: bool                    # False if depth is weakened (skip trade)


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

        # Historical bounce detection
        self._historical_levels: Dict[str, List[HistoricalBounceLevel]] = {}  # symbol -> bounce levels
        self._power_levels: Dict[str, List[PowerLevel]] = {}  # symbol -> power levels
        self._historical_last_update: Dict[str, datetime] = {}  # symbol -> last fetch time

        # External dependencies (set via setter methods)
        self._ib_wrapper: Optional[Any] = None  # IBWrapper for historical data
        self._trade_db: Optional[Any] = None    # TradeDatabase for caching

        # Trading rules: pattern -> (direction, min_confidence)
        self._rules = {
            Pattern.REJECTION_AT_SUPPORT: (
                TradeDirection.LONG_CALL,
                self.get_config('rejection_support_confidence', 0.65) # Default, overridden in analyze
            ),
            Pattern.REJECTION_AT_RESISTANCE: (
                TradeDirection.LONG_PUT,
                self.get_config('rejection_resistance_confidence', 0.65) # Default, overridden in analyze
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
            # 'zone_proximity_pct': 0.005,      # OLD: 0.5% proximity
            'zone_proximity_pct': 0.002,        # 0.2% proximity to trigger detection
            'exclusion_zone_pct': 0.001,        # 0.1% dead zone around price

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

            # === Historical Bounce Detection ===
            'historical_bounce_enabled': True,  # Enable/disable historical analysis
            'historical_lookback_days': 30,     # Days of historical data to fetch
            # Bar sizes: '1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
            #            '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
            #            '20 mins', '30 mins', '1 hour', '2 hours', '3 hours',
            #            '4 hours', '8 hours', '1 day', '1 week', '1 month'
            'historical_bar_size': '15 mins',   # Candlestick timeframe
            'swing_window': 5,                  # Bars on each side for swing detection

            # Bounce Level Detection
            'bounce_proximity_pct': 0.001,      # 0.1% tolerance for clustering swings
            'min_bounces': 2,                   # Minimum tests to form a level
            'max_historical_levels': 10,        # Max bounce levels to track per symbol

            # Decay Settings
            'decay_type': 'linear',             # 'linear' or 'exponential'
            'linear_decay_days': 30,            # For linear: days to full decay
            'exponential_half_life_days': 15.0, # For exponential: half-life in days

            # Power Level Settings
            'power_level_proximity_pct': 0.005, # 0.5% - historical + depth alignment
            'power_level_confidence_boost': 0.15, # Confidence boost for power levels

            # Depth Validation at Power Levels
            'weak_depth_threshold': 0.5,        # Below this ratio = weak (skip trade)
            'strong_depth_threshold': 1.5,      # Above this ratio = strong (extra conf)

            # Cache Settings
            'historical_cache_ttl_hours': 24,   # Refresh cache after N hours

            # === Performance Feedback ===
            # Adjusts confidence based on recent win rate and P&L
            'performance_feedback_enabled': True,
            'performance_lookback_days': 14,    # Window for measuring performance
            'min_trades_for_feedback': 5,       # Need N trades before adjusting
            'win_rate_boost_threshold': 0.60,   # Win rate above this → boost confidence
            'win_rate_penalty_threshold': 0.40, # Win rate below this → reduce confidence
            'max_confidence_boost': 0.15,       # Max +15% confidence for good performance
            'max_confidence_penalty': 0.20,     # Max -20% confidence for poor performance
            'pnl_weight': 0.3,                  # Weight of P&L vs win rate (0.3 = 30%)
            'pnl_baseline': 50.0,               # $50 avg profit = "good" baseline
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
        now = ticker.time if ticker.time else datetime.now()

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
        instance_name = self.get_config('instance_name', self.name, symbol=symbol)
        for level_price in spoofed_levels:
            logger.info(f"{instance_name} ({symbol}): Spoofing detected at ${level_price:.2f}")

        # Get confirmed levels only
        confirmed_support = self._get_confirmed_levels(symbol, 'support')
        confirmed_resistance = self._get_confirmed_levels(symbol, 'resistance')

        # Update historical bounce levels (cached, refreshes when stale)
        if self.get_config('historical_bounce_enabled', True):
            self._update_historical_levels(symbol, current_price, symbol)

        # Detect power levels (historical + depth convergence)
        all_depth_levels = confirmed_support + confirmed_resistance
        power_levels = self._detect_power_levels(symbol, all_depth_levels, current_price)

        # Log current state
        if confirmed_support:
            support_str = f"${confirmed_support[0].price:.2f}"
        else:
            pending_sup = len([l for l in self._tracked_levels[symbol].values() if l.zone_type == 'support' and l.state == LevelState.PENDING])
            support_str = f"none ({pending_sup} pending)"

        if confirmed_resistance:
            resistance_str = f"${confirmed_resistance[0].price:.2f}"
        else:
            pending_res = len([l for l in self._tracked_levels[symbol].values() if l.zone_type == 'resistance' and l.state == LevelState.PENDING])
            resistance_str = f"none ({pending_res} pending)"
            
        power_str = f", power_levels={len(power_levels)}" if power_levels else ""

        # Check for Power Level patterns first (they have higher priority)
        pattern_result = self._detect_pattern_at_power_levels(
            current_price, symbol, analysis, power_levels
        )

        # Fall back to regular pattern detection if no power level match
        if pattern_result is None:
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
        instance_name = self.get_config('instance_name', self.name, symbol=symbol)
        logger.info(
            f"{instance_name} ({symbol}): price=${current_price:.2f}, "
            f"support={support_str}, resistance={resistance_str}, "
            f"pattern={pattern_name}, confidence={confidence_val:.2f}{power_str}"
        )

        if pattern_result is None:
            return None

        pattern, confidence, price_level, imbalance, metadata = pattern_result

        # Check if pattern maps to a trade
        if pattern not in self._rules:
            return None

        # Get rule direction and confidence (with symbol override support)
        direction, _ = self._rules[pattern]
        
        # Re-fetch min_confidence with symbol context
        rule_key_map = {
            Pattern.REJECTION_AT_SUPPORT: 'rejection_support_confidence',
            Pattern.REJECTION_AT_RESISTANCE: 'rejection_resistance_confidence',
            Pattern.ABSORPTION_BREAKOUT_UP: 'absorption_confidence',
            Pattern.ABSORPTION_BREAKOUT_DOWN: 'absorption_confidence',
        }
        min_confidence = self.get_config(rule_key_map.get(pattern, 'min_confidence'), 0.65, symbol=symbol)

        raw_confidence = confidence
        confidence = self.apply_performance_feedback(confidence, instance_name)

        # Track original confidence in metadata if modified
        if abs(confidence - raw_confidence) > 0.001:
            metadata['raw_confidence'] = raw_confidence
            metadata['performance_adjusted'] = True

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
        exclusion_pct = self.get_config('exclusion_zone_pct', 0.005, symbol=symbol)

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
                                current_price: float, exclusion_pct: float, symbol: str = None) -> List[LiquidityZone]:
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
        zscore_levels = self.get_config('zscore_levels_count', 10, symbol=symbol)
        zscore_threshold = self.get_config('zscore_threshold', 3.0, symbol=symbol)
        liquidity_threshold = self.get_config('liquidity_threshold', 1000, symbol=symbol)
        max_size = max(volumes) if volumes else 1

        for i, price in enumerate(prices):
            size = liquidity[price]

            # Skip if below base threshold
            if size < liquidity_threshold:
                continue

            # Skip if in exclusion zone
            if self.is_in_exclusion_zone(current_price, price, exclusion_pct, symbol=symbol):
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
        confirmation_time = timedelta(minutes=self.get_config('level_confirmation_minutes', 5, symbol=symbol))

        # Track all significant zones from current analysis
        all_zones = analysis['support'] + analysis['resistance']
        current_prices = {z.price for z in all_zones}

        # Update existing tracked levels
        for price in list(tracked.keys()):
            level = tracked[price]

            # Check if level is in current analysis OR hidden by exclusion zone but in raw data
            is_present = False
            current_size = 0

            if price in current_prices:
                is_present = True
                zone = next(z for z in all_zones if z.price == price)
                current_size = zone.size
            else:
                # Check raw liquidity to see if it's hidden (e.g. inside exclusion zone)
                raw_liquidity = analysis['raw_bids'] if level.zone_type == 'support' else analysis['raw_asks']
                if price in raw_liquidity:
                    size = raw_liquidity[price]
                    # If size is still significant (e.g. > 50% of initial), assume it's still there
                    if size > level.initial_volume * 0.5:
                        is_present = True
                        current_size = size

            if is_present:
                # Level still exists - update it
                level.last_seen = now
                level.current_volume = current_size

                # Check for volume refresh (iceberg behavior)
                if current_size > level.current_volume * 0.8:
                    level.refresh_count += 1

                # Update volume history for absorption detection
                if price not in self._volume_history[symbol]:
                    self._volume_history[symbol][price] = []
                self._volume_history[symbol][price].append(current_size)
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
        spoof_distance = self.get_config('spoofing_distance_ticks', 3, symbol=symbol)

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
        proximity_pct = self.get_config('zone_proximity_pct', 0.005, symbol=symbol)
        absorption_threshold = self.get_config('absorption_threshold_pct', 0.20, symbol=symbol)
        rejection_flip = self.get_config('rejection_imbalance_flip', 0.60, symbol=symbol)

        # Check support zones
        for level in confirmed_support:
            if self.is_price_near_level(current_price, level.price, proximity_pct):
                # Check for absorption (breakout signal)
                if self._is_absorbing(symbol, level, absorption_threshold):
                    confidence = self._adjust_confidence_by_imbalance(
                        level.current_volume / level.initial_volume,
                        imbalance, bullish=True, symbol=symbol
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
                            base_confidence, imbalance, bullish=True, symbol=symbol
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
                        imbalance, bullish=False, symbol=symbol
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
                            base_confidence, imbalance, bullish=False, symbol=symbol
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

    def _detect_pattern_at_power_levels(
        self,
        current_price: float,
        symbol: str,
        analysis: Dict,
        power_levels: List[PowerLevel]
    ) -> Optional[tuple]:
        """
        Detect trading patterns at Power Levels with enhanced confidence.

        Power Levels get priority because they combine historical bounce
        data with real-time depth confirmation.

        Returns:
            Tuple of (pattern, confidence, price_level, imbalance, metadata)
            or None if no valid power level pattern
        """
        if not power_levels:
            return None

        imbalance = analysis['imbalance']
        proximity_pct = self.get_config('zone_proximity_pct', 0.005, symbol=symbol)
        confidence_boost = self.get_config('power_level_confidence_boost', 0.15, symbol=symbol)
        rejection_flip = self.get_config('rejection_imbalance_flip', 0.60, symbol=symbol)

        for pl in power_levels:
            # Skip invalid (weakened) power levels
            if not pl.is_valid:
                instance_name = self.get_config('instance_name', self.name, symbol=symbol)
                logger.debug(
                    f"{instance_name} ({symbol}): Skipping weakened power level at ${pl.price:.2f}"
                )
                continue

            # Check if price is near this power level
            if not self.is_price_near_level(current_price, pl.price, proximity_pct):
                continue

            # Power Level is in play - check for patterns
            if pl.level_type == 'support':
                if self._is_bouncing_off_support(current_price, pl.price, symbol):
                    # Validate imbalance
                    if imbalance > -rejection_flip:  # Not heavily bearish
                        confidence = min(1.0, pl.combined_confidence + confidence_boost)

                        instance_name = self.get_config('instance_name', self.name, symbol=symbol)
                        logger.info(
                            f"{instance_name} ({symbol}): POWER LEVEL bounce at ${pl.price:.2f} "
                            f"(historical bounces: {pl.historical_level.bounce_count}, "
                            f"depth: {pl.depth_strength}, confidence: {confidence:.2f})"
                        )

                        return (
                            Pattern.REJECTION_AT_SUPPORT,
                            confidence,
                            pl.price,
                            imbalance,
                            {
                                'zone_size': pl.depth_level.current_volume,
                                'power_level': True,
                                'historical_bounces': pl.historical_level.bounce_count,
                                'depth_strength': pl.depth_strength,
                                'decayed_strength': pl.historical_level.decayed_strength,
                            }
                        )

            elif pl.level_type == 'resistance':
                if self._is_rejecting_at_resistance(current_price, pl.price, symbol):
                    # Validate imbalance
                    if imbalance < rejection_flip:  # Not heavily bullish
                        confidence = min(1.0, pl.combined_confidence + confidence_boost)

                        instance_name = self.get_config('instance_name', self.name, symbol=symbol)
                        logger.info(
                            f"{instance_name} ({symbol}): POWER LEVEL rejection at ${pl.price:.2f} "
                            f"(historical bounces: {pl.historical_level.bounce_count}, "
                            f"depth: {pl.depth_strength}, confidence: {confidence:.2f})"
                        )

                        return (
                            Pattern.REJECTION_AT_RESISTANCE,
                            confidence,
                            pl.price,
                            imbalance,
                            {
                                'zone_size': pl.depth_level.current_volume,
                                'power_level': True,
                                'historical_bounces': pl.historical_level.bounce_count,
                                'depth_strength': pl.depth_strength,
                                'decayed_strength': pl.historical_level.decayed_strength,
                            }
                        )

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
                                         imbalance: float, bullish: bool, symbol: str = None) -> float:
        """
        Adjust confidence based on whether imbalance confirms signal.

        Imbalance is a confidence MULTIPLIER, not an entry trigger.
        """
        weight = self.get_config('imbalance_weight', 0.3, symbol=symbol)

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

        proximity = self.get_proximity_distance(current_price, symbol=symbol)
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

        proximity = self.get_proximity_distance(current_price, symbol=symbol)
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

    # =========================================================================
    # Historical Bounce Detection Methods
    # =========================================================================

    def set_ib_wrapper(self, wrapper: Any):
        """Set IB wrapper for historical data fetching."""
        self._ib_wrapper = wrapper

    def set_trade_db(self, db: Any):
        """Set trade database for caching."""
        self._trade_db = db

    def _update_historical_levels(self, symbol: str, current_price: float, config_symbol: str = None):
        """
        Update historical bounce levels for a symbol if needed.

        Checks cache TTL and fetches fresh data when stale.
        """
        if not self.get_config('historical_bounce_enabled', True):
            return

        cache_ttl = self.get_config('historical_cache_ttl_hours', 24)
        now = datetime.now()

        # Check if we need to refresh
        last_update = self._historical_last_update.get(symbol)
        if last_update:
            age_hours = (now - last_update).total_seconds() / 3600
            if age_hours < cache_ttl:
                return  # Cache is still fresh

        # Try to load from database cache first
        bars = None
        bar_size = self.get_config('historical_bar_size', '15 mins')

        if self._trade_db:
            cached = self._trade_db.get_cached_bars(symbol, bar_size, cache_ttl)
            if cached:
                bars = cached
                logger.debug(f"{self.get_config('instance_name', self.name, symbol=config_symbol)}: Using cached bars for {symbol}")

        # Fetch from IB if no cache
        if bars is None and self._ib_wrapper:
            lookback_days = self.get_config('historical_lookback_days', 30)
            duration = f"{lookback_days} D"

            ib_bars = self._ib_wrapper.get_historical_bars(
                symbol, bar_size=bar_size, duration=duration
            )

            if ib_bars:
                # Convert to dict format and cache
                bars = [
                    {
                        'timestamp': bar.date if isinstance(bar.date, datetime) else datetime.fromisoformat(str(bar.date)),
                        'open': bar.open,
                        'high': bar.high,
                        'low': bar.low,
                        'close': bar.close,
                        'volume': bar.volume,
                    }
                    for bar in ib_bars
                ]

                if self._trade_db:
                    self._trade_db.cache_historical_bars(symbol, bar_size, ib_bars)

        if not bars:
            logger.debug(f"{self.get_config('instance_name', self.name, symbol=config_symbol)}: No historical bars for {symbol}")
            return

        # Identify swing points and bounce levels
        swing_points = self._identify_swing_points(bars, symbol=config_symbol)
        bounce_levels = self._identify_bounce_levels(swing_points, current_price, symbol=config_symbol)

        # Apply decay to all levels
        for level in bounce_levels:
            level.decayed_strength = self._apply_decay(level, now, symbol=config_symbol)

        # Sort by decayed strength and limit
        bounce_levels.sort(key=lambda l: l.decayed_strength, reverse=True)
        max_levels = self.get_config('max_historical_levels', 10)
        self._historical_levels[symbol] = bounce_levels[:max_levels]
        self._historical_last_update[symbol] = now

        instance_name = self.get_config('instance_name', self.name, symbol=config_symbol)
        if bounce_levels:
            logger.info(
                f"{instance_name} ({symbol}): Identified {len(bounce_levels)} historical bounce levels "
                f"from {len(swing_points)} swing points"
            )

    def _identify_swing_points(self, bars: List[Dict], symbol: str = None) -> List[SwingPoint]:
        """
        Identify swing highs and lows using a local extremum window.

        A swing high is a bar whose high is greater than the highs of
        the N bars before and after it.

        A swing low is a bar whose low is less than the lows of
        the N bars before and after it.
        """
        swing_points = []
        window = self.get_config('swing_window', 5, symbol=symbol)
        half_window = window // 2

        if len(bars) < window:
            return []

        for i in range(half_window, len(bars) - half_window):
            current_bar = bars[i]

            # Check for swing high
            is_swing_high = True
            for j in range(i - half_window, i + half_window + 1):
                if j != i and bars[j]['high'] >= current_bar['high']:
                    is_swing_high = False
                    break

            if is_swing_high:
                swing_points.append(SwingPoint(
                    price=current_bar['high'],
                    timestamp=current_bar['timestamp'],
                    swing_type='high',
                    bar_index=i
                ))
                continue  # A bar can't be both swing high and low

            # Check for swing low
            is_swing_low = True
            for j in range(i - half_window, i + half_window + 1):
                if j != i and bars[j]['low'] <= current_bar['low']:
                    is_swing_low = False
                    break

            if is_swing_low:
                swing_points.append(SwingPoint(
                    price=current_bar['low'],
                    timestamp=current_bar['timestamp'],
                    swing_type='low',
                    bar_index=i
                ))

        return swing_points

    def _identify_bounce_levels(self, swing_points: List[SwingPoint],
                                 current_price: float, symbol: str = None) -> List[HistoricalBounceLevel]:
        """
        Cluster swing points into bounce levels.

        A bounce level is formed when 2+ swing points occur within
        proximity_pct of each other.
        """
        proximity_pct = self.get_config('bounce_proximity_pct', 0.001, symbol=symbol)
        min_bounces = self.get_config('min_bounces', 2, symbol=symbol)

        # Separate swing highs and lows
        swing_highs = [sp for sp in swing_points if sp.swing_type == 'high']
        swing_lows = [sp for sp in swing_points if sp.swing_type == 'low']

        levels = []

        # Cluster swing lows into support levels
        levels.extend(self._cluster_swing_points(
            swing_lows, 'support', proximity_pct, min_bounces, current_price
        ))

        # Cluster swing highs into resistance levels
        levels.extend(self._cluster_swing_points(
            swing_highs, 'resistance', proximity_pct, min_bounces, current_price
        ))

        return levels

    def _cluster_swing_points(self, points: List[SwingPoint], level_type: str,
                               proximity_pct: float, min_bounces: int,
                               current_price: float) -> List[HistoricalBounceLevel]:
        """
        Cluster swing points by price proximity.

        Uses greedy clustering: sort by price, group adjacent points
        within proximity_pct of the cluster average.
        """
        if len(points) < min_bounces:
            return []

        # Sort by price
        sorted_points = sorted(points, key=lambda p: p.price)

        clusters: List[List[SwingPoint]] = []
        current_cluster = [sorted_points[0]]

        for point in sorted_points[1:]:
            cluster_avg = sum(p.price for p in current_cluster) / len(current_cluster)

            # Check if within proximity (using current price as reference)
            if abs(point.price - cluster_avg) / current_price <= proximity_pct:
                current_cluster.append(point)
            else:
                # Start new cluster
                if len(current_cluster) >= min_bounces:
                    clusters.append(current_cluster)
                current_cluster = [point]

        # Don't forget the last cluster
        if len(current_cluster) >= min_bounces:
            clusters.append(current_cluster)

        # Convert clusters to HistoricalBounceLevel objects
        levels = []
        for cluster in clusters:
            avg_price = sum(p.price for p in cluster) / len(cluster)
            timestamps = sorted([p.timestamp for p in cluster])

            # Strength based on bounce count (5+ bounces = max strength of 1.0)
            strength = min(1.0, len(cluster) / 5.0)

            levels.append(HistoricalBounceLevel(
                price=avg_price,
                level_type=level_type,
                bounce_count=len(cluster),
                first_test=timestamps[0],
                last_test=timestamps[-1],
                bounce_timestamps=timestamps,
                strength=strength,
                decayed_strength=0.0,  # Calculated separately
            ))

        return levels

    def _apply_decay(self, level: HistoricalBounceLevel,
                     current_time: Optional[datetime] = None, symbol: str = None) -> float:
        """
        Apply time decay to a historical level.

        Supports linear or exponential decay based on config.
        """
        current_time = current_time or datetime.now()
        decay_type = self.get_config('decay_type', 'linear', symbol=symbol)

        if decay_type == 'exponential':
            return self._apply_exponential_decay(level, current_time, symbol=symbol)
        else:
            return self._apply_linear_decay(level, current_time, symbol=symbol)

    def _apply_linear_decay(self, level: HistoricalBounceLevel,
                            current_time: datetime, symbol: str = None) -> float:
        """
        Apply linear time decay to a historical level.

        Formula: decayed_strength = base_strength * (1 - age_days / decay_days)
        """
        decay_days = self.get_config('linear_decay_days', 30, symbol=symbol)

        # Use most recent test for decay calculation
        last_test = level.last_test

        # Normalize timezones for subtraction
        if last_test.tzinfo is not None and current_time.tzinfo is None:
            current_time = current_time.astimezone()
        elif last_test.tzinfo is None and current_time.tzinfo is not None:
            last_test = last_test.astimezone()

        age = current_time - last_test
        age_days = age.total_seconds() / 86400

        decay_factor = max(0.0, 1.0 - (age_days / decay_days))
        return level.strength * decay_factor

    def _apply_exponential_decay(self, level: HistoricalBounceLevel,
                                  current_time: datetime, symbol: str = None) -> float:
        """
        Apply exponential time decay to a historical level.

        Formula: decayed_strength = base_strength * 2^(-age_days / half_life_days)
        """
        import math

        half_life_days = self.get_config('exponential_half_life_days', 15.0, symbol=symbol)

        last_test = level.last_test

        # Normalize timezones for subtraction
        if last_test.tzinfo is not None and current_time.tzinfo is None:
            current_time = current_time.astimezone()
        elif last_test.tzinfo is None and current_time.tzinfo is not None:
            last_test = last_test.astimezone()

        age = current_time - last_test
        age_days = age.total_seconds() / 86400

        decay_factor = math.pow(2, -age_days / half_life_days)
        return level.strength * decay_factor

    def _detect_power_levels(self, symbol: str,
                              depth_levels: List[TrackedLevel],
                              current_price: float) -> List[PowerLevel]:
        """
        Cross-reference historical bounce levels with real-time depth levels.

        A Power Level occurs when a historical bounce level aligns with
        a confirmed depth level within proximity_pct.
        """
        historical_levels = self._historical_levels.get(symbol, [])
        if not historical_levels:
            return []

        power_levels = []
        proximity_pct = self.get_config('power_level_proximity_pct', 0.005, symbol=symbol)

        for hist_level in historical_levels:
            for depth_level in depth_levels:
                # Skip if types don't match
                if hist_level.level_type != depth_level.zone_type:
                    continue

                # Check proximity using percentage of current price
                proximity = abs(hist_level.price - depth_level.price) / current_price

                if proximity <= proximity_pct:
                    # Calculate depth strength relative to average
                    avg_depth = self._get_average_depth_volume(symbol)
                    depth_strength = self._categorize_depth_strength(symbol,
                        depth_level.current_volume, avg_depth
                    )

                    # Determine if valid (not weakened)
                    is_valid = depth_strength != 'weak'

                    # Calculate combined confidence
                    combined_confidence = self._calculate_power_level_confidence(
                        hist_level, depth_level, depth_strength
                    )

                    power_levels.append(PowerLevel(
                        price=(hist_level.price + depth_level.price) / 2,
                        level_type=hist_level.level_type,
                        historical_level=hist_level,
                        depth_level=depth_level,
                        combined_confidence=combined_confidence,
                        depth_strength=depth_strength,
                        is_valid=is_valid,
                    ))

        # Store for later use
        self._power_levels[symbol] = power_levels
        return power_levels

    def _get_average_depth_volume(self, symbol: str) -> float:
        """Calculate average depth volume for normalization."""
        tracked = self._tracked_levels.get(symbol, {})
        if not tracked:
            return 10000  # Default fallback

        volumes = [level.current_volume for level in tracked.values()]
        return sum(volumes) / len(volumes) if volumes else 10000

    def _categorize_depth_strength(self, symbol: str, volume: int, average_volume: float) -> str:
        """
        Categorize depth volume relative to average.

        Returns 'weak', 'average', or 'strong'.
        """
        weak_threshold = self.get_config('weak_depth_threshold', 0.5, symbol=symbol)
        strong_threshold = self.get_config('strong_depth_threshold', 1.5, symbol=symbol)

        ratio = volume / average_volume if average_volume > 0 else 0

        if ratio < weak_threshold:
            return 'weak'
        elif ratio > strong_threshold:
            return 'strong'
        else:
            return 'average'

    def _calculate_power_level_confidence(self, hist_level: HistoricalBounceLevel,
                                           depth_level: TrackedLevel,
                                           depth_strength: str) -> float:
        """
        Calculate combined confidence for a Power Level.

        Formula:
        - Start with historical decayed_strength (0.0 - 1.0)
        - Add depth confidence bonus:
            - 'strong' depth: +0.2
            - 'average' depth: +0.1
            - 'weak' depth: -0.2 (penalty)
        """
        base_confidence = hist_level.decayed_strength

        # Depth strength adjustments
        if depth_strength == 'strong':
            base_confidence += 0.20
        elif depth_strength == 'average':
            base_confidence += 0.10
        else:  # weak
            base_confidence -= 0.20

        # Volume-based bonus (normalized, capped at 0.1)
        volume_bonus = min(0.1, depth_level.current_volume / 50000)
        base_confidence += volume_bonus

        return max(0.0, min(1.0, base_confidence))

    def get_power_levels(self, symbol: str) -> List[PowerLevel]:
        """Get current power levels for a symbol (for external access/debugging)."""
        return self._power_levels.get(symbol, [])

    def get_historical_levels(self, symbol: str) -> List[HistoricalBounceLevel]:
        """Get current historical bounce levels for a symbol (for external access/debugging)."""
        return self._historical_levels.get(symbol, [])

    @classmethod
    def get_test_scenarios(cls) -> list:
        """Define test scenarios for the test runner."""
        return [
            {
                "name": "Support Bounce (Bullish)",
                "description": "Price drops to support, hits buy wall, bounces up",
                "type": "sequence",
                "setup": {
                    "method": "simulate_bounce",
                    "params": {"start_price": 100.20, "support_level": 100.0}
                },
                "expected": {
                    "direction": TradeDirection.LONG_CALL
                }
            },
            {
                "name": "Support Absorption (Bullish)",
                "description": "Iceberg bid at support absorbs selling pressure",
                "type": "sequence",
                "setup": {
                    "method": "simulate_absorption_support",
                    "params": {"start_price": 100.20, "support_level": 100.0}
                },
                "expected": {
                    "direction": TradeDirection.LONG_CALL
                }
            }
        ]
