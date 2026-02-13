"""
Global Market Context Managers

Handles Market Regime Detection and Sector Rotation analysis.
"""

import logging
import statistics
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any

from ib_wrapper import IBWrapper

logger = logging.getLogger(__name__)

class MarketRegime(Enum):
    BULL_TREND = "bull_trend"
    BEAR_TREND = "bear_trend"
    RANGE_BOUND = "range_bound"
    HIGH_CHAOS = "high_chaos"
    UNKNOWN = "unknown"

class MarketRegimeDetector:
    """
    Detects the global market regime using SPY and VIX.
    Singleton-style usage via shared instance.
    """
    
    def __init__(self, ib: IBWrapper, config: Dict[str, Any] = None):
        self.ib = ib
        self.config = config or {}
        self.current_regime = MarketRegime.UNKNOWN
        self.last_update = None
        self.spy_data = {}
        self.vix_data = {}

    def assess_regime(self) -> MarketRegime:
        """
        Calculate market regime based on SPY and VIX.
        Should be called at market open and mid-day.
        """
        try:
            # Fetch Data
            spy_bars = self.ib.get_historical_bars('SPY', bar_size='1 day', duration='1 Y')
            if not spy_bars:
                # Fallback to RTH=False (Extended hours)
                spy_bars = self.ib.get_historical_bars('SPY', bar_size='1 day', duration='1 Y', use_rth=False)
            if not spy_bars:
                # Fallback to MIDPOINT if TRADES fails (common with shared market data/paper trading)
                spy_bars = self.ib.get_historical_bars('SPY', bar_size='1 day', duration='1 Y', what_to_show='MIDPOINT')
            if not spy_bars:
                # Fallback to ISLAND exchange (often works when SMART fails in dual-session)
                spy_bars = self.ib.get_historical_bars('SPY', bar_size='1 day', duration='1 Y', exchange='ISLAND')

            vix_bars = self.ib.get_historical_bars('VIX', bar_size='1 day', duration='30 D', exchange='CBOE', sec_type='IND')
            if not vix_bars:
                # Fallback to RTH=False
                vix_bars = self.ib.get_historical_bars('VIX', bar_size='1 day', duration='30 D', exchange='CBOE', sec_type='IND', use_rth=False)
            if not vix_bars:
                # Fallback for VIX as well
                vix_bars = self.ib.get_historical_bars('VIX', bar_size='1 day', duration='30 D', exchange='CBOE', sec_type='IND', what_to_show='MIDPOINT')
            
            if not spy_bars or not vix_bars:
                logger.warning("Insufficient data for regime detection")
                return self.current_regime

            current_spy = spy_bars[-1].close
            current_vix = vix_bars[-1].close
            
            # Calculate Metrics
            # 1. SPY 200 SMA
            closes = [b.close for b in spy_bars]
            sma_200 = statistics.mean(closes[-200:]) if len(closes) >= 200 else current_spy
            
            # 2. SPY Volatility (Daily realized vol over last 5 days)
            recent_spy = closes[-6:]
            returns = [(recent_spy[i] - recent_spy[i-1])/recent_spy[i-1] for i in range(1, len(recent_spy))]
            spy_vol = statistics.stdev(returns) if len(returns) > 1 else 0
            
            # 3. VIX Change (5 days)
            vix_5d_ago = vix_bars[-5].close if len(vix_bars) >= 5 else current_vix
            vix_change_pct = (current_vix - vix_5d_ago) / vix_5d_ago
            
            # 4. Range Bound Check (2% range over 10 days)
            spy_10d = closes[-10:]
            spy_range_pct = (max(spy_10d) - min(spy_10d)) / min(spy_10d)
            
            # Get thresholds from config
            chaos_vix = self.config.get('high_chaos_vix_threshold', 30)
            chaos_vix_change = self.config.get('high_chaos_vix_change_pct', 0.20)
            chaos_spy_vol = self.config.get('high_chaos_spy_vol_pct', 0.02)
            
            bull_vix = self.config.get('bull_trend_vix_threshold', 20)
            range_vix_min = self.config.get('range_bound_vix_min', 15)
            range_vix_max = self.config.get('range_bound_vix_max', 25)

            # Determine Regime (Priority Logic)
            
            # High Chaos: VIX spike > 20% OR SPY Vol > 2% OR VIX > 30 (Safety override)
            if vix_change_pct > chaos_vix_change or spy_vol > chaos_spy_vol or current_vix > chaos_vix:
                regime = MarketRegime.HIGH_CHAOS
                
            # Bear Trend: SPY < 200 MA OR VIX > 30
            elif current_spy < sma_200 or current_vix > chaos_vix:
                regime = MarketRegime.BEAR_TREND
                
            # Range Bound: SPY range < 2% AND VIX stable (15-25)
            elif spy_range_pct < 0.02 and range_vix_min <= current_vix <= range_vix_max:
                regime = MarketRegime.RANGE_BOUND
                
            # Bull Trend: SPY > 200 MA AND VIX < 20
            elif current_spy > sma_200 and current_vix < bull_vix:
                regime = MarketRegime.BULL_TREND
                
            else:
                # Fallback / Transition state
                regime = MarketRegime.RANGE_BOUND

            self.current_regime = regime
            self.last_update = datetime.now()
            logger.info(f"Market Regime Updated: {regime.value} (SPY=${current_spy:.2f}, VIX={current_vix:.2f})")
            return regime
            
        except Exception as e:
            logger.error(f"Error detecting market regime: {e}")
            return self.current_regime

class SectorRotationManager:
    """
    Analyzes Sector Rotation using Relative Strength vs SPY.
    """

    SECTORS = [
        'XLK', 'XLE', 'XLF', 'XLV', 'XLI', 'XLP',
        'XLY', 'XLB', 'XLU', 'XLRE', 'XLC'
    ]

    def __init__(self, ib: IBWrapper, config: Optional[Dict[str, Any]] = None):
        self.ib = ib
        self.config = config or {}
        self.sector_rs = {s: 0.0 for s in self.SECTORS} # Slope of RS ratio
        self.symbol_sector_map = {} # Symbol -> Sector ETF
        self.last_update = None

        # Apply symbol-sector overrides from config
        overrides = self.config.get('symbol_sector_overrides', {})
        self.symbol_sector_map.update(overrides)

    def map_symbol_to_sector(self, symbol: str, industry: str) -> str:
        """Map a stock symbol/industry to its sector ETF."""
        # Check config overrides first
        if symbol in self.symbol_sector_map:
            return self.symbol_sector_map[symbol]

        # Simple mapping based on IB industry strings
        mapping = {
            'Technology': 'XLK',
            'Energy': 'XLE',
            'Financial': 'XLF',
            'Healthcare': 'XLV',
            'Industrials': 'XLI',
            'Consumer Defensive': 'XLP',
            'Consumer Cyclical': 'XLY',
            'Basic Materials': 'XLB',
            'Utilities': 'XLU',
            'Real Estate': 'XLRE',
            'Communication': 'XLC'
        }
        # Try to match partial strings
        for key, etf in mapping.items():
            if key in industry:
                self.symbol_sector_map[symbol] = etf
                return etf
        return 'UNKNOWN'

    def assess_rotation(self):
        """
        Calculate Relative Strength slope for all sectors.
        """
        try:
            bar_size = self.config.get('bar_size', '1 hour')
            duration = self.config.get('duration', '5 D')
            rs_window = self.config.get('rs_window', 5)

            # Get SPY data
            spy_bars = self.ib.get_historical_bars('SPY', bar_size=bar_size, duration=duration)
            if not spy_bars:
                spy_bars = self.ib.get_historical_bars('SPY', bar_size=bar_size, duration=duration, use_rth=False)
            if not spy_bars:
                spy_bars = self.ib.get_historical_bars('SPY', bar_size=bar_size, duration=duration, what_to_show='MIDPOINT')

            if not spy_bars:
                return

            spy_closes = {b.date: b.close for b in spy_bars} # Map by date/time for alignment

            for sector in self.SECTORS:
                sec_bars = self.ib.get_historical_bars(sector, bar_size=bar_size, duration=duration)
                if not sec_bars:
                    sec_bars = self.ib.get_historical_bars(sector, bar_size=bar_size, duration=duration, use_rth=False)
                if not sec_bars:
                    sec_bars = self.ib.get_historical_bars(sector, bar_size=bar_size, duration=duration, what_to_show='MIDPOINT')

                if not sec_bars:
                    continue

                # Calculate RS Ratio for last N periods
                ratios = []
                for bar in sec_bars[-rs_window:]:
                    if bar.date in spy_closes:
                        spy_price = spy_closes[bar.date]
                        if spy_price > 0:
                            ratios.append(bar.close / spy_price)

                if len(ratios) < 2:
                    continue

                # Calculate Slope (Linear Regression approximation)
                slope = (ratios[-1] - ratios[0]) / len(ratios)
                self.sector_rs[sector] = slope

            self.last_update = datetime.now()
            logger.info("Sector Rotation Updated")

        except Exception as e:
            logger.error(f"Error assessing sector rotation: {e}")

    def get_sector_rs(self, symbol: str) -> float:
        """Get RS slope for a symbol's sector."""
        sector = self.symbol_sector_map.get(symbol)
        if sector and sector in self.sector_rs:
            return self.sector_rs[sector]
        return 0.0