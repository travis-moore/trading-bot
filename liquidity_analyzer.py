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
        Detect trading patterns from order book
        
        Args:
            ticker: IB ticker with depth data
            current_price: Current stock price
            
        Returns:
            PatternSignal or None
        """
        analysis = self.analyze_book(ticker)
        
        # Check for testing zones
        for zone in analysis['support']:
            distance = abs(current_price - zone.price)
            if distance <= self.zone_proximity:
                # Price is testing support
                if self._is_bouncing_off_support(current_price, zone.price):
                    return PatternSignal(
                        pattern=Pattern.REJECTION_AT_SUPPORT,
                        confidence=zone.strength,
                        price_level=zone.price,
                        imbalance=analysis['imbalance'],
                        metadata={'zone_size': zone.size}
                    )
                else:
                    return PatternSignal(
                        pattern=Pattern.TESTING_SUPPORT,
                        confidence=zone.strength * 0.7,
                        price_level=zone.price,
                        imbalance=analysis['imbalance'],
                        metadata={'zone_size': zone.size}
                    )
        
        for zone in analysis['resistance']:
            distance = abs(current_price - zone.price)
            if distance <= self.zone_proximity:
                # Price is testing resistance
                if self._is_rejecting_at_resistance(current_price, zone.price):
                    return PatternSignal(
                        pattern=Pattern.REJECTION_AT_RESISTANCE,
                        confidence=zone.strength,
                        price_level=zone.price,
                        imbalance=analysis['imbalance'],
                        metadata={'zone_size': zone.size}
                    )
                else:
                    return PatternSignal(
                        pattern=Pattern.TESTING_RESISTANCE,
                        confidence=zone.strength * 0.7,
                        price_level=zone.price,
                        imbalance=analysis['imbalance'],
                        metadata={'zone_size': zone.size}
                    )
        
        # Check for breakout conditions based on order imbalance
        if analysis['imbalance'] > self.imbalance_threshold:
            return PatternSignal(
                pattern=Pattern.POTENTIAL_BREAKOUT_UP,
                confidence=abs(analysis['imbalance']),
                price_level=None,
                imbalance=analysis['imbalance'],
                metadata={'bid_depth': analysis['bid_depth_total']}
            )
        
        if analysis['imbalance'] < -self.imbalance_threshold:
            return PatternSignal(
                pattern=Pattern.POTENTIAL_BREAKOUT_DOWN,
                confidence=abs(analysis['imbalance']),
                price_level=None,
                imbalance=analysis['imbalance'],
                metadata={'ask_depth': analysis['ask_depth_total']}
            )
        
        # Default: consolidation
        return PatternSignal(
            pattern=Pattern.CONSOLIDATION,
            confidence=0.5,
            price_level=current_price,
            imbalance=analysis['imbalance'],
            metadata={}
        )
    
    def _is_bouncing_off_support(self, current_price: float, 
                                  support_level: float) -> bool:
        """
        Detect if price is bouncing off support
        (requires previous price tracking)
        """
        if self.previous_price is None:
            self.previous_price = current_price
            return False
        
        # Price was below support and is now moving back up
        bouncing = (
            self.previous_price <= support_level and 
            current_price > support_level
        )
        
        self.previous_price = current_price
        return bouncing
    
    def _is_rejecting_at_resistance(self, current_price: float,
                                     resistance_level: float) -> bool:
        """
        Detect if price is rejecting at resistance
        (requires previous price tracking)
        """
        if self.previous_price is None:
            self.previous_price = current_price
            return False
        
        # Price was above resistance and is now moving back down
        rejecting = (
            self.previous_price >= resistance_level and
            current_price < resistance_level
        )
        
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
