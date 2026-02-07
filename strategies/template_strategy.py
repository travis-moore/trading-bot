"""
Template Strategy

This is a template for creating new trading strategies.
Copy this file and modify it to create your own strategy.

To use your strategy:
1. Copy this file to strategies/my_strategy.py
2. Rename the class to MyStrategy
3. Implement the analyze() method with your trading logic
4. Add configuration to config.yaml under strategies.my_strategy
"""

import logging
from typing import Dict, Optional, Any

from .base_strategy import BaseStrategy, StrategySignal, TradeDirection

logger = logging.getLogger(__name__)


class TemplateStrategy(BaseStrategy):
    """
    Template strategy - copy and modify this for your own strategies.

    Your strategy should:
    1. Analyze market data (order book, price action, indicators)
    2. Generate signals with confidence levels
    3. Return None when there's no trading opportunity

    Your strategy should NOT:
    - Place orders directly (the engine does this)
    - Manage positions (the engine does this)
    - Implement risk management (the engine does this)
    """

    @property
    def name(self) -> str:
        """Unique identifier for this strategy."""
        return "template"

    @property
    def description(self) -> str:
        """Human-readable description."""
        return "Template strategy - copy and modify for your own strategies"

    @property
    def version(self) -> str:
        """Strategy version."""
        return "1.0.0"

    def get_default_config(self) -> Dict[str, Any]:
        """
        Define your strategy's configuration parameters.

        These can be overridden in config.yaml under strategies.<name>

        Example config.yaml:
            strategies:
              template:
                enabled: true
                my_threshold: 0.8
                lookback_period: 10
        """
        return {
            'enabled': False,  # Disabled by default (it's just a template)
            'my_threshold': 0.7,
            'lookback_period': 5,
            # Add your parameters here
        }

    def analyze(self, ticker: Any, current_price: float,
                context: Dict[str, Any] = None) -> Optional[StrategySignal]:
        """
        Analyze market data and generate a trade signal.

        This is called by the trading engine for each symbol on each scan.

        Args:
            ticker: ib_insync Ticker object containing:
                - ticker.domBids: List of bid levels (price, size)
                - ticker.domAsks: List of ask levels (price, size)
                - ticker.bid: Current best bid
                - ticker.ask: Current best ask
                - ticker.last: Last trade price

            current_price: Current stock price (usually same as ticker.last)

            context: Optional dict with additional info:
                - 'symbol': The stock symbol (e.g., 'AAPL')
                - 'positions': List of current Position objects
                - 'account_value': Current account value

        Returns:
            StrategySignal if you detect a trading opportunity
            None if no signal (market is neutral or unclear)

        Example implementation:

            # Get your config parameters
            threshold = self.get_config('my_threshold', 0.7)

            # Analyze the order book
            if not ticker.domBids or not ticker.domAsks:
                return None  # No data

            total_bid = sum(b.size for b in ticker.domBids if b.price > 0)
            total_ask = sum(a.size for a in ticker.domAsks if a.price > 0)

            if total_bid + total_ask == 0:
                return None

            # Calculate buy/sell imbalance
            imbalance = (total_bid - total_ask) / (total_bid + total_ask)

            # Generate signal if imbalance is strong enough
            if imbalance > threshold:
                return StrategySignal(
                    direction=TradeDirection.LONG_CALL,
                    confidence=abs(imbalance),
                    pattern_name="strong_buy_imbalance",
                    metadata={'imbalance': imbalance}
                )
            elif imbalance < -threshold:
                return StrategySignal(
                    direction=TradeDirection.LONG_PUT,
                    confidence=abs(imbalance),
                    pattern_name="strong_sell_imbalance",
                    metadata={'imbalance': imbalance}
                )

            return None  # No strong signal
        """
        # This template just returns None (no signal)
        # Replace this with your actual strategy logic

        # Example: Log that we're being called (for debugging)
        symbol = context.get('symbol', 'UNKNOWN') if context else 'UNKNOWN'
        logger.debug(f"TemplateStrategy analyzing {symbol} @ ${current_price:.2f}")

        # Return None = no trading signal
        return None

    def on_position_opened(self, position: Any):
        """
        Called when a position is opened based on your signal.

        Use this to track state or adjust future signals.

        Args:
            position: The Position object that was opened
        """
        logger.info(f"TemplateStrategy: Position opened - {position.contract.localSymbol}")

    def on_position_closed(self, position: Any, reason: str):
        """
        Called when a position is closed.

        Use this to learn from outcomes and improve your strategy.

        Args:
            position: The Position object that was closed
            reason: Why it was closed (profit_target, stop_loss, manual_close, etc.)
        """
        logger.info(
            f"TemplateStrategy: Position closed - {position.contract.localSymbol} "
            f"reason={reason}"
        )

    @classmethod
    def get_test_scenarios(cls) -> list:
        """
        Define test scenarios for this strategy.
        
        The test runner (test_strategies.py) uses this to generate data 
        and verify the strategy behaves as expected.
        
        Returns:
            List of dictionaries, where each dict describes a test scenario.
        """
        return [
            # Example 1: Single Ticker Test
            {
                "name": "Bullish Imbalance",
                "description": "Should buy when bids significantly outweigh asks",
                "type": "single",  # 'single' ticker or 'sequence' of tickers
                "setup": {
                    "method": "generate_imbalance",  # Method in MarketDataGenerator
                    "params": {"price": 100.0, "skew": 0.8}
                },
                "expected": {
                    # Template returns None by default, so we expect no signal
                    # "direction": TradeDirection.LONG_CALL, 
                }
            },
            # Example 2: Sequence Test (e.g. for bounces)
            # {
            #     "name": "Support Bounce",
            #     "type": "sequence",
            #     "setup": {
            #         "method": "simulate_bounce",
            #         "params": {"start_price": 101.0, "support_level": 100.0}
            #     },
            #     "expected": {
            #         "direction": TradeDirection.LONG_CALL
            #     }
            # }
        ]


# =============================================================================
# QUICK REFERENCE
# =============================================================================
#
# TradeDirection options:
#   - TradeDirection.LONG_CALL  -> Buy call options (bullish)
#   - TradeDirection.LONG_PUT   -> Buy put options (bearish)
#   - TradeDirection.NO_TRADE   -> Don't trade (or just return None)
#
# StrategySignal fields:
#   - direction: TradeDirection (required)
#   - confidence: float 0.0-1.0 (required) - higher = more confident
#   - pattern_name: str (optional) - human-readable pattern name
#   - price_level: float (optional) - key price level (support/resistance)
#   - metadata: dict (optional) - any extra data for logging/debugging
#
# Accessing config:
#   value = self.get_config('param_name', default_value)
#
# Common ticker attributes:
#   ticker.domBids  -> List[DOMLevel] - bid side of order book
#   ticker.domAsks  -> List[DOMLevel] - ask side of order book
#   ticker.bid      -> float - best bid price
#   ticker.ask      -> float - best ask price
#   ticker.last     -> float - last trade price
#   ticker.volume   -> int - volume
#
# DOMLevel attributes:
#   level.price -> float
#   level.size  -> int
#
# =============================================================================
