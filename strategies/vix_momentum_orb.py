"""
VIX Momentum ORB Strategy

Implements a 15-minute Opening Range Breakout (ORB) strategy filtered by VIX momentum.
"""

import logging
from datetime import datetime, time, timedelta
from typing import Dict, Optional, Any, List, Tuple
from zoneinfo import ZoneInfo

from .base_strategy import BaseStrategy, StrategySignal, TradeDirection

logger = logging.getLogger(__name__)


class VIXMomentumORB(BaseStrategy):
    """
    VIX Momentum ORB Strategy.

    Logic:
    1. Establish Opening Range (default 9:30-9:45 AM ET).
    2. Wait for breakout of ORB High/Low between 9:45-10:15 AM ET.
    3. Confirm with VIX Momentum (VIX down for calls, VIX up for puts).
    4. One trade per day per symbol.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._ib_wrapper = None
        
        # State
        self._trade_executed_today: Dict[str, bool] = {}
        self._current_date = None
        self._orb_high: Dict[str, float] = {}
        self._orb_low: Dict[str, float] = {}
        self._orb_complete: Dict[str, bool] = {}
        self._orb_milestones_logged: Dict[str, set] = {}
        
        # VIX History: List[Tuple[datetime, float]]
        self._vix_history: List[Tuple[datetime, float]] = []
        self._last_log_time: Dict[str, datetime] = {}

    @property
    def name(self) -> str:
        return "vix_momentum_orb"

    @property
    def description(self) -> str:
        return "15-min Opening Range Breakout filtered by VIX momentum"

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_default_config(self) -> Dict[str, Any]:
        return {
            'enabled': False,
            'orb_minutes': 15,
            'target_profit': 300.0,
            'contract_cost_basis': 150.0,
            'vix_symbol': 'VIX',
            'spy_symbol': 'SPY', # For divergence check
            'spread_threshold_pct': 0.05, # 5% spread limit
            'vix_slope_minutes': 5,
            'check_vix_divergence': True,
            'allowed_regimes': ['bull_trend', 'bear_trend', 'high_chaos'], # Momentum works in trends/chaos
        }

    def set_ib_wrapper(self, wrapper: Any):
        """Set IB wrapper to access data for other symbols (VIX, SPY)."""
        self._ib_wrapper = wrapper

    def _log_throttled(self, symbol: str, message: str, level=logging.INFO, interval_seconds=60):
        """Log a message at most once every interval_seconds."""
        now = datetime.now()
        last = self._last_log_time.get(symbol)
        if not last or (now - last).total_seconds() > interval_seconds:
            logger.log(level, message)
            self._last_log_time[symbol] = now
            
    def _get_next_orb_end_info(self, now: datetime, orb_minutes: int) -> Tuple[timedelta, str]:
        """Calculate time until next ORB end and description of when it is."""
        today = now.date()
        market_open_today = datetime.combine(today, time(9, 30), tzinfo=now.tzinfo)
        orb_end_today = market_open_today + timedelta(minutes=orb_minutes)
        
        if now < orb_end_today:
            return orb_end_today - now, "today"
            
        # Find next business day
        next_day = today + timedelta(days=1)
        while next_day.weekday() >= 5:  # Saturday=5, Sunday=6
            next_day += timedelta(days=1)
            
        market_open_next = datetime.combine(next_day, time(9, 30), tzinfo=now.tzinfo)
        orb_end_next = market_open_next + timedelta(minutes=orb_minutes)
        
        day_name = next_day.strftime("%A")
        return orb_end_next - now, day_name

    def analyze(self, ticker: Any, current_price: float,
                context: Dict[str, Any] = None) -> Optional[StrategySignal]:
        
        # 1. Time & Date Management
        if context and 'current_time' in context:
            now = context['current_time']
        else:
            try:
                now = datetime.now(ZoneInfo("America/New_York"))
            except Exception:
                now = datetime.now().astimezone()
            
        today = now.date()
        
        if self._current_date != today:
            self._reset_daily_state(today)
            
        symbol = context.get('symbol') if context else 'UNKNOWN'
        
        # Initialize state for this symbol if needed
        if symbol not in self._orb_high:
            self._orb_high[symbol] = float('-inf')
            self._orb_low[symbol] = float('inf')
            self._orb_complete[symbol] = False
            self._trade_executed_today[symbol] = False
            
        orb_minutes = self.get_config('orb_minutes', 15)
            
        # 2. One-and-Done Filter
        if self._trade_executed_today[symbol]:
            # Show countdown if we are done for the day (traded or missed)
            remaining, day_str = self._get_next_orb_end_info(now, orb_minutes)
            hours, remainder = divmod(remaining.total_seconds(), 3600)
            minutes, _ = divmod(remainder, 60)
            self._log_throttled(symbol, f"[{self.name}] Waiting for next session. ORB ends in {int(hours)}h {int(minutes)}m ({day_str})", level=logging.INFO)
            return None

        # 3. Define Time Windows
        market_open = datetime.combine(today, time(9, 30), tzinfo=now.tzinfo)
        orb_end = market_open + timedelta(minutes=orb_minutes)
        trading_end = market_open + timedelta(minutes=45) # 10:15 AM

        # 4. ORB Calculation Phase
        if current_price is None or current_price <= 0:
            return None

        # Update ORB if in window
        if market_open <= now < orb_end:
            self._orb_high[symbol] = max(self._orb_high[symbol], current_price)
            self._orb_low[symbol] = min(self._orb_low[symbol], current_price)
            self._orb_complete[symbol] = False
            
            # Countdown Logging (15, 10, 5 min warnings)
            if symbol not in self._orb_milestones_logged:
                self._orb_milestones_logged[symbol] = set()
            
            minutes_remaining = (orb_end - now).total_seconds() / 60.0
            for m in [15, 10, 5]:
                if minutes_remaining <= m and m not in self._orb_milestones_logged[symbol]:
                    if minutes_remaining > m - 1.0: # Only log if we are actually close to the mark
                        logger.info(f"[{self.name}] {symbol}: {m} min to end of ORB. Range: {self._orb_low[symbol]:.2f} - {self._orb_high[symbol]:.2f}")
                    self._orb_milestones_logged[symbol].add(m)
            
            self._log_throttled(symbol, f"[{self.name}] Building ORB: {self._orb_low[symbol]:.2f} - {self._orb_high[symbol]:.2f}", level=logging.DEBUG)
            return None
        elif now >= orb_end:
            if not self._orb_complete[symbol]:
                # If ORB window is over but high/low are uninitialized, it means we missed the window.
                if self._orb_high[symbol] == float('-inf') or self._orb_low[symbol] == float('inf'):
                    # Missed window - disable for today and show countdown
                    self._trade_executed_today[symbol] = True
                    self._orb_complete[symbol] = True
                    
                    remaining, day_str = self._get_next_orb_end_info(now, orb_minutes)
                    hours, remainder = divmod(remaining.total_seconds(), 3600)
                    minutes, _ = divmod(remainder, 60)
                    self._log_throttled(symbol, f"[{self.name}] Waiting for next session. ORB ends in {int(hours)}h {int(minutes)}m ({day_str})", level=logging.INFO)
                    return None
                logger.info(f"[{self.name}] {symbol}: ORB Established: {self._orb_low[symbol]:.2f} - {self._orb_high[symbol]:.2f}")
            self._orb_complete[symbol] = True
        else:
            # Before market open
            remaining, day_str = self._get_next_orb_end_info(now, orb_minutes)
            hours, remainder = divmod(remaining.total_seconds(), 3600)
            minutes, _ = divmod(remainder, 60)
            self._log_throttled(symbol, f"[{self.name}] Waiting for market open. ORB ends in {int(hours)}h {int(minutes)}m ({day_str})", level=logging.INFO)
            return None

        # 5. Trading Window Check (9:45 - 10:15)
        if not (orb_end <= now <= trading_end):
            remaining, day_str = self._get_next_orb_end_info(now, orb_minutes)
            hours, remainder = divmod(remaining.total_seconds(), 3600)
            minutes, _ = divmod(remainder, 60)
            self._log_throttled(symbol, f"[{self.name}] Trading window closed. Next ORB ends in {int(hours)}h {int(minutes)}m ({day_str})", level=logging.INFO)
            return None

        # 6. Spread Check (Improvement B)
        # Check spread of the instrument we are TRADING (ticker)
        if hasattr(ticker, 'bid') and hasattr(ticker, 'ask') and ticker.bid and ticker.ask and ticker.bid > 0 and ticker.ask > 0:
            spread = ticker.ask - ticker.bid
            mid = (ticker.ask + ticker.bid) / 2
            spread_pct = spread / mid
            if spread_pct > self.get_config('spread_threshold_pct', 0.05):
                logger.debug(f"{symbol}: Spread too wide ({spread_pct:.1%}), skipping")
                self._log_throttled(symbol, f"[{self.name}] Spread too wide ({spread_pct:.1%})", level=logging.WARNING)
                return None

        # 7. VIX Analysis
        vix_symbol = self.get_config('vix_symbol', 'VIX')
        
        # Check for VIX price attached to ticker (for testing) or context
        vix_price = getattr(ticker, 'vix_price', None)
        if vix_price is None and context:
            vix_price = context.get('vix_price')
        if vix_price is None:
            vix_price = self._get_market_price(vix_symbol)
        
        if not vix_price:
            self._log_throttled(symbol, f"[{self.name}] VIX price unavailable for {vix_symbol}", level=logging.WARNING)
            return None
            
        # Update VIX history
        self._update_vix_history(now, vix_price)
        vix_slope = self._calculate_vix_slope()
        
        # Log status periodically
        self._log_throttled(symbol, f"[{self.name}] Monitoring: Price=${current_price:.2f} ORB=[{self._orb_low[symbol]:.2f}-{self._orb_high[symbol]:.2f}] VIX_Slope={vix_slope:.4f}", level=logging.INFO)
        
        # 8. Signal Logic
        signal = None
        
        # Bullish: QQQ > ORB High AND VIX trending down
        if current_price > self._orb_high[symbol]:
            if vix_slope < 0:
                # VIX Divergence Check (Improvement A) is implicit in vix_slope < 0
                
                raw_confidence = 0.8 + (abs(vix_slope) * 10)
                confidence = min(0.95, max(0.1, raw_confidence))
                
                signal = StrategySignal(
                    direction=TradeDirection.LONG_CALL,
                    confidence=confidence, # Boost confidence with steeper slope
                    pattern_name="orb_breakout_bullish",
                    metadata={
                        'orb_high': self._orb_high[symbol],
                        'breakout_price': current_price,
                        'vix_slope': vix_slope
                    }
                )

        # Bearish: QQQ < ORB Low AND VIX trending up
        elif current_price < self._orb_low[symbol]:
            if vix_slope > 0:
                raw_confidence = 0.8 + (vix_slope * 10)
                confidence = min(0.95, max(0.1, raw_confidence))
                
                signal = StrategySignal(
                    direction=TradeDirection.LONG_PUT,
                    confidence=confidence,
                    pattern_name="orb_breakout_bearish",
                    metadata={
                        'orb_low': self._orb_low[symbol],
                        'breakout_price': current_price,
                        'vix_slope': vix_slope
                    }
                )

        return signal

    def on_position_opened(self, position: Any):
        """Mark trade as executed for the day."""
        symbol = position.contract.symbol
        self._trade_executed_today[symbol] = True
        logger.info(f"VIXMomentumORB: Position opened for {position.contract.localSymbol}. Strategy done for today for {symbol}.")

    def _reset_daily_state(self, date):
        self._current_date = date
        self._trade_executed_today.clear()
        self._orb_high.clear()
        self._orb_low.clear()
        self._orb_complete.clear()
        self._vix_history.clear()
        self._orb_milestones_logged.clear()

    def _get_market_price(self, symbol: str) -> Optional[float]:
        """Helper to get price from IB wrapper."""
        if not self._ib_wrapper:
            return None
        
        # Try to find existing ticker
        if hasattr(self._ib_wrapper, 'ib'):
            for t in self._ib_wrapper.ib.tickers():
                if t.contract and t.contract.symbol == symbol:
                    # Prefer last price, then mid price, then close
                    if t.last and t.last > 0: return t.last
                    if t.bid > 0 and t.ask > 0: return (t.bid + t.ask) / 2
                    if t.close > 0: return t.close
                
        return None

    def _update_vix_history(self, now: datetime, price: float):
        """Add VIX price and prune old entries."""
        self._vix_history.append((now, price))
        
        # Keep only last N minutes
        cutoff = now - timedelta(minutes=self.get_config('vix_slope_minutes', 5))
        self._vix_history = [x for x in self._vix_history if x[0] >= cutoff]

    def _calculate_vix_slope(self) -> float:
        """Calculate simple slope of VIX over history."""
        if len(self._vix_history) < 2:
            return 0.0
            
        # Simple: (End - Start) / Minutes
        start_time, start_price = self._vix_history[0]
        end_time, end_price = self._vix_history[-1]
        
        duration_mins = (end_time - start_time).total_seconds() / 60.0
        if duration_mins < 1.0: # Need at least 1 min of data for reliable slope
            return 0.0
            
        return (end_price - start_price) / duration_mins

    @classmethod
    def get_test_scenarios(cls) -> list:
        return [
            {
                "name": "Clean Breakout Bullish",
                "description": "QQQ breaks ORB High, VIX dropping",
                "type": "sequence",
                "setup": {
                    "method": "simulate_orb_breakout",
                    "params": {
                        "orb_high": 100.0,
                        "orb_low": 99.0,
                        "breakout_price": 100.5,
                        "vix_trend": "down"
                    }
                },
                "expected": {
                    "direction": TradeDirection.LONG_CALL
                }
            }
        ]