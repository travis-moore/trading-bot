"""
Test Data Generator

Generates synthetic market data (Tickers, DOMs, Price History) for testing strategies
without requiring a live IB connection.
"""

import math
import random
from datetime import datetime, timedelta
from typing import List, Optional, Generator

from ib_insync import Ticker, DOMLevel, Contract

class MarketDataGenerator:
    """
    Generates fake stock data designed to test various strategies.
    
    Focuses on the *intent* of strategies (imbalance, support/resistance, momentum)
    rather than specific implementation details.
    """
    
    def __init__(self, symbol: str = "TEST"):
        self.symbol = symbol
        self.contract = Contract(symbol=symbol, secType='STK', exchange='SMART', currency='USD')
        self.current_time = datetime.now()
        
    def _create_dom_levels(self, start_price: float, direction: int, 
                          total_vol: int, levels: int = 5, 
                          decay: float = 0.5) -> List[DOMLevel]:
        """
        Helper to create a list of DOMLevels.
        
        Args:
            start_price: Price of the first level
            direction: 1 for Asks (price goes up), -1 for Bids (price goes down)
            total_vol: Total volume to distribute across levels
            levels: Number of levels
            decay: How much volume drops per level (0.0-1.0)
        """
        dom_levels = []
        remaining_vol = total_vol
        current_price = start_price
        
        for i in range(levels):
            # Calculate volume for this level
            if i == levels - 1:
                vol = remaining_vol
            else:
                vol = int(remaining_vol * (1.0 - decay))
                remaining_vol -= vol
            
            # Ensure at least some volume
            vol = max(1, vol)
            
            dom_levels.append(DOMLevel(price=round(current_price, 2), size=vol, marketMaker=''))
            current_price += (0.01 * direction)
            
        return dom_levels

    def _advance_time(self, seconds: float = 1.0):
        """Advance internal clock."""
        self.current_time += timedelta(seconds=seconds)

    def generate_ticker(self, price: float, bid_size: int = 100, ask_size: int = 100,
                       bid_price: float = None, ask_price: float = None) -> Ticker:
        """Generates a basic Ticker object."""
        bp = bid_price if bid_price is not None else price - 0.01
        ap = ask_price if ask_price is not None else price + 0.01
        self._advance_time()
        
        return Ticker(
            contract=self.contract,
            time=self.current_time,
            bid=bp,
            bidSize=bid_size,
            ask=ap,
            askSize=ask_size,
            last=price,
            lastSize=100,
            volume=10000,
            domBids=[],
            domAsks=[]
        )

    def generate_imbalance(self, price: float, skew: float = 0.8, 
                          total_liquidity: int = 10000) -> Ticker:
        """
        Generates a Ticker with a specific Order Book imbalance.
        
        Args:
            price: Current price
            skew: 0.0 to 1.0. 
                  0.5 = Balanced
                  >0.5 = Bullish (More Bids)
                  <0.5 = Bearish (More Asks)
            total_liquidity: Total size of bids + asks
        """
        bid_vol = int(total_liquidity * skew)
        ask_vol = total_liquidity - bid_vol
        
        # Spread is tight
        bid_price = price - 0.01
        ask_price = price + 0.01
        
        bids = self._create_dom_levels(bid_price, -1, bid_vol)
        asks = self._create_dom_levels(ask_price, 1, ask_vol)
        self._advance_time()
        
        return Ticker(
            contract=self.contract,
            time=self.current_time,
            bid=bid_price,
            bidSize=bids[0].size,
            ask=ask_price,
            askSize=asks[0].size,
            last=price,
            lastSize=10,
            volume=50000,
            domBids=bids,
            domAsks=asks
        )

    def generate_support_resistance(self, price: float, wall_price: float, 
                                   wall_size: int = 5000, is_support: bool = True) -> Ticker:
        """
        Generates a Ticker with a massive "wall" at a specific price.
        
        Args:
            price: Current trading price
            wall_price: Price where the wall exists
            wall_size: Size of the wall orders
            is_support: True if wall is on Bid side (Support), False if Ask side (Resistance)
        """
        # Base liquidity for non-wall side
        base_liquidity = 1000
        self._advance_time()
        
        if is_support:
            # Wall is on the Bid side
            # Ensure wall_price is below current price
            if wall_price >= price:
                wall_price = price - 0.01
                
            # Create normal asks
            asks = self._create_dom_levels(price + 0.01, 1, base_liquidity)
            
            # Create bids with a wall
            # We need to construct bids such that one level hits wall_price
            # Dynamically calculate needed levels to reach the wall
            dist = price - wall_price
            levels_needed = int(dist / 0.01) + 5  # +5 buffer
            levels_needed = min(max(10, levels_needed), 50)  # Clamp max 50 (realistic L2 depth)
            
            bids = []
            curr = price - 0.01
            for _ in range(levels_needed):
                size = 100 # Normal size
                if abs(curr - wall_price) < 0.001:
                    size = wall_size # The Wall
                
                bids.append(DOMLevel(round(curr, 2), size, ''))
                curr -= 0.01
                
            return Ticker(
                contract=self.contract,
                time=self.current_time,
                bid=bids[0].price,
                bidSize=bids[0].size,
                ask=asks[0].price,
                askSize=asks[0].size,
                last=price,
                domBids=bids,
                domAsks=asks
            )
        else:
            # Wall is on the Ask side (Resistance)
            if wall_price <= price:
                wall_price = price + 0.01
                
            bids = self._create_dom_levels(price - 0.01, -1, base_liquidity)
            
            dist = wall_price - price
            levels_needed = int(dist / 0.01) + 5
            levels_needed = min(max(10, levels_needed), 50)  # Clamp max 50
            
            asks = []
            curr = price + 0.01
            for _ in range(levels_needed):
                size = 100
                if abs(curr - wall_price) < 0.001:
                    size = wall_size
                
                asks.append(DOMLevel(round(curr, 2), size, ''))
                curr += 0.01
                
            return Ticker(
                contract=self.contract,
                time=self.current_time,
                bid=bids[0].price,
                bidSize=bids[0].size,
                ask=asks[0].price,
                askSize=asks[0].size,
                last=price,
                domBids=bids,
                domAsks=asks
            )

    def generate_sine_wave_price(self, base: float = 100.0, amplitude: float = 2.0, 
                                period: int = 20, steps: int = 50, 
                                noise: float = 0.1) -> List[float]:
        """
        Generates a list of prices oscillating like a sine wave.
        Useful for testing Swing Trading entries/exits.
        """
        prices = []
        for i in range(steps):
            # sin(x)
            angle = (i / period) * 2 * math.pi
            val = math.sin(angle) * amplitude
            
            # Add noise
            random_noise = random.uniform(-noise, noise)
            
            price = base + val + random_noise
            prices.append(round(price, 2))
            
        return prices

    def simulate_breakout(self, start_price: float, resistance_level: float, 
                         steps: int = 10) -> Generator[Ticker, None, None]:
        """
        Yields a sequence of Tickers simulating a breakout through resistance.
        
        Sequence:
        1. Price approaches resistance.
        2. Resistance wall appears.
        3. Volume spikes, wall gets eaten (size decreases).
        4. Price breaks through.
        """
        current_price = start_price
        wall_size = 5000
        
        step_size = (resistance_level - start_price) / (steps // 2)
        
        # Phase 0: Warmup (Establish Resistance for 5+ minutes)
        for _ in range(6):
            self._advance_time(60) # Advance 1 minute per tick
            yield self.generate_support_resistance(start_price, resistance_level, wall_size, is_support=False)

        # Phase 1: Approach
        for i in range(steps // 2):
            current_price += step_size
            # Generate ticker with resistance wall
            yield self.generate_support_resistance(current_price, resistance_level, wall_size, is_support=False)
            
        # Phase 2: Attack the wall (Absorption/Iceberg)
        # Fluctuate size to simulate consumption and refill (iceberg) to trigger variance check
        current_price = resistance_level
        for i in range(5):
            # Alternate between full wall and low size to create high variance (CV > 0.3)
            current_wall = wall_size if i % 2 == 0 else int(wall_size * 0.2)
            yield self.generate_support_resistance(current_price, resistance_level, current_wall, is_support=False)
            
        # Phase 3: Breakout (Price above resistance, wall gone)
        current_price = resistance_level + 0.10
        for i in range(steps - (steps // 2) - 3):
            current_price += 0.05
            # Normal bullish imbalance now
            yield self.generate_imbalance(current_price, skew=0.7)

    def simulate_bounce(self, start_price: float, support_level: float, 
                       steps: int = 10) -> Generator[Ticker, None, None]:
        """
        Yields a sequence simulating a bounce off support.
        Useful for testing Swing Trading 'buy the dip' logic.
        """
        current_price = start_price
        step_down = (start_price - support_level) / (steps // 2)
        
        # Phase 0: Warmup (Establish Support for 5+ minutes)
        for _ in range(6):
            self._advance_time(60) # Advance 1 minute per tick
            yield self.generate_support_resistance(start_price, support_level, is_support=True)

        # Phase 1: Drop to support
        for _ in range(steps // 2):
            current_price -= step_down
            # Ensure we don't go below support due to float math
            if current_price < support_level: 
                current_price = support_level
            yield self.generate_support_resistance(current_price, support_level, is_support=True)
            
        # Phase 2: Hit support and bounce up
        current_price = support_level
        yield self.generate_support_resistance(current_price, support_level, is_support=True)
        
        # Bounce up (Price increases, support wall holds)
        for i in range(steps // 2):
            current_price += 0.05
            yield self.generate_support_resistance(current_price, support_level, is_support=True)

    def simulate_absorption_support(self, start_price: float, support_level: float, 
                                   steps: int = 10) -> Generator[Ticker, None, None]:
        """
        Yields a sequence simulating absorption at support (Iceberg Bid).
        Triggers ABSORPTION_BREAKOUT_UP (Bullish).
        """
        current_price = start_price
        wall_size = 5000
        step_down = (start_price - support_level) / (steps // 2)
        
        # Phase 0: Warmup
        for _ in range(6):
            self._advance_time(60)
            yield self.generate_support_resistance(start_price, support_level, wall_size, is_support=True)
            
        # Phase 1: Drop to support
        for _ in range(steps // 2):
            current_price -= step_down
            if current_price < support_level: current_price = support_level
            yield self.generate_support_resistance(current_price, support_level, wall_size, is_support=True)
            
        # Phase 2: Absorption (Price at support, wall refreshes)
        current_price = support_level
        for i in range(5):
            # Fluctuate size to trigger variance check and refresh count
            current_wall = wall_size if i % 2 == 0 else int(wall_size * 0.2)
            yield self.generate_support_resistance(current_price, support_level, current_wall, is_support=True)
            
        # Phase 3: Bounce
        for i in range(5):
            current_price += 0.05
            yield self.generate_support_resistance(current_price, support_level, wall_size, is_support=True)

    def simulate_orb_breakout(self, orb_high: float, orb_low: float, 
                             breakout_price: float, vix_trend: str = "down") -> Generator[Ticker, None, None]:
        """
        Yields a sequence simulating an Opening Range Breakout with VIX context.
        
        Sequence:
        1. 9:30-9:45: Price oscillates within orb_high/orb_low to establish range.
        2. 9:45+: Price breaks out.
        3. VIX trends in specified direction.
        """
        # Set start time to 9:30 AM ET today
        now = datetime.now()
        start_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
        self.current_time = start_time
        
        current_price = (orb_high + orb_low) / 2
        vix_price = 20.0
        
        # Phase 1: Establish Range (9:30 - 9:45)
        # We generate ticks every minute
        for i in range(16): # 0 to 15 minutes
            # Oscillate price
            if i % 2 == 0:
                tick_price = orb_high - 0.05
            else:
                tick_price = orb_low + 0.05
                
            # VIX stays flat or choppy
            vix_price += random.uniform(-0.05, 0.05)
            
            ticker = self.generate_ticker(tick_price)
            ticker.vix_price = vix_price # Attach for testing
            yield ticker
            
            self._advance_time(60) # Advance 1 min

        # Phase 2: Breakout (9:46+)
        # Move VIX based on trend
        vix_step = -0.1 if vix_trend == "down" else 0.1
        
        # Move price towards breakout
        target = breakout_price
        step = (target - current_price) / 5
        
        for i in range(5):
            current_price += step
            vix_price += vix_step
            
            ticker = self.generate_ticker(current_price)
            ticker.vix_price = vix_price
            yield ticker
            
            self._advance_time(60)