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
    Logic: Sell short_put_delta Put, Buy long_put_delta Put.
    Exit: 50% Max Profit.
    """
    @property
    def name(self) -> str:
        return "bull_put_spread"

    def get_default_config(self) -> Dict[str, Any]:
        config = super().get_default_config()
        config.update({
            'short_put_delta': 30,      # Delta of the put to sell
            'long_put_delta': 15,       # Delta of the put to buy (protection)
            'exit_at_pct_profit': 0.50, # Close at 50% of max credit received
        })
        return config

    def analyze(self, ticker: Any, current_price: float, context: Optional[Dict[str, Any]] = None) -> Optional[StrategySignal]:
        # 1. Check Market Regime
        context = context or {}
        regime = context.get('market_regime', MarketRegime.UNKNOWN)
        if regime != MarketRegime.BULL_TREND:
            instance_name = self.get_config('instance_name', self.name, symbol=context.get('symbol'))
            logger.info(f"{instance_name} ({context.get('symbol')}): Skipping - Regime {regime.value} != {MarketRegime.BULL_TREND.value}")
            return None

        # 2. Use Swing Strategy logic to detect Support Rejection
        signal = super().analyze(ticker, current_price, context)

        if signal and signal.direction == TradeDirection.LONG_CALL: # Rejection at Support maps to Long Call in Swing
            symbol = context.get('symbol')
            short_delta = self.get_config('short_put_delta', 30, symbol=symbol)
            long_delta = self.get_config('long_put_delta', 15, symbol=symbol)
            exit_pct = self.get_config('exit_at_pct_profit', 0.50, symbol=symbol)

            # Convert to Bull Put Spread Signal
            return StrategySignal(
                direction=TradeDirection.BULL_PUT_SPREAD,
                confidence=signal.confidence,
                pattern_name=signal.pattern_name,
                price_level=signal.price_level,
                metadata={
                    **signal.metadata,
                    'legs': {'short_delta': short_delta, 'long_delta': long_delta, 'type': 'put'},
                    'exit_rule': f'{int(exit_pct * 100)}_pct_profit'
                }
            )
        return None

    @classmethod
    def get_test_scenarios(cls) -> list:
        return [
            {
                "name": "Bull Put Spread (Support Bounce + Bull Trend)",
                "type": "sequence",
                "setup": {
                    "method": "simulate_bounce",
                    "params": {"start_price": 100.20, "support_level": 100.0}
                },
                "context": {"market_regime": MarketRegime.BULL_TREND},
                "expected": {"direction": TradeDirection.BULL_PUT_SPREAD}
            }
        ]

class BearPutSpreadStrategy(SwingTradingStrategy):
    """
    Bear Put Spread (Debit Spread).
    Entry: Support Imbalance Breakthrough (Breakout Down) AND Bear Trend.
    Logic: Buy long_put_delta Put, Sell short_put_delta Put.
    """
    @property
    def name(self) -> str:
        return "bear_put_spread"

    def get_default_config(self) -> Dict[str, Any]:
        config = super().get_default_config()
        config.update({
            'long_put_delta': 50,       # Delta of the put to buy (near ATM)
            'short_put_delta': 30,      # Delta of the put to sell (further OTM)
        })
        return config

    def analyze(self, ticker: Any, current_price: float, context: Optional[Dict[str, Any]] = None) -> Optional[StrategySignal]:
        # 1. Check Market Regime
        context = context or {}
        regime = context.get('market_regime', MarketRegime.UNKNOWN)
        if regime != MarketRegime.BEAR_TREND:
            instance_name = self.get_config('instance_name', self.name, symbol=context.get('symbol'))
            logger.info(f"{instance_name} ({context.get('symbol')}): Skipping - Regime {regime.value} != {MarketRegime.BEAR_TREND.value}")
            return None

        # 2. Detect Breakout Down (Absorption/Breakout)
        signal = super().analyze(ticker, current_price, context)

        # Swing strategy maps Breakout Down to LONG_PUT
        if signal and signal.direction == TradeDirection.LONG_PUT:
            if "breakout" in signal.pattern_name or "absorption" in signal.pattern_name:
                symbol = context.get('symbol')
                long_delta = self.get_config('long_put_delta', 50, symbol=symbol)
                short_delta = self.get_config('short_put_delta', 30, symbol=symbol)

                return StrategySignal(
                    direction=TradeDirection.BEAR_PUT_SPREAD,
                    confidence=signal.confidence,
                    pattern_name=signal.pattern_name,
                    price_level=signal.price_level,
                    metadata={
                        **signal.metadata,
                        'legs': {'long_delta': long_delta, 'short_delta': short_delta, 'type': 'put'}
                    }
                )
        return None

    @classmethod
    def get_test_scenarios(cls) -> list:
        return []

class LongPutStrategy(SwingTradingStrategy):
    """
    Long Put.
    Entry: High-confidence Support Breakthrough AND (Bear Trend OR High Chaos).
    Logic: Buy put_delta Put (ATM).
    """
    RECOMMENDED_MIN_CONFIDENCE = 0.75
    _confidence_warning_logged_today = None  # Track daily warning

    @property
    def name(self) -> str:
        return "long_put"

    def get_default_config(self) -> Dict[str, Any]:
        config = super().get_default_config()
        config.update({
            'put_delta': 50,                        # Delta of the put to buy
            'absorption_confidence': 0.75,          # Min confidence for entry
        })
        return config

    def analyze(self, ticker: Any, current_price: float, context: Optional[Dict[str, Any]] = None) -> Optional[StrategySignal]:
        # 1. Check Market Regime
        context = context or {}
        regime = context.get('market_regime', MarketRegime.UNKNOWN)
        if regime not in [MarketRegime.BEAR_TREND, MarketRegime.HIGH_CHAOS]:
            instance_name = self.get_config('instance_name', self.name, symbol=context.get('symbol'))
            logger.info(f"{instance_name} ({context.get('symbol')}): Skipping - Regime {regime.value} not in [bear_trend, high_chaos]")
            return None

        # Warn if confidence is below recommended minimum (once per day)
        from datetime import date
        today = date.today()
        min_conf = self.get_config('absorption_confidence', 0.75)
        if min_conf < self.RECOMMENDED_MIN_CONFIDENCE and self._confidence_warning_logged_today != today:
            logger.warning(
                f"LongPutStrategy: absorption_confidence ({min_conf}) is below "
                f"recommended minimum ({self.RECOMMENDED_MIN_CONFIDENCE}). "
                f"Low confidence entries increase risk of false breakout signals."
            )
            LongPutStrategy._confidence_warning_logged_today = today

        # 2. Detect Breakout Down
        signal = super().analyze(ticker, current_price, context)

        if signal and signal.direction == TradeDirection.LONG_PUT:
            if "breakout" in signal.pattern_name or "absorption" in signal.pattern_name:
                if signal.confidence >= min_conf:
                    symbol = context.get('symbol')
                    put_delta = self.get_config('put_delta', 50, symbol=symbol)

                    return StrategySignal(
                        direction=TradeDirection.LONG_PUT_STRAIGHT,
                        confidence=signal.confidence,
                        pattern_name=signal.pattern_name,
                        price_level=signal.price_level,
                        metadata={
                            **signal.metadata,
                            'legs': {'long_delta': put_delta, 'type': 'put'}
                        }
                    )
        return None

    @classmethod
    def get_test_scenarios(cls) -> list:
        return []

class IronCondorStrategy(SwingTradingStrategy):
    """
    Iron Condor.
    Entry: Market Regime is Range Bound.
    Logic: Sell short deltas, Buy wing deltas.
    Exit: Configurable % profit or DTE threshold.
    """
    @property
    def name(self) -> str:
        return "iron_condor"

    def get_default_config(self) -> Dict[str, Any]:
        config = super().get_default_config()
        config.update({
            'short_put_delta': 15,      # Delta of the put to sell
            'long_put_delta': 5,        # Delta of the put to buy (wing)
            'short_call_delta': 15,     # Delta of the call to sell
            'long_call_delta': 5,       # Delta of the call to buy (wing)
            'exit_at_pct_profit': 0.50, # Close at 50% of max credit received
            'exit_at_dte': 21,          # Close when 21 DTE remaining
            'min_confidence': 0.80,     # Higher confidence for IC
        })
        return config

    def analyze(self, ticker: Any, current_price: float, context: Optional[Dict[str, Any]] = None) -> Optional[StrategySignal]:
        # 1. Check Market Regime
        context = context or {}
        regime = context.get('market_regime', MarketRegime.UNKNOWN)
        if regime != MarketRegime.RANGE_BOUND:
            instance_name = self.get_config('instance_name', self.name, symbol=context.get('symbol'))
            logger.info(f"{instance_name} ({context.get('symbol')}): Skipping - Regime {regime.value} != {MarketRegime.RANGE_BOUND.value}")
            return None

        # 2. Get analysis from parent
        analysis = self.get_analysis(ticker, current_price, context.get('symbol'))

        # Check if price is roughly in middle of nearest zones
        nearest_support = analysis['confirmed_support'][0]['price'] if analysis['confirmed_support'] else 0
        nearest_resistance = analysis['confirmed_resistance'][0]['price'] if analysis['confirmed_resistance'] else float('inf')

        if nearest_support > 0 and nearest_resistance < float('inf'):
            midpoint = (nearest_support + nearest_resistance) / 2
            range_width = nearest_resistance - nearest_support

            # If price is in the middle 50% of the range
            dist_to_mid = abs(current_price - midpoint)
            if dist_to_mid < (range_width * 0.25):
                symbol = context.get('symbol')
                sp_delta = self.get_config('short_put_delta', 15, symbol=symbol)
                lp_delta = self.get_config('long_put_delta', 5, symbol=symbol)
                sc_delta = self.get_config('short_call_delta', 15, symbol=symbol)
                lc_delta = self.get_config('long_call_delta', 5, symbol=symbol)
                exit_pct = self.get_config('exit_at_pct_profit', 0.50, symbol=symbol)
                exit_dte = self.get_config('exit_at_dte', 21, symbol=symbol)

                return StrategySignal(
                    direction=TradeDirection.IRON_CONDOR,
                    confidence=0.8,
                    pattern_name="range_consolidation",
                    metadata={
                        'legs': {
                            'short_put_delta': sp_delta,
                            'long_put_delta': lp_delta,
                            'short_call_delta': sc_delta,
                            'long_call_delta': lc_delta
                        },
                        'exit_rule': f'{int(exit_pct * 100)}_pct_profit_or_{exit_dte}_dte'
                    }
                )

        return None

    @classmethod
    def get_test_scenarios(cls) -> list:
        return [
            {
                "name": "Iron Condor (Range Bound + Consolidation)",
                "type": "single",
                "setup": {
                    "method": "generate_ticker",
                    "params": {"price": 100.0}
                },
                "context": {"market_regime": MarketRegime.RANGE_BOUND},
                "expected": {"direction": TradeDirection.IRON_CONDOR}
            }
        ]
