"""
Trading Engine
Implements rule-based trading logic for options based on liquidity patterns
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from ib_insync import Contract
from ib_wrapper import IBWrapper
from liquidity_analyzer import LiquidityAnalyzer, Pattern, PatternSignal

logger = logging.getLogger(__name__)


class TradeDirection(Enum):
    """Trade direction"""
    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    NO_TRADE = "no_trade"


@dataclass
class TradeRule:
    """Rules for entering trades"""
    pattern: Pattern
    direction: TradeDirection
    min_confidence: float
    entry_condition: str  # Description


@dataclass
class Position:
    """Represents an open position"""
    contract: Contract
    entry_price: float
    entry_time: datetime
    quantity: int
    direction: TradeDirection
    stop_loss: float
    profit_target: float
    pattern: Pattern
    db_id: Optional[int] = None
    order_ref: Optional[str] = None


class TradingEngine:
    """
    Main trading engine that orchestrates pattern detection and trade execution
    """
    
    def __init__(self, ib_wrapper: IBWrapper, analyzer: LiquidityAnalyzer, config: Dict,
                 trade_db=None):
        """
        Initialize trading engine

        Args:
            ib_wrapper: IB API wrapper
            analyzer: Liquidity analyzer
            config: Trading configuration
            trade_db: Optional TradeDatabase for persistence
        """
        self.ib = ib_wrapper
        self.analyzer = analyzer
        self.config = config
        self.db = trade_db
        
        # Active positions
        self.positions: List[Position] = []
        
        # Trading rules
        self.rules = self._setup_rules()
        
        # Risk management
        self.max_position_size = config.get('max_position_size', 1000)
        self.max_positions = config.get('max_positions', 3)
        self.position_size_pct = config.get('position_size_pct', 0.02)  # 2% of account
        
        # Exit rules
        self.profit_target_pct = config.get('profit_target_pct', 0.5)  # 50%
        self.stop_loss_pct = config.get('stop_loss_pct', 0.3)  # 30%
        self.max_hold_days = config.get('max_hold_days', 30)
        
    def _setup_rules(self) -> List[TradeRule]:
        """
        Setup trading rules from configuration
        
        Returns:
            List of trade rules
        """
        rules_config = self.config.get('trading_rules', {})
        
        return [
            TradeRule(
                pattern=Pattern.REJECTION_AT_SUPPORT,
                direction=TradeDirection.LONG_CALL,
                min_confidence=rules_config.get('rejection_support_confidence', 0.6),
                entry_condition="Price bounces off strong support with high confidence"
            ),
            TradeRule(
                pattern=Pattern.POTENTIAL_BREAKOUT_UP,
                direction=TradeDirection.LONG_CALL,
                min_confidence=rules_config.get('breakout_up_confidence', 0.7),
                entry_condition="Strong buy imbalance suggesting upward breakout"
            ),
            TradeRule(
                pattern=Pattern.REJECTION_AT_RESISTANCE,
                direction=TradeDirection.LONG_PUT,
                min_confidence=rules_config.get('rejection_resistance_confidence', 0.6),
                entry_condition="Price rejects at strong resistance with high confidence"
            ),
            TradeRule(
                pattern=Pattern.POTENTIAL_BREAKOUT_DOWN,
                direction=TradeDirection.LONG_PUT,
                min_confidence=rules_config.get('breakout_down_confidence', 0.7),
                entry_condition="Strong sell imbalance suggesting downward breakout"
            ),
        ]
    
    def evaluate_signal(self, signal: PatternSignal) -> Optional[TradeDirection]:
        """
        Evaluate if signal meets trading rules
        
        Args:
            signal: Pattern signal from analyzer
            
        Returns:
            Trade direction or None
        """
        for rule in self.rules:
            if rule.pattern == signal.pattern and signal.confidence >= rule.min_confidence:
                logger.info(f"Signal matches rule: {rule.entry_condition}")
                return rule.direction
        
        return None
    
    def calculate_position_size(self, option_price: float) -> int:
        """
        Calculate position size based on account value
        
        Args:
            option_price: Price per option contract
            
        Returns:
            Number of contracts to trade
        """
        account_value = self.ib.get_account_value()
        if account_value is None:
            logger.warning("Could not get account value, using default position size")
            return 1
        
        # Calculate dollar amount to risk
        position_value = account_value * self.position_size_pct
        
        # Calculate contracts (each option controls 100 shares)
        contracts = int(position_value / (option_price * 100))
        
        # Apply limits
        contracts = max(1, min(contracts, self.max_positions))
        
        # Check against max position size
        total_cost = contracts * option_price * 100
        if total_cost > self.max_position_size:
            contracts = int(self.max_position_size / (option_price * 100))
        
        return max(1, contracts)
    
    def select_option(self, symbol: str, direction: TradeDirection,
                     current_price: float) -> Optional[Contract]:
        """
        Select appropriate option contract based on direction
        
        Args:
            symbol: Stock symbol
            direction: Trade direction
            current_price: Current stock price
            
        Returns:
            Option contract or None
        """
        # Get option chain
        chain, expiries = self.ib.get_option_chain(
            symbol,
            expiry_days_min=self.config.get('min_dte', 7),
            expiry_days_max=self.config.get('max_dte', 45)
        )
        
        if not expiries:
            logger.warning(f"No valid option expirations found for {symbol}")
            return None
        
        # Select expiration (use first available)
        expiry = expiries[0]
        
        # Determine strike and right
        if direction == TradeDirection.LONG_CALL:
            strike_pct = self.config.get('call_strike_pct', 1.02)
            right = 'C'
        elif direction == TradeDirection.LONG_PUT:
            strike_pct = self.config.get('put_strike_pct', 0.98)
            right = 'P'
        else:
            return None
        
        target_strike = current_price * strike_pct
        
        # Try strikes in order of closeness to target
        # chain.strikes contains all strikes across all expirations
        # We need to find one that actually exists for our chosen expiry
        if not chain.strikes:
            logger.error(f"No strikes available in chain for {symbol}")
            return None
        
        # Sort all available strikes by proximity to target
        # The chain already contains only valid strikes for this symbol
        sorted_strikes = sorted(chain.strikes, key=lambda x: abs(x - target_strike))
        
        # Try up to 10 closest strikes (increased from 5)
        max_attempts = min(10, len(sorted_strikes))
        
        for i, strike in enumerate(sorted_strikes[:max_attempts]):
            contract = self.ib.find_option_contract(symbol, strike, expiry, right)
            
            # Check if contract was qualified (localSymbol gets populated)
            if contract and hasattr(contract, 'localSymbol') and contract.localSymbol:
                logger.info(f"Selected option: {contract.localSymbol} (tried {i+1} strikes)")
                return contract
        
        logger.error(f"Could not find valid option contract for {symbol} near ${target_strike:.2f}")
        return None
    
    def _round_strike(self, target_strike: float, available_strikes: List[float]) -> float:
        """Find nearest available strike price"""
        if not available_strikes:
            return round(target_strike, 1)
        
        return min(available_strikes, key=lambda x: abs(x - target_strike))
    
    def enter_trade(self, symbol: str, direction: TradeDirection,
                   signal: PatternSignal) -> bool:
        """
        Enter a trade based on signal
        
        Args:
            symbol: Stock symbol
            direction: Trade direction
            signal: Pattern signal
            
        Returns:
            True if trade entered successfully
        """
        # Check if we can take more positions
        if len(self.positions) >= self.max_positions:
            logger.info("Maximum positions reached, skipping trade")
            return False

        # Check if we already have a position in this symbol
        for p in self.positions:
            if p.contract.symbol == symbol:
                logger.info(f"Already holding a position in {symbol}, skipping")
                return False
        
        # Get current price
        current_price = self.ib.get_stock_price(symbol)
        if current_price is None:
            logger.error("Could not get current price")
            return False
        
        # Select option
        contract = self.select_option(symbol, direction, current_price)
        if contract is None:
            logger.error("Could not select option contract")
            return False
        
        # Get option price
        price_data = self.ib.get_option_price(contract)
        if price_data is None:
            logger.error("Could not get option price")
            return False
        
        bid, ask, last = price_data
        raw_price = (bid + ask) / 2 if bid > 0 and ask > 0 else last
        # Round to nearest $0.05 tick (standard option tick increment)
        entry_price = round(raw_price * 20) / 20
        
        if entry_price <= 0:
            logger.error("Invalid option price")
            return False
        
        # Calculate position size
        quantity = self.calculate_position_size(entry_price)
        
        logger.info(f"Entering trade: {contract.localSymbol} x{quantity} @ ${entry_price:.2f}")

        # Calculate exit levels
        profit_target = entry_price * (1 + self.profit_target_pct)
        stop_loss = entry_price * (1 - self.stop_loss_pct)

        # Generate order tag and persist before placing order (crash safety)
        order_ref = None
        db_id = None
        if self.db:
            order_ref = self.db.generate_order_ref()
            db_id = self.db.insert_position({
                'symbol': contract.symbol,
                'local_symbol': contract.localSymbol,
                'con_id': contract.conId,
                'strike': contract.strike,
                'expiry': contract.lastTradeDateOrContractMonth,
                'right': contract.right,
                'exchange': contract.exchange or 'SMART',
                'entry_price': entry_price,
                'entry_time': datetime.now().isoformat(),
                'quantity': quantity,
                'direction': direction.value,
                'stop_loss': stop_loss,
                'profit_target': profit_target,
                'pattern': signal.pattern.value,
                'entry_order_id': None,
                'order_ref': order_ref,
                'status': 'pending_fill',
            })

        # Place order (using limit order at mid-price)
        trade = self.ib.buy_option(
            contract, quantity, limit_price=entry_price, order_ref=order_ref
        )

        if trade is None:
            logger.error("Failed to place order")
            if self.db and db_id:
                self.db.close_position(db_id, 0, 'order_failed')
            return False

        # Update DB with order ID and mark as open
        if self.db and db_id:
            self.db.update_position_order_id(db_id, trade.order.orderId)
            self.db.update_position_status(db_id, 'open')

        # Track position in memory
        position = Position(
            contract=contract,
            entry_price=entry_price,
            entry_time=datetime.now(),
            quantity=quantity,
            direction=direction,
            stop_loss=stop_loss,
            profit_target=profit_target,
            pattern=signal.pattern,
            db_id=db_id,
            order_ref=order_ref,
        )

        self.positions.append(position)

        logger.info(f"Trade entered successfully. Stop: ${stop_loss:.2f}, Target: ${profit_target:.2f}")
        return True
    
    def check_exits(self):
        """Check all positions for exit conditions"""
        # First, detect positions removed externally (manual sell)
        self._check_manual_closes()

        for position in self.positions[:]:  # Copy list to allow removal
            should_exit, reason = self._should_exit_position(position)

            if should_exit:
                self._exit_position(position, reason)

    def _check_manual_closes(self):
        """Detect bot positions that were closed manually in TWS/IBKR."""
        if not self.positions:
            return

        # Build lookup of IB portfolio by conId
        ib_portfolio = self.ib.get_portfolio()
        ib_by_conid: Dict[int, int] = {}
        for item in ib_portfolio:
            con_id = item.contract.conId
            ib_by_conid[con_id] = ib_by_conid.get(con_id, 0) + int(abs(item.position))

        for position in self.positions[:]:
            con_id = position.contract.conId
            ib_qty = ib_by_conid.get(con_id, 0)

            if ib_qty == 0:
                # Position gone from IB entirely — closed manually
                logger.info(
                    f"Position {position.contract.localSymbol} no longer in IB portfolio "
                    f"-- assuming manual close"
                )
                if self.db and position.db_id:
                    self.db.close_position(
                        position_id=position.db_id,
                        exit_price=0,
                        exit_reason='manual_close',
                    )
                self.positions.remove(position)
    
    def _should_exit_position(self, position: Position) -> tuple[bool, str]:
        """
        Check if position should be exited
        
        Returns:
            (should_exit, reason)
        """
        # Get current option price
        price_data = self.ib.get_option_price(position.contract)
        if price_data is None:
            logger.warning("Could not get option price for exit check")
            return False, ""
        
        bid, ask, last = price_data
        current_price = (bid + ask) / 2 if bid > 0 and ask > 0 else last
        
        if current_price <= 0:
            return False, ""
        
        # Check profit target
        if current_price >= position.profit_target:
            return True, f"Profit target reached (${current_price:.2f} >= ${position.profit_target:.2f})"
        
        # Check stop loss
        if current_price <= position.stop_loss:
            return True, f"Stop loss hit (${current_price:.2f} <= ${position.stop_loss:.2f})"
        
        # Check time-based exit
        days_held = (datetime.now() - position.entry_time).days
        if days_held >= self.max_hold_days:
            return True, f"Max hold period reached ({days_held} days)"
        
        return False, ""
    
    def _exit_position(self, position: Position, reason: str):
        """Exit a position"""
        logger.info(f"Exiting position: {position.contract.localSymbol}. Reason: {reason}")

        # Place sell order
        trade = self.ib.sell_option(position.contract, position.quantity)

        if trade:
            # Persist to trade history
            if self.db and position.db_id:
                exit_price = 0
                if trade.orderStatus and trade.orderStatus.avgFillPrice > 0:
                    exit_price = trade.orderStatus.avgFillPrice
                self.db.close_position(
                    position_id=position.db_id,
                    exit_price=exit_price,
                    exit_reason=reason,
                    exit_order_id=trade.order.orderId,
                )
            # Remove from in-memory positions
            self.positions.remove(position)
            logger.info(f"Position exited successfully")
        else:
            logger.error("Failed to exit position")
    
    def get_status(self) -> Dict:
        """Get current trading status"""
        status = {
            'positions': len(self.positions),
            'max_positions': self.max_positions,
            'active_contracts': [f"{p.contract.localSymbol} x{p.quantity}" for p in self.positions],
            'account_value': self.ib.get_account_value(),
            'pnl': None,
        }
        if self.db:
            status['pnl'] = self.db.get_bot_pnl_summary()
        return status
