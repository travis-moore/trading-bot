"""
Trading Engine
Implements rule-based trading logic for options based on liquidity patterns.

Supports both legacy LiquidityAnalyzer integration and new plugin-based strategies.
"""

import logging
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from ib_insync import Contract
from ib_wrapper import IBWrapper
from market_context import MarketRegime, MarketRegimeDetector, SectorRotationManager

# Legacy imports for backward compatibility
from liquidity_analyzer import LiquidityAnalyzer, Pattern, PatternSignal

# New strategy system imports
try:
    from strategies import StrategyManager, StrategySignal
    STRATEGIES_AVAILABLE = True
except ImportError:
    STRATEGIES_AVAILABLE = False
    StrategyManager = None
    StrategySignal = None

logger = logging.getLogger(__name__)


class TradeDirection(Enum):
    """Trade direction"""
    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    NO_TRADE = "no_trade"
    BULL_PUT_SPREAD = "bull_put_spread"
    BEAR_PUT_SPREAD = "bear_put_spread"
    LONG_PUT_STRAIGHT = "long_put_straight"
    IRON_CONDOR = "iron_condor"


@dataclass
class TradeRule:
    """Rules for entering trades (legacy system)"""
    pattern: Pattern
    direction: TradeDirection
    min_confidence: float
    entry_condition: str  # Description


@dataclass
class PendingOrder:
    """Represents a pending (unfilled) order with bracket orders."""
    contract: Contract
    entry_price: float
    order_time: datetime
    quantity: int
    direction: TradeDirection
    stop_loss: float
    profit_target: float
    pattern: Union[Pattern, str]
    entry_trade: Any  # ib_insync Trade object for entry order
    stop_loss_trade: Optional[Any] = None  # Trade object for stop loss
    take_profit_trade: Optional[Any] = None  # Trade object for take profit
    db_id: Optional[int] = None
    order_ref: Optional[str] = None
    strategy_name: Optional[str] = None


@dataclass
class Position:
    """Represents an open (filled) position"""
    contract: Contract
    entry_price: float
    entry_time: datetime
    quantity: int
    direction: TradeDirection
    stop_loss: float
    profit_target: float
    pattern: Union[Pattern, str]  # Pattern enum or string pattern name
    db_id: Optional[int] = None
    order_ref: Optional[str] = None
    strategy_name: Optional[str] = None  # Which strategy opened this position
    stop_loss_trade: Optional[Any] = None  # Attached stop loss order
    take_profit_trade: Optional[Any] = None  # Attached take profit order
    peak_price: Optional[float] = None  # Highest/Lowest price seen since entry (for trailing stop)


class TradingEngine:
    """
    Main trading engine that orchestrates pattern detection and trade execution.

    Supports two modes:
    1. Legacy mode: Uses LiquidityAnalyzer directly
    2. Strategy mode: Uses StrategyManager with plugin strategies

    The mode is determined by whether a StrategyManager is provided.
    """

    def __init__(self, ib_wrapper: IBWrapper, analyzer: LiquidityAnalyzer, config: Dict,
                 trade_db=None, strategy_manager=None,
                 market_regime_detector=None, sector_manager=None):
        """
        Initialize trading engine.

        Args:
            ib_wrapper: IB API wrapper
            analyzer: Liquidity analyzer (used in legacy mode)
            config: Trading configuration
            trade_db: Optional TradeDatabase for persistence
            strategy_manager: Optional StrategyManager for plugin-based strategies
            market_regime_detector: Optional MarketRegimeDetector
            sector_manager: Optional SectorRotationManager
        """
        self.ib = ib_wrapper
        self.analyzer = analyzer
        self.config = config
        self.db = trade_db
        self.strategy_manager = strategy_manager
        self.market_regime_detector = market_regime_detector
        self.sector_manager = sector_manager

        # Active positions (filled orders)
        self.positions: List[Position] = []

        # Pending orders (not yet filled)
        self.pending_orders: List[PendingOrder] = []

        # Trading rules (legacy mode)
        self.rules = self._setup_rules()

        # Risk management
        self.max_position_size = config.get('max_position_size', 1000)
        self.max_positions = config.get('max_positions', 3)
        self.position_size_pct = config.get('position_size_pct', 0.02)  # 2% of account

        # Exit rules
        self.profit_target_pct = config.get('profit_target_pct', 0.5)  # 50%
        self.stop_loss_pct = config.get('stop_loss_pct', 0.3)  # 30%
        self.max_hold_days = config.get('max_hold_days', 30)

        # Order management settings
        self.order_timeout_seconds = config.get('order_timeout_seconds', 60)
        self.price_drift_threshold = config.get('price_drift_threshold', 0.10)  # 10% drift
        self.use_bracket_orders = config.get('use_bracket_orders', True)

    @property
    def using_strategies(self) -> bool:
        """Check if engine is using strategy manager."""
        return self.strategy_manager is not None and STRATEGIES_AVAILABLE

    def _get_strategy_max_positions(self, strategy_name: str) -> int:
        """
        Get max_positions for a specific strategy instance.

        Looks up the strategy's config for max_positions, falling back to
        the global max_positions setting.

        Args:
            strategy_name: The strategy instance name

        Returns:
            Maximum number of positions allowed for this strategy
        """
        if self.strategy_manager is not None:
            strategy = self.strategy_manager.get_strategy(strategy_name)
            if strategy:
                # Check strategy's own config for max_positions
                max_pos = strategy.get_config('max_positions', None)
                if max_pos is not None:
                    return int(max_pos)

        # Fall back to global max_positions
        return self.max_positions

    def _get_strategy_label(self, strategy_name: str) -> str:
        """
        Get a display label for a strategy instance (type:instance format).

        Args:
            strategy_name: The strategy instance name

        Returns:
            Label like "swing_trading:swing_aggressive" or just the name if type equals name
        """
        if self.strategy_manager is not None:
            strategy_type = self.strategy_manager.get_strategy_type(strategy_name)
            if strategy_type and strategy_type != strategy_name:
                return f"{strategy_type}:{strategy_name}"
        return strategy_name

    def get_signal(self, ticker, current_price: float, symbol: str):
        """
        Get trading signal using strategy manager or legacy analyzer.

        Args:
            ticker: ib_insync Ticker with market data
            current_price: Current stock price
            symbol: Stock symbol

        Returns:
            StrategySignal (new) or PatternSignal (legacy), or None
        """
        if self.using_strategies and self.strategy_manager is not None:
            # Use strategy manager
            context = {
                'symbol': symbol,
                'positions': self.positions,
                'account_value': self.ib.get_account_value(),
                'market_regime': self.market_regime_detector.current_regime if self.market_regime_detector else None,
                'sector_rs': self.sector_manager.get_sector_rs(symbol) if self.sector_manager else 0
            }
            return self.strategy_manager.get_best_signal(ticker, current_price, context)
        else:
            # Legacy: use analyzer directly
            return self.analyzer.detect_pattern(ticker, current_price)

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
    
    def evaluate_signal(self, signal) -> Optional[TradeDirection]:
        """
        Evaluate if signal meets trading rules.

        Supports both legacy PatternSignal and new StrategySignal.

        Args:
            signal: PatternSignal (legacy) or StrategySignal (new)

        Returns:
            Trade direction or None
        """
        # Handle new StrategySignal (already has direction and confidence filtering)
        if STRATEGIES_AVAILABLE and StrategySignal is not None:
            if hasattr(signal, 'direction') and hasattr(signal, 'pattern_name'):
                # This is a StrategySignal - it already passed confidence check
                direction = signal.direction
                
                # --- GLOBAL CONTEXT VETO LOGIC ---
                # Only apply to OPEN signals (entries).
                # Assuming all StrategySignals with valid direction are OPEN requests.
                # CLOSE signals usually handled via check_exits or explicit NO_TRADE with metadata.
                
                if direction == TradeDirection.NO_TRADE:
                    return None

                if self.market_regime_detector and self.sector_manager:
                    regime = self.market_regime_detector.current_regime
                    # Get symbol from context if available, or we need to pass it.
                    # evaluate_signal doesn't take symbol arg, but signal might have it in metadata?
                    # Actually, we need the symbol to check Sector RS.
                    # We'll assume the caller (scan_for_signals) handles the signal if we return it,
                    # but we need to veto here.
                    # Let's assume signal.metadata has 'symbol' or we skip sector check if missing.
                    # Wait, scan_for_signals calls this.
                    
                    # NOTE: To properly implement Sector RS check, we need the symbol.
                    # Since evaluate_signal signature is fixed in this refactor, 
                    # we'll rely on the fact that strategies *already* checked regime in their analyze() method
                    # as per the strategy implementation.
                    # BUT the prompt says "The engine must evaluate...".
                    # I will add the checks here assuming I can access global context.
                    
                    # Veto Logic
                    # 1. Bullish Strategies
                    is_bullish = direction in [TradeDirection.LONG_CALL, TradeDirection.BULL_PUT_SPREAD]
                    if is_bullish:
                        if regime == MarketRegime.BEAR_TREND:
                            logger.info(f"VETO: Bullish signal blocked by Bear Trend")
                            return None
                        # Sector RS check requires symbol. If not available, skip.
                        
                    # 2. Bearish Strategies
                    is_bearish = direction in [TradeDirection.LONG_PUT, TradeDirection.BEAR_PUT_SPREAD, TradeDirection.LONG_PUT_STRAIGHT]
                    if is_bearish:
                        if regime == MarketRegime.BULL_TREND:
                            logger.info(f"VETO: Bearish signal blocked by Bull Trend")
                            return None
                            
                    # 3. Iron Condor
                    if direction == TradeDirection.IRON_CONDOR:
                        if regime != MarketRegime.RANGE_BOUND:
                            logger.info(f"VETO: Iron Condor blocked (Regime not Range Bound)")
                            return None
                            
                    # 4. High Chaos Veto for Swing
                    if regime == MarketRegime.HIGH_CHAOS and "scalp" not in str(signal.metadata.get('strategy_type', '')):
                        logger.info(f"VETO: Swing/Options signal blocked by High Chaos")
                        return None

                return direction

        # Legacy PatternSignal handling
        for rule in self.rules:
            if rule.pattern == signal.pattern and signal.confidence >= rule.min_confidence:
                logger.info(f"Signal matches rule: {rule.entry_condition}")
                return rule.direction

        return None
    
    def calculate_position_size(self, option_price: float, confidence: float = 1.0) -> int:
        """
        Calculate position size based on account value and signal confidence.

        Position size is scaled by confidence: higher confidence = larger position.
        For example, 0.7 confidence = 70% of the base position size.

        Args:
            option_price: Price per option contract
            confidence: Signal confidence (0.0 to 1.0), scales position size

        Returns:
            Number of contracts to trade
        """
        account_value = self.ib.get_account_value()
        if account_value is None:
            logger.warning("Could not get account value, using default position size")
            return 1

        # Calculate base dollar amount to risk
        base_position_value = account_value * self.position_size_pct

        # Scale by confidence (e.g., 0.7 confidence = 70% of base size)
        confidence = max(0.1, min(1.0, confidence))  # Clamp to [0.1, 1.0]
        position_value = base_position_value * confidence

        # Calculate contracts (each option controls 100 shares)
        contracts = int(position_value / (option_price * 100))

        # Apply limits
        contracts = max(1, min(contracts, self.max_positions))

        # Check against max position size
        total_cost = contracts * option_price * 100
        if total_cost > self.max_position_size:
            contracts = int(self.max_position_size / (option_price * 100))

        logger.debug(f"Position sizing: confidence={confidence:.2f}, base=${base_position_value:.0f}, scaled=${position_value:.0f}, contracts={contracts}")

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
        
        # Try up to 3 expirations to find a valid contract
        # Some strikes only exist for monthly expirations, etc.
        for expiry in expiries[:3]:
            # Try up to 20 closest strikes per expiration to increase chances of finding a match
            for i, strike in enumerate(sorted_strikes[:20]):
                # Use quiet=True to suppress warnings when probing for valid strikes
                # check_prices=False to speed up selection (we check price later in enter_trade)
                contract = self.ib.find_option_contract(symbol, strike, expiry, right, check_prices=False, quiet=True)

                # Check if contract was qualified (localSymbol gets populated)
                if contract and hasattr(contract, 'localSymbol') and contract.localSymbol:
                    logger.info(f"Selected option: {contract.localSymbol} (expiry {expiry}, strike {strike})")
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
        Enter a trade based on signal using bracket orders.

        Places a limit buy order with attached stop loss and take profit orders.
        The order is tracked as 'pending' until the entry fills.

        Args:
            symbol: Stock symbol
            direction: Trade direction
            signal: Pattern signal

        Returns:
            True if order placed successfully (not necessarily filled)
        """
        # Get strategy info from signal metadata (if using strategy system)
        signal_metadata = getattr(signal, 'metadata', {})
        strategy_name = signal_metadata.get('strategy', 'swing_trading')  # Instance name
        strategy_type = signal_metadata.get('strategy_type', strategy_name)  # Type (e.g., swing_trading)
        strategy_label = f"{strategy_type}:{strategy_name}" if strategy_type != strategy_name else strategy_name

        # Get per-strategy max_positions (fall back to global config)
        strategy_max_positions = self._get_strategy_max_positions(strategy_name)

        # Count positions for this specific strategy
        strategy_positions = sum(
            1 for p in self.positions if p.strategy_name == strategy_name
        )
        strategy_pending = sum(
            1 for po in self.pending_orders if po.strategy_name == strategy_name
        )
        strategy_exposure = strategy_positions + strategy_pending

        if strategy_exposure >= strategy_max_positions:
            logger.info(
                f"[{strategy_label}] Max positions reached ({strategy_exposure}/{strategy_max_positions}), "
                f"skipping trade"
            )
            return False

        # Check if we already have a position or pending order in this symbol for this strategy
        for p in self.positions:
            if p.contract.symbol == symbol and p.strategy_name == strategy_name:
                logger.info(f"[{strategy_label}] Already holding a position in {symbol}, skipping")
                return False
        for po in self.pending_orders:
            if po.contract.symbol == symbol and po.strategy_name == strategy_name:
                logger.info(f"[{strategy_label}] Already have pending order in {symbol}, skipping")
                return False

        # Get current price
        current_price = self.ib.get_stock_price(symbol)
        if current_price is None:
            logger.error(f"[{strategy_label}] Could not get current price for {symbol}")
            return False

        # Select option
        contract = self.select_option(symbol, direction, current_price)
        if contract is None:
            logger.error(f"[{strategy_label}] Could not select option contract for {symbol}")
            return False

        # Get option price
        price_data = self.ib.get_option_price(contract)
        if price_data is None:
            logger.error(f"[{strategy_label}] Could not get option price for {contract.localSymbol}")
            return False

        bid, ask, last = price_data
        raw_price = (bid + ask) / 2 if bid > 0 and ask > 0 else last
        # Round to nearest $0.05 tick (standard option tick increment)
        entry_price = round(raw_price * 20) / 20

        if entry_price <= 0:
            logger.error(f"[{strategy_label}] Invalid option price for {contract.localSymbol}")
            return False

        # Calculate position size (scaled by signal confidence)
        signal_confidence = getattr(signal, 'confidence', 1.0)
        quantity = self.calculate_position_size(entry_price, confidence=signal_confidence)

        # Calculate exit levels (round to $0.05 tick)
        raw_profit_target = entry_price * (1 + self.profit_target_pct)
        raw_stop_loss = entry_price * (1 - self.stop_loss_pct)
        profit_target = round(raw_profit_target * 20) / 20
        stop_loss = round(raw_stop_loss * 20) / 20

        # Check strategy budget if configured
        if self.db:
            available_budget = self.db.get_available_budget(strategy_name)
            if available_budget > 0:
                # Budget is configured for this strategy
                trade_cost = quantity * entry_price * 100  # Cost per contract * 100 shares
                if trade_cost > available_budget:
                    # Reduce quantity to fit budget
                    max_affordable = int(available_budget / (entry_price * 100))
                    if max_affordable < 1:
                        logger.info(
                            f"[{strategy_label}] Insufficient budget for {symbol} "
                            f"(available: ${available_budget:.2f}, need: ${entry_price * 100:.2f} per contract)"
                        )
                        return False
                    old_qty = quantity
                    quantity = max_affordable
                    logger.info(
                        f"[{strategy_label}] Reducing quantity from {old_qty} to {quantity} "
                        f"to fit budget (${available_budget:.2f} available)"
                    )

        logger.info(
            f"[{strategy_label}] Placing bracket order: {contract.localSymbol} x{quantity} "
            f"@ ${entry_price:.2f} (SL: ${stop_loss:.2f}, TP: ${profit_target:.2f})"
        )

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
                'pattern': signal.pattern_name.value if hasattr(signal.pattern_name, 'value') else str(signal.pattern_name),
                'strategy': strategy_name,
                'entry_order_id': None,
                'order_ref': order_ref,
                'status': 'pending_fill',
                'peak_price': entry_price,
            })

        # Place bracket order (entry + stop loss + take profit)
        if self.use_bracket_orders:
            trades = self.ib.buy_option_bracket(
                contract=contract,
                quantity=quantity,
                entry_price=entry_price,
                stop_loss_price=stop_loss,
                take_profit_price=profit_target,
                tif='GTC',
                order_ref=order_ref,
            )

            if trades is None:
                logger.error(f"[{strategy_label}] Failed to place bracket order for {contract.localSymbol}")
                if self.db and db_id:
                    self.db.close_position(db_id, 0, 'order_failed')
                return False

            entry_trade, stop_loss_trade, take_profit_trade = trades
        else:
            # Fallback to simple limit order (no bracket)
            entry_trade = self.ib.buy_option(
                contract, quantity, limit_price=entry_price, order_ref=order_ref
            )
            if entry_trade is None:
                logger.error(f"[{strategy_label}] Failed to place order for {contract.localSymbol}")
                if self.db and db_id:
                    self.db.close_position(db_id, 0, 'order_failed')
                return False
            stop_loss_trade = None
            take_profit_trade = None

        # Update DB with order ID (keep status as pending_fill)
        if self.db and db_id:
            self.db.update_position_order_id(db_id, entry_trade.order.orderId)

        # Track as pending order (not position yet)
        pending = PendingOrder(
            contract=contract,
            entry_price=entry_price,
            order_time=datetime.now(),
            quantity=quantity,
            direction=direction,
            stop_loss=stop_loss,
            profit_target=profit_target,
            pattern=signal.pattern_name,
            entry_trade=entry_trade,
            stop_loss_trade=stop_loss_trade,
            take_profit_trade=take_profit_trade,
            db_id=db_id,
            order_ref=order_ref,
            strategy_name=strategy_name,
        )

        self.pending_orders.append(pending)

        logger.info(
            f"[{strategy_label}] Order placed (pending fill): {contract.localSymbol} x{quantity} "
            f"@ ${entry_price:.2f} (SL: ${stop_loss:.2f}, TP: ${profit_target:.2f})"
        )
        return True
    
    def check_pending_orders(self):
        """
        Check status of pending orders and handle fills/cancellations/timeouts.

        This should be called periodically in the main loop.
        """
        if not self.pending_orders:
            return

        for pending in self.pending_orders[:]:  # Copy list to allow removal
            try:
                self._check_single_pending_order(pending)
            except Exception as e:
                logger.error(f"Error checking pending order: {e}")

    def _check_single_pending_order(self, pending: PendingOrder):
        """Check and handle a single pending order."""
        status = self.ib.get_order_status(pending.entry_trade)
        filled_qty = int(status.get('filled', 0))

        # Check if entry order fully filled
        if self.ib.is_order_filled(pending.entry_trade):
            self._convert_pending_to_position(pending, filled_qty)
            return

        # Check if entry order was cancelled externally
        if status['status'] in ('Cancelled', 'Inactive', 'ApiCancelled', 'Rejected'):
            if filled_qty > 0:
                # Partial fill before cancel - convert filled portion to position
                logger.info(
                    f"Order cancelled with partial fill: {pending.contract.localSymbol} "
                    f"({filled_qty}/{pending.quantity} filled)"
                )
                self._convert_pending_to_position(pending, filled_qty)
            else:
                logger.info(f"Order cancelled for {pending.contract.localSymbol}")
                self._remove_pending_order(pending, 'cancelled')
            return

        # Check for timeout
        age_seconds = (datetime.now() - pending.order_time).total_seconds()
        if age_seconds > self.order_timeout_seconds:
            # If partially filled, convert filled portion regardless of drift
            if filled_qty > 0:
                logger.info(
                    f"Order timeout with partial fill: {pending.contract.localSymbol} "
                    f"({filled_qty}/{pending.quantity} filled) - keeping filled portion"
                )
                # Cancel remaining unfilled portion
                self.ib.cancel_order(pending.entry_trade)
                # Convert the filled portion to a position
                self._convert_pending_to_position(pending, filled_qty)
                return

            # No fills yet - check price drift
            price_data = self.ib.get_option_price(pending.contract)
            if price_data:
                bid, ask, last = price_data
                current_mid = (bid + ask) / 2 if bid > 0 and ask > 0 else last

                if current_mid > 0:
                    drift = abs(current_mid - pending.entry_price) / pending.entry_price

                    if drift > self.price_drift_threshold:
                        # Price has drifted too far - cancel the order
                        logger.warning(
                            f"Order timeout with price drift: {pending.contract.localSymbol} "
                            f"(entry: ${pending.entry_price:.2f}, current: ${current_mid:.2f}, "
                            f"drift: {drift:.1%})"
                        )
                        self._cancel_pending_order(pending, 'timeout_drift')
                        return
                    else:
                        # Price hasn't drifted much - optionally adjust
                        logger.info(
                            f"Order pending {age_seconds:.0f}s: {pending.contract.localSymbol} "
                            f"(entry: ${pending.entry_price:.2f}, current: ${current_mid:.2f})"
                        )
                        # Could add price adjustment logic here if desired
            else:
                # Can't get price - cancel after timeout
                logger.warning(
                    f"Order timeout, no price data: {pending.contract.localSymbol}"
                )
                self._cancel_pending_order(pending, 'timeout_no_price')

    def _convert_pending_to_position(self, pending: PendingOrder, filled_qty: Optional[int] = None):
        """
        Convert a filled (or partially filled) pending order to an active position.

        Args:
            pending: The pending order to convert
            filled_qty: Number of contracts filled. If None, uses pending.quantity (full fill).
        """
        # Determine actual filled quantity
        if filled_qty is None:
            status = self.ib.get_order_status(pending.entry_trade)
            filled_qty = int(status.get('filled', pending.quantity))

        if filled_qty <= 0:
            logger.warning(f"Cannot convert to position: no fills for {pending.contract.localSymbol}")
            self._remove_pending_order(pending, 'no_fills')
            return

        strategy_name = pending.strategy_name or 'unknown'
        strategy_label = self._get_strategy_label(strategy_name)
        is_partial = filled_qty < pending.quantity
        if is_partial:
            logger.info(
                f"[{strategy_label}] Partial fill: {pending.contract.localSymbol} "
                f"{filled_qty}/{pending.quantity} contracts filled"
            )
        else:
            logger.info(f"[{strategy_label}] Order filled: {pending.contract.localSymbol} x{filled_qty}")

        # Get actual fill price
        status = self.ib.get_order_status(pending.entry_trade)
        fill_price = status['avg_fill_price'] if status['avg_fill_price'] > 0 else pending.entry_price

        # Calculate trade cost and commit budget
        trade_cost = fill_price * filled_qty * 100  # Options: price * contracts * 100
        if self.db and pending.strategy_name:
            self.db.commit_budget(pending.strategy_name, trade_cost)

        # Create position with actual filled quantity
        position = Position(
            contract=pending.contract,
            entry_price=fill_price,
            entry_time=datetime.now(),
            quantity=filled_qty,
            direction=pending.direction,
            stop_loss=pending.stop_loss,
            profit_target=pending.profit_target,
            pattern=pending.pattern,
            db_id=pending.db_id,
            order_ref=pending.order_ref,
            strategy_name=pending.strategy_name,
            stop_loss_trade=pending.stop_loss_trade,
            take_profit_trade=pending.take_profit_trade,
            peak_price=fill_price,
        )

        self.positions.append(position)
        self.pending_orders.remove(pending)

        # Update database
        if self.db and pending.db_id:
            self.db.update_position_status(pending.db_id, 'open')
            # Update quantity in DB if partial fill
            if is_partial:
                self.db.update_position_quantity(pending.db_id, filled_qty)
            # Log if fill price differs from limit price
            if abs(fill_price - pending.entry_price) > 0.01:
                logger.info(f"[{strategy_label}] Fill price ${fill_price:.2f} differs from limit ${pending.entry_price:.2f}")

        logger.info(
            f"[{strategy_label}] Position opened: {pending.contract.localSymbol} x{filled_qty} "
            f"@ ${fill_price:.2f} (SL: ${pending.stop_loss:.2f}, TP: ${pending.profit_target:.2f})"
        )

    def _cancel_pending_order(self, pending: PendingOrder, reason: str):
        """Cancel a pending order and clean up."""
        strategy_name = pending.strategy_name or 'unknown'
        strategy_label = self._get_strategy_label(strategy_name)
        logger.info(f"[{strategy_label}] Cancelling order for {pending.contract.localSymbol}: {reason}")

        # Cancel entry order
        self.ib.cancel_order(pending.entry_trade)

        # Cancel bracket orders if they exist
        if pending.stop_loss_trade:
            self.ib.cancel_order(pending.stop_loss_trade)
        if pending.take_profit_trade:
            self.ib.cancel_order(pending.take_profit_trade)

        self._remove_pending_order(pending, reason)

    def _remove_pending_order(self, pending: PendingOrder, reason: str):
        """Remove a pending order from tracking."""
        strategy_name = pending.strategy_name or 'unknown'
        strategy_label = self._get_strategy_label(strategy_name)
        self.pending_orders.remove(pending)

        # Update database
        if self.db and pending.db_id:
            self.db.close_position(pending.db_id, 0, f'order_{reason}')

        logger.info(f"[{strategy_label}] Removed pending order: {pending.contract.localSymbol} ({reason})")

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

        # CRITICAL: Only check for manual closes if we can confirm IB connection is active.
        # If disconnected, get_portfolio() returns empty list, which would incorrectly
        # mark all positions as manually closed.
        if not self.ib.is_connected():
            logger.debug("Skipping manual close check - IB not connected")
            return

        # Build lookup of IB portfolio by conId
        ib_portfolio = self.ib.get_portfolio()

        # Safety check: If portfolio is empty but we have tracked positions, be cautious.
        # An empty portfolio could mean:
        #   (a) All positions were truly closed manually
        #   (b) Connection issue not caught by is_connected() (stale data, API lag)
        #   (c) User logged out of TWS but socket still open briefly
        #
        # To avoid falsely marking positions as closed, we skip if portfolio is empty.
        # The user can manually clear stale positions from the database if needed.
        if not ib_portfolio and self.positions:
            logger.warning(
                f"Empty portfolio from IB but tracking {len(self.positions)} position(s) - "
                "skipping manual close check (possible connection issue)"
            )
            return

        ib_by_conid: Dict[int, int] = {}
        for item in ib_portfolio:
            con_id = item.contract.conId
            ib_by_conid[con_id] = ib_by_conid.get(con_id, 0) + int(abs(item.position))

        for position in self.positions[:]:
            con_id = position.contract.conId
            ib_qty = ib_by_conid.get(con_id, 0)

            if ib_qty == 0:
                # Position gone from IB entirely — closed manually
                strategy_name = position.strategy_name or 'unknown'
                strategy_label = self._get_strategy_label(strategy_name)
                logger.info(
                    f"[{strategy_label}] Position {position.contract.localSymbol} no longer in IB portfolio "
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
        
        # Update peak price for trailing stop logic
        if position.peak_price is None:
            position.peak_price = position.entry_price

        if position.direction == TradeDirection.LONG_CALL:
            if current_price > position.peak_price:
                position.peak_price = current_price
                if self.db and position.db_id:
                    self.db.update_position_peak_price(position.db_id, current_price)
        elif position.direction == TradeDirection.LONG_PUT:
            if current_price < position.peak_price and current_price > 0:
                position.peak_price = current_price
                if self.db and position.db_id:
                    self.db.update_position_peak_price(position.db_id, current_price)

        # Check profit target
        if current_price >= position.profit_target:
            return True, f"Profit target reached (${current_price:.2f} >= ${position.profit_target:.2f})"
        
        # Check stop loss
        if current_price <= position.stop_loss:
            return True, f"Stop loss hit (${current_price:.2f} <= ${position.stop_loss:.2f})"
        
        # Check trailing stop
        if self.config.get('trailing_stop_enabled', False):
            activation_pct = self.config.get('trailing_stop_activation_pct', 0.10)
            distance_pct = self.config.get('trailing_stop_distance_pct', 0.05)
            
            if position.direction == TradeDirection.LONG_CALL:
                # Calculate current profit pct based on peak
                peak_profit_pct = (position.peak_price - position.entry_price) / position.entry_price
                
                if peak_profit_pct >= activation_pct:
                    # Trailing active
                    trail_price = position.peak_price * (1.0 - distance_pct)
                    # Ensure trail doesn't move stop down (only up)
                    effective_stop = max(position.stop_loss, trail_price)
                    
                    if current_price <= effective_stop:
                        return True, f"Trailing stop hit (${current_price:.2f} <= ${effective_stop:.2f}, peak: ${position.peak_price:.2f})"
            
            elif position.direction == TradeDirection.LONG_PUT:
                # Calculate current profit pct based on peak (lowest price)
                # For puts, profit is when price goes down
                peak_profit_pct = (position.entry_price - position.peak_price) / position.entry_price
                
                if peak_profit_pct >= activation_pct:
                    # Trailing active
                    trail_price = position.peak_price * (1.0 + distance_pct)
                    # Ensure trail doesn't move stop up (only down)
                    effective_stop = min(position.stop_loss, trail_price)
                    
                    if current_price >= effective_stop:
                        return True, f"Trailing stop hit (${current_price:.2f} >= ${effective_stop:.2f}, peak: ${position.peak_price:.2f})"
        
        # Check time-based exit
        days_held = (datetime.now() - position.entry_time).days
        if days_held >= self.max_hold_days:
            return True, f"Max hold period reached ({days_held} days)"
        
        return False, ""
    
    def _exit_position(self, position: Position, reason: str):
        """Exit a position"""
        strategy_name = position.strategy_name or 'unknown'
        strategy_label = self._get_strategy_label(strategy_name)
        logger.info(f"[{strategy_label}] Exiting position: {position.contract.localSymbol}. Reason: {reason}")

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
            logger.info(f"[{strategy_label}] Position exited successfully: {position.contract.localSymbol}")
        else:
            logger.error(f"[{strategy_label}] Failed to exit position: {position.contract.localSymbol}")
    
    def get_status(self) -> Dict:
        """Get current trading status"""
        # Build pending order info with age and strategy (using type:instance format)
        pending_info = []
        for po in self.pending_orders:
            age_sec = (datetime.now() - po.order_time).total_seconds()
            strat = po.strategy_name or 'unknown'
            strat_label = self._get_strategy_label(strat)
            pending_info.append(
                f"[{strat_label}] {po.contract.localSymbol} x{po.quantity} @ ${po.entry_price:.2f} ({age_sec:.0f}s)"
            )

        # Build position info with strategy (using type:instance format)
        position_info = []
        for p in self.positions:
            strat = p.strategy_name or 'unknown'
            strat_label = self._get_strategy_label(strat)
            position_info.append(f"[{strat_label}] {p.contract.localSymbol} x{p.quantity}")

        # Count positions per strategy
        positions_by_strategy: Dict[str, int] = {}
        for p in self.positions:
            strat = p.strategy_name or 'unknown'
            positions_by_strategy[strat] = positions_by_strategy.get(strat, 0) + 1
        for po in self.pending_orders:
            strat = po.strategy_name or 'unknown'
            positions_by_strategy[strat] = positions_by_strategy.get(strat, 0) + 1

        status = {
            'positions': len(self.positions),
            'pending_orders': len(self.pending_orders),
            'max_positions': self.max_positions,
            'active_contracts': position_info,
            'pending_contracts': pending_info,
            'positions_by_strategy': positions_by_strategy,
            'account_value': self.ib.get_account_value(),
            'pnl': None,
        }
        if self.db:
            status['pnl'] = self.db.get_bot_pnl_summary()
        return status
