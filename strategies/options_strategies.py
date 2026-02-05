"""
Advanced Options Strategies

Implements Spread and Iron Condor strategies based on Market Regime.
"""

import logging
from typing import Dict, Optional, Any
from .base_strategy import StrategySignal, TradeDirection
from .swing_trading import SwingTradingStrategy, Pattern
from market_context import MarketRegime

logger = logging.getLogger(__name__)

class BullPutSpreadStrategy(SwingTradingStrategy):
    """
    Bull Put Spread (Credit Spread).
    Entry: Price rejects Support (Power Level/Zone) AND Bull Trend.
    Logic: Sell 30-Delta Put, Buy 15-Delta Put.
    Exit: 50% Max Profit.
    """
    @property
    def name(self) -> str:
        return "bull_put_spread"

    def analyze(self, ticker: Any, current_price: float, context: Optional[Dict[str, Any]] = None) -> Optional[StrategySignal]:
        # 1. Check Market Regime
        regime = context.get('market_regime', MarketRegime.UNKNOWN)
        if regime != MarketRegime.BULL_TREND:
            return None

        # 2. Use Swing Strategy logic to detect Support Rejection
        signal = super().analyze(ticker, current_price, context)
        
        if signal and signal.direction == TradeDirection.LONG_CALL: # Rejection at Support maps to Long Call in Swing
            # Convert to Bull Put Spread Signal
            return StrategySignal(
                direction=TradeDirection.BULL_PUT_SPREAD,
                confidence=signal.confidence,
                pattern_name=signal.pattern_name,
                price_level=signal.price_level,
                metadata={
                    **signal.metadata,
                    'legs': {'short_delta': 30, 'long_delta': 15, 'type': 'put'},
                    'exit_rule': '50_pct_profit'
                }
            )
        return None

class BearPutSpreadStrategy(SwingTradingStrategy):
    """
    Bear Put Spread (Debit Spread).
    Entry: Support Imbalance Breakthrough (Breakout Down) AND Bear Trend.
    Logic: Buy 50-Delta Put, Sell 30-Delta Put.
    """
    @property
    def name(self) -> str:
        return "bear_put_spread"

    def analyze(self, ticker: Any, current_price: float, context: Optional[Dict[str, Any]] = None) -> Optional[StrategySignal]:
        # 1. Check Market Regime
        regime = context.get('market_regime', MarketRegime.UNKNOWN)
        if regime != MarketRegime.BEAR_TREND:
            return None

        # 2. Detect Breakout Down (Absorption/Breakout)
        signal = super().analyze(ticker, current_price, context)
        
        # Swing strategy maps Breakout Down to LONG_PUT
        if signal and signal.direction == TradeDirection.LONG_PUT:
            if "breakout" in signal.pattern_name or "absorption" in signal.pattern_name:
                return StrategySignal(
                    direction=TradeDirection.BEAR_PUT_SPREAD,
                    confidence=signal.confidence,
                    pattern_name=signal.pattern_name,
                    price_level=signal.price_level,
                    metadata={
                        **signal.metadata,
                        'legs': {'long_delta': 50, 'short_delta': 30, 'type': 'put'}
                    }
                )
        return None

class LongPutStrategy(SwingTradingStrategy):
    """
    Long Put.
    Entry: High-confidence Support Breakthrough AND (Bear Trend OR High Chaos).
    Logic: Buy 50-Delta Put (ATM).
    """
    @property
    def name(self) -> str:
        return "long_put"

    def analyze(self, ticker: Any, current_price: float, context: Optional[Dict[str, Any]] = None) -> Optional[StrategySignal]:
        # 1. Check Market Regime
        regime = context.get('market_regime', MarketRegime.UNKNOWN)
        if regime not in [MarketRegime.BEAR_TREND, MarketRegime.HIGH_CHAOS]:
            return None

        # 2. Detect Breakout Down
        signal = super().analyze(ticker, current_price, context)
        
        if signal and signal.direction == TradeDirection.LONG_PUT:
            if "breakout" in signal.pattern_name or "absorption" in signal.pattern_name:
                # Require high confidence
                if signal.confidence > 0.75:
                    return StrategySignal(
                        direction=TradeDirection.LONG_PUT_STRAIGHT,
                        confidence=signal.confidence,
                        pattern_name=signal.pattern_name,
                        price_level=signal.price_level,
                        metadata={
                            **signal.metadata,
                            'legs': {'long_delta': 50, 'type': 'put'}
                        }
                    )
        return None

class IronCondorStrategy(SwingTradingStrategy):
    """
    Iron Condor.
    Entry: Market Regime is Range Bound.
    Logic: Sell 15-Delta Put/Call, Buy 5-Delta wings.
    Exit: 50% profit or 21 DTE.
    """
    @property
    def name(self) -> str:
        return "iron_condor"

    def analyze(self, ticker: Any, current_price: float, context: Optional[Dict[str, Any]] = None) -> Optional[StrategySignal]:
        # 1. Check Market Regime
        regime = context.get('market_regime', MarketRegime.UNKNOWN)
        if regime != MarketRegime.RANGE_BOUND:
            return None

        # 2. Check for Consolidation (Lack of directional signal)
        # We can use the absence of strong directional signals from Swing strategy
        # or check if price is between support and resistance
        
        # Get analysis from parent
        analysis = self.get_analysis(ticker, current_price, context.get('symbol'))
        
        # Check if price is roughly in middle of nearest zones
        # This is a simplification; real IC logic might check IV Rank etc.
        # For this template, we rely primarily on Regime + Consolidation
        
        # If Swing Strategy finds NO pattern, it returns None.
        # But we want to trade when there is NO breakout/rejection (Range Bound).
        
        # Let's check if we are NOT near any major level
        nearest_support = analysis['confirmed_support'][0]['price'] if analysis['confirmed_support'] else 0
        nearest_resistance = analysis['confirmed_resistance'][0]['price'] if analysis['confirmed_resistance'] else float('inf')
        
        if nearest_support > 0 and nearest_resistance < float('inf'):
            midpoint = (nearest_support + nearest_resistance) / 2
            range_width = nearest_resistance - nearest_support
            
            # If price is in the middle 50% of the range
            dist_to_mid = abs(current_price - midpoint)
            if dist_to_mid < (range_width * 0.25):
                return StrategySignal(
                    direction=TradeDirection.IRON_CONDOR,
                    confidence=0.8, # High confidence if regime is Range Bound
                    pattern_name="range_consolidation",
                    metadata={
                        'legs': {
                            'short_put_delta': 15,
                            'long_put_delta': 5,
                            'short_call_delta': 15,
                            'long_call_delta': 5
                        },
                        'exit_rule': '50_pct_profit_or_21_dte'
                    }
                )
        
        return None