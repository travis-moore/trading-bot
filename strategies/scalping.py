"""
Scalping Strategy

Short-term trading based on order book imbalance with time-horizon decay exits.

This strategy:
- Enters trades based on strong order book imbalance
- Uses tight proximity settings (0.05% default)
- Implements time-decay exit: exit if price doesn't move favorably within N ticks
- Targets quick profits from momentum

Separated from Swing Trading which focuses on support/resistance levels.
"""

import logging
from typing import Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta

from .base_strategy import BaseStrategy, StrategySignal, TradeDirection

logger = logging.getLogger(__name__)


@dataclass
class ScalpPosition:
    """Track a scalping position for time-decay exit logic."""
    symbol: str
    direction: TradeDirection
    entry_price: float
    entry_time: datetime
    entry_tick: int
    initial_imbalance: float


class ScalpingStrategy(BaseStrategy):
    """
    Scalping strategy based on order book imbalance.

    Trading Logic:
    - Strong positive imbalance (bids >> asks) → LONG_CALL
    - Strong negative imbalance (asks >> bids) → LONG_PUT
    - Time-decay exit: if price doesn't move favorably within N ticks, signal exit

    This is a high-frequency strategy that should be used with tight stops.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

        # Track positions for time-decay logic
        self._positions: Dict[str, ScalpPosition] = {}  # symbol -> position
        self._tick_counts: Dict[str, int] = {}  # symbol -> tick count
        self._entry_prices: Dict[str, float] = {}  # symbol -> entry price for decay check

    @property
    def name(self) -> str:
        return "scalping"

    @property
    def description(self) -> str:
        return (
            "Scalping strategy based on order book imbalance. "
            "Enters on strong imbalance, exits on time-decay if price doesn't move."
        )

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_default_config(self) -> Dict[str, Any]:
        """Return default configuration for scalping strategy."""
        return {
            # Imbalance thresholds
            'imbalance_entry_threshold': 0.7,      # Strong imbalance to enter
            'imbalance_exit_threshold': 0.3,       # Weak imbalance to exit

            # Time-decay settings
            'max_ticks_without_progress': 5,       # Exit after N ticks if no progress
            'min_progress_pct': 0.001,             # 0.1% minimum move in favor

            # Proportional settings (tighter for scalping)
            'zone_proximity_pct': 0.0005,          # 0.05% proximity

            # Confidence settings
            'min_confidence': 0.70,
        }

    def analyze(self, ticker: Any, current_price: float,
                context: Optional[Dict[str, Any]] = None) -> Optional[StrategySignal]:
        """
        Analyze order book imbalance for scalping opportunities.

        Args:
            ticker: ib_insync Ticker with domBids/domAsks
            current_price: Current stock price
            context: Optional context with 'symbol' key

        Returns:
            StrategySignal if opportunity detected, None otherwise
        """
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')

        # Increment tick counter for this symbol
        self._tick_counts[symbol] = self._tick_counts.get(symbol, 0) + 1
        tick = self._tick_counts[symbol]

        # Calculate order book imbalance
        imbalance = self._calculate_imbalance(ticker)

        if imbalance is None:
            return None

        # Check for time-decay exit signal on existing position
        exit_signal = self._check_time_decay_exit(symbol, current_price, tick, imbalance)
        if exit_signal:
            return exit_signal

        # Check for entry signal based on imbalance
        entry_threshold = self.get_config('imbalance_entry_threshold', 0.7)
        min_confidence = self.get_config('min_confidence', 0.70)

        # Strong buy imbalance
        if imbalance >= entry_threshold:
            confidence = min(1.0, imbalance)  # Use imbalance as confidence

            if confidence >= min_confidence:
                # Track this as a potential position
                self._start_tracking(symbol, TradeDirection.LONG_CALL,
                                     current_price, tick, imbalance)

                logger.info(
                    f"scalping ({symbol}): LONG signal - "
                    f"imbalance: {imbalance:+.2f}, confidence: {confidence:.2f}"
                )

                return StrategySignal(
                    direction=TradeDirection.LONG_CALL,
                    confidence=confidence,
                    pattern_name="imbalance_long",
                    metadata={
                        'imbalance': imbalance,
                        'tick': tick,
                        'strategy_type': 'scalping'
                    }
                )

        # Strong sell imbalance
        elif imbalance <= -entry_threshold:
            confidence = min(1.0, abs(imbalance))

            if confidence >= min_confidence:
                self._start_tracking(symbol, TradeDirection.LONG_PUT,
                                     current_price, tick, imbalance)

                logger.info(
                    f"scalping ({symbol}): SHORT signal - "
                    f"imbalance: {imbalance:+.2f}, confidence: {confidence:.2f}"
                )

                return StrategySignal(
                    direction=TradeDirection.LONG_PUT,
                    confidence=confidence,
                    pattern_name="imbalance_short",
                    metadata={
                        'imbalance': imbalance,
                        'tick': tick,
                        'strategy_type': 'scalping'
                    }
                )

        return None

    def _calculate_imbalance(self, ticker: Any) -> Optional[float]:
        """Calculate order book imbalance from ticker data."""
        if not ticker.domBids or not ticker.domAsks:
            return None

        total_bid = sum(b.size for b in ticker.domBids if b.price > 0)
        total_ask = sum(a.size for a in ticker.domAsks if a.price > 0)

        total = total_bid + total_ask
        if total == 0:
            return None

        return (total_bid - total_ask) / total

    def _start_tracking(self, symbol: str, direction: TradeDirection,
                        price: float, tick: int, imbalance: float):
        """Start tracking a position for time-decay logic."""
        self._positions[symbol] = ScalpPosition(
            symbol=symbol,
            direction=direction,
            entry_price=price,
            entry_time=datetime.now(),
            entry_tick=tick,
            initial_imbalance=imbalance
        )
        self._entry_prices[symbol] = price

    def _check_time_decay_exit(self, symbol: str, current_price: float,
                                tick: int, imbalance: float) -> Optional[StrategySignal]:
        """
        Check if position should be exited due to time-decay.

        Time-decay exit triggers when:
        1. N ticks have passed since entry
        2. Price hasn't moved favorably by min_progress_pct
        OR
        3. Imbalance has flipped against the position
        """
        if symbol not in self._positions:
            return None

        position = self._positions[symbol]
        max_ticks = self.get_config('max_ticks_without_progress', 5)
        min_progress = self.get_config('min_progress_pct', 0.001)
        exit_threshold = self.get_config('imbalance_exit_threshold', 0.3)

        ticks_elapsed = tick - position.entry_tick

        # Calculate price progress
        if position.direction == TradeDirection.LONG_CALL:
            progress = (current_price - position.entry_price) / position.entry_price
            favorable = progress > 0
            imbalance_flipped = imbalance < -exit_threshold
        else:
            progress = (position.entry_price - current_price) / position.entry_price
            favorable = progress > 0
            imbalance_flipped = imbalance > exit_threshold

        # Check exit conditions
        should_exit = False
        exit_reason = ""

        if imbalance_flipped:
            should_exit = True
            exit_reason = "imbalance_flip"
        elif ticks_elapsed >= max_ticks and progress < min_progress:
            should_exit = True
            exit_reason = "time_decay"

        if should_exit:
            # Clear tracking
            del self._positions[symbol]
            if symbol in self._entry_prices:
                del self._entry_prices[symbol]

            logger.info(
                f"scalping ({symbol}): EXIT signal - "
                f"reason: {exit_reason}, ticks: {ticks_elapsed}, progress: {progress:+.2%}"
            )

            # Return opposite direction to signal exit
            exit_direction = (TradeDirection.LONG_PUT
                              if position.direction == TradeDirection.LONG_CALL
                              else TradeDirection.LONG_CALL)

            return StrategySignal(
                direction=TradeDirection.NO_TRADE,  # Signal to exit, not enter
                confidence=0.9,
                pattern_name=f"scalp_exit_{exit_reason}",
                metadata={
                    'exit_reason': exit_reason,
                    'ticks_elapsed': ticks_elapsed,
                    'progress_pct': progress,
                    'original_direction': position.direction.value,
                    'strategy_type': 'scalping'
                }
            )

        return None

    def on_position_opened(self, position: Any):
        """Track position when opened."""
        symbol = position.contract.symbol
        if symbol in self._positions:
            logger.debug(f"Scalping: tracking position {symbol}")

    def on_position_closed(self, position: Any, reason: str):
        """Clean up tracking when position closed."""
        symbol = position.contract.symbol
        if symbol in self._positions:
            del self._positions[symbol]
        if symbol in self._entry_prices:
            del self._entry_prices[symbol]
        if symbol in self._tick_counts:
            del self._tick_counts[symbol]

        logger.debug(f"Scalping: position {symbol} closed - {reason}")
