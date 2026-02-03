"""
Liquidity Analyzer
Analyzes order book depth to identify trading patterns
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class Pattern(Enum):
    """Trading pattern types"""
    TESTING_SUPPORT = "testing_support"
    TESTING_RESISTANCE = "testing_resistance"
    POTENTIAL_BREAKOUT_UP = "potential_breakout_up"
    POTENTIAL_BREAKOUT_DOWN = "potential_breakout_down"
    CONSOLIDATION = "consolidation"
    REJECTION_AT_SUPPORT = "rejection_at_support"
    REJECTION_AT_RESISTANCE = "rejection_at_resistance"
    BREAKTHROUGH_RESISTANCE = "breakthrough_resistance"
    BREAKTHROUGH_SUPPORT = "breakthrough_support"


@dataclass
class LiquidityZone:
    """Represents a liquidity zone in the order book"""
    price: float
    size: int
    zone_type: str  # 'support' or 'resistance'
    strength: float  # Relative strength (0-1)


@dataclass
class PatternSignal:
    """Signal detected from order book analysis"""
    pattern: Pattern
    confidence: float  # 0-1
    price_level: Optional[float]
    imbalance: Optional[float]
    metadata: Dict


class LiquidityAnalyzer:
    """
    Analyzes order book liquidity to detect trading patterns
    """
    
    def __init__(self, config: Dict):
        """
        Initialize analyzer with configuration
        
        Args:
            config: Dictionary with analysis parameters
                - liquidity_threshold: Minimum size to consider a zone
                - zone_proximity: How close price must be to zone (dollars)
                - imbalance_threshold: Threshold for order imbalance
                - num_levels: Number of order book levels to analyze
        """
        self.liquidity_threshold = config.get('liquidity_threshold', 1000)
        self.zone_proximity = config.get('zone_proximity', 0.10)
        self.imbalance_threshold = config.get('imbalance_threshold', 0.6)
        self.num_levels = config.get('num_levels', 10)
        
        # Track previous state for pattern detection
        self.previous_price = None
        self.previous_zones = {'support': [], 'resistance': []}
        
    def analyze_book(self, ticker) -> Dict:
        """
        Analyze order book to identify liquidity zones
        
        Args:
            ticker: IB ticker object with domBids and domAsks
            
        Returns:
            Dictionary with analysis results
        """
        if not ticker.domBids or not ticker.domAsks:
            logger.warning("No depth data available")
            return {
                'support': [],
                'resistance': [],
                'bid_depth_total': 0,
                'ask_depth_total': 0,
                'imbalance': 0
            }
        
        # Extract liquidity by price level
        bid_liquidity = {bid.price: bid.size for bid in ticker.domBids}
        ask_liquidity = {ask.price: ask.size for ask in ticker.domAsks}
        
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
            'bid_liquidity': bid_liquidity,
            'ask_liquidity': ask_liquidity
        }
    
    def _identify_zones(self, liquidity: Dict[float, int], 
                       zone_type: str) -> List[LiquidityZone]:
        """
        Identify significant liquidity zones
        
        Args:
            liquidity: Dictionary of price -> size
            zone_type: 'support' or 'resistance'
            
        Returns:
            List of LiquidityZone objects
        """
        if not liquidity:
            return []
        
        zones = []
        max_size = max(liquidity.values()) if liquidity else 1
        
        for price, size in liquidity.items():
            if size >= self.liquidity_threshold:
                strength = size / max_size
                zones.append(LiquidityZone(
                    price=price,
                    size=size,
                    zone_type=zone_type,
                    strength=strength
                ))
        
        # Sort zones by strength
        zones.sort(key=lambda z: z.strength, reverse=True)
        return zones
    
    def _calculate_imbalance(self, total_bid: int, total_ask: int) -> float:
        """
        Calculate order book imbalance
        
        Returns:
            Value between -1 (heavy sell pressure) and 1 (heavy buy pressure)
        """
        total = total_bid + total_ask
        if total == 0:
            return 0.0
        
        return (total_bid - total_ask) / total
    
    def detect_pattern(self, ticker, current_price: float) -> Optional[PatternSignal]:
        """
        Detect trading patterns from order book.

        Confidence is calculated from zone strength and adjusted by imbalance:
        - Bullish signals (support bounce) get boosted by positive imbalance
        - Bearish signals (resistance rejection) get boosted by negative imbalance
        - Conflicting imbalance reduces confidence

        Args:
            ticker: IB ticker with depth data
            current_price: Current stock price

        Returns:
            PatternSignal or None
        """
        analysis = self.analyze_book(ticker)
        imbalance = analysis['imbalance']

        # Check for testing zones
        for zone in analysis['support']:
            distance = abs(current_price - zone.price)
            if distance <= self.zone_proximity:
                # Price is testing support (bullish scenario)
                base_confidence = zone.strength
                if self._is_bouncing_off_support(current_price, zone.price):
                    # Rejection at support - positive imbalance confirms the bounce
                    adjusted_confidence = self._adjust_confidence_by_imbalance(
                        base_confidence, imbalance, bullish=True
                    )
                    return PatternSignal(
                        pattern=Pattern.REJECTION_AT_SUPPORT,
                        confidence=adjusted_confidence,
                        price_level=zone.price,
                        imbalance=imbalance,
                        metadata={'zone_size': zone.size, 'raw_strength': base_confidence}
                    )
                else:
                    # Just testing support
                    adjusted_confidence = self._adjust_confidence_by_imbalance(
                        base_confidence * 0.7, imbalance, bullish=True
                    )
                    return PatternSignal(
                        pattern=Pattern.TESTING_SUPPORT,
                        confidence=adjusted_confidence,
                        price_level=zone.price,
                        imbalance=imbalance,
                        metadata={'zone_size': zone.size, 'raw_strength': base_confidence}
                    )

        for zone in analysis['resistance']:
            distance = abs(current_price - zone.price)
            if distance <= self.zone_proximity:
                # Price is testing resistance (bearish scenario)
                base_confidence = zone.strength
                if self._is_rejecting_at_resistance(current_price, zone.price):
                    # Rejection at resistance - negative imbalance confirms the rejection
                    adjusted_confidence = self._adjust_confidence_by_imbalance(
                        base_confidence, imbalance, bullish=False
                    )
                    return PatternSignal(
                        pattern=Pattern.REJECTION_AT_RESISTANCE,
                        confidence=adjusted_confidence,
                        price_level=zone.price,
                        imbalance=imbalance,
                        metadata={'zone_size': zone.size, 'raw_strength': base_confidence}
                    )
                else:
                    # Just testing resistance
                    adjusted_confidence = self._adjust_confidence_by_imbalance(
                        base_confidence * 0.7, imbalance, bullish=False
                    )
                    return PatternSignal(
                        pattern=Pattern.TESTING_RESISTANCE,
                        confidence=adjusted_confidence,
                        price_level=zone.price,
                        imbalance=imbalance,
                        metadata={'zone_size': zone.size, 'raw_strength': base_confidence}
                    )

        # Check for breakout conditions based on order imbalance
        if imbalance > self.imbalance_threshold:
            return PatternSignal(
                pattern=Pattern.POTENTIAL_BREAKOUT_UP,
                confidence=abs(imbalance),
                price_level=None,
                imbalance=imbalance,
                metadata={'bid_depth': analysis['bid_depth_total']}
            )

        if imbalance < -self.imbalance_threshold:
            return PatternSignal(
                pattern=Pattern.POTENTIAL_BREAKOUT_DOWN,
                confidence=abs(imbalance),
                price_level=None,
                imbalance=imbalance,
                metadata={'ask_depth': analysis['ask_depth_total']}
            )

        # Default: consolidation
        return PatternSignal(
            pattern=Pattern.CONSOLIDATION,
            confidence=0.5,
            price_level=current_price,
            imbalance=imbalance,
            metadata={}
        )

    def _adjust_confidence_by_imbalance(self, base_confidence: float,
                                         imbalance: float, bullish: bool) -> float:
        """
        Adjust confidence based on whether imbalance confirms or contradicts the signal.

        Args:
            base_confidence: Starting confidence from zone strength
            imbalance: Order book imbalance (-1 to +1)
            bullish: True if signal is bullish (support bounce, breakout up)

        Returns:
            Adjusted confidence (clamped to 0.1 - 1.0)
        """
        # Imbalance adjustment factor (how much imbalance affects confidence)
        # At max imbalance (±1.0), this adds/subtracts up to 0.3 from confidence
        imbalance_weight = 0.3

        if bullish:
            # Positive imbalance confirms bullish signal, negative contradicts
            adjustment = imbalance * imbalance_weight
        else:
            # Negative imbalance confirms bearish signal, positive contradicts
            adjustment = -imbalance * imbalance_weight

        adjusted = base_confidence + adjustment
        return max(0.1, min(1.0, adjusted))
    
    def _is_bouncing_off_support(self, current_price: float,
                                  support_level: float) -> bool:
        """
        Detect if price is bouncing off support.

        A bounce is detected when:
        - Price was near support (within zone_proximity) in previous scan
        - Price is now moving UP away from support
        - The move up is meaningful (not just noise)
        """
        if self.previous_price is None:
            self.previous_price = current_price
            return False

        # Was previous price near support? (within zone_proximity)
        prev_distance = abs(self.previous_price - support_level)
        was_near_support = prev_distance <= self.zone_proximity

        # Is price now moving up (away from support)?
        moving_up = current_price > self.previous_price

        # Minimum move to consider it a bounce (not just noise)
        # Use 20% of zone_proximity as minimum move threshold
        min_move = self.zone_proximity * 0.2
        move_size = current_price - self.previous_price

        bouncing = was_near_support and moving_up and move_size >= min_move

        self.previous_price = current_price
        return bouncing
    
    def _is_rejecting_at_resistance(self, current_price: float,
                                     resistance_level: float) -> bool:
        """
        Detect if price is rejecting at resistance.

        A rejection is detected when:
        - Price was near resistance (within zone_proximity) in previous scan
        - Price is now moving DOWN away from resistance
        - The move down is meaningful (not just noise)
        """
        if self.previous_price is None:
            self.previous_price = current_price
            return False

        # Was previous price near resistance? (within zone_proximity)
        prev_distance = abs(self.previous_price - resistance_level)
        was_near_resistance = prev_distance <= self.zone_proximity

        # Is price now moving down (away from resistance)?
        moving_down = current_price < self.previous_price

        # Minimum move to consider it a rejection (not just noise)
        # Use 20% of zone_proximity as minimum move threshold
        min_move = self.zone_proximity * 0.2
        move_size = self.previous_price - current_price

        rejecting = was_near_resistance and moving_down and move_size >= min_move

        self.previous_price = current_price
        return rejecting
    
    def get_nearest_zones(self, current_price: float, 
                         analysis: Dict) -> Dict[str, Optional[LiquidityZone]]:
        """
        Get nearest support and resistance zones
        
        Args:
            current_price: Current stock price
            analysis: Analysis dictionary from analyze_book
            
        Returns:
            Dict with 'support' and 'resistance' nearest zones
        """
        nearest_support = None
        nearest_resistance = None
        
        # Find nearest support below current price
        support_below = [
            z for z in analysis['support'] 
            if z.price < current_price
        ]
        if support_below:
            nearest_support = max(support_below, key=lambda z: z.price)
        
        # Find nearest resistance above current price
        resistance_above = [
            z for z in analysis['resistance']
            if z.price > current_price
        ]
        if resistance_above:
            nearest_resistance = min(resistance_above, key=lambda z: z.price)
        
        return {
            'support': nearest_support,
            'resistance': nearest_resistance
        }
