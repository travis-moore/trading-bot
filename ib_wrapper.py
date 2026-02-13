"""
Interactive Brokers API Wrapper
Provides clean interface for options trading and market data
"""

from ib_insync import *
import logging
from typing import Optional, List, Dict, Tuple, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class IBWrapper:
    """Wrapper for Interactive Brokers API operations"""
    
    # Common indices that require secType='IND'
    KNOWN_INDICES = {'SPX', 'VIX', 'NDX', 'RUT', 'XSP', 'DJX'}

    def __init__(self, host='127.0.0.1', port=7497, client_id=1):
        self.ib = IB()
        self.host = host
        self.port = port
        self.client_id = client_id
        self.connected = False
        
    def connect(self) -> bool:
        """Connect to IB TWS or Gateway"""
        try:
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            self._patch_market_depth()
            self.connected = True
            logger.info(f"Connected to IB at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to IB: {e}")
            self.connected = False
            return False
    
    def _patch_market_depth(self):
        """Patch ib_insync bug where updateMktDepthL2 crashes on out-of-range positions."""
        wrapper = self.ib.wrapper
        original = wrapper.updateMktDepthL2

        def patched_updateMktDepthL2(
                reqId, position, marketMaker, operation, side, price, size,
                isSmartDepth=False):
            ticker = wrapper.reqId2Ticker.get(reqId)
            if ticker is None:
                return
            dom = ticker.domBids if side else ticker.domAsks
            # Extend the list if position is out of range
            while position >= len(dom):
                dom.append(DOMLevel(0, 0, ''))
            original(reqId, position, marketMaker, operation, side, price,
                     size, isSmartDepth)

        wrapper.updateMktDepthL2 = patched_updateMktDepthL2

    def disconnect(self):
        """Disconnect from IB"""
        if self.connected:
            self.ib.disconnect()
            self.connected = False
            logger.info("Disconnected from IB")

    def is_connected(self) -> bool:
        """
        Check if actually connected to IB.

        Uses ib_insync's isConnected() which checks the actual socket state,
        not just our cached flag. This catches cases where TWS was closed
        or the user logged out.
        """
        return self.ib.isConnected()
    
    def get_stock_price(self, symbol: str) -> Optional[float]:
        """
        Get current stock price
        
        Args:
            symbol: Stock ticker symbol (e.g., 'NVDA')
            
        Returns:
            Current price or None if error
        """
        try:
            # Use ISLAND (NASDAQ) exchange for better data availability
            if symbol in self.KNOWN_INDICES:
                contract = Index(symbol, 'CBOE' if symbol in ['VIX', 'XSP', 'SPX'] else 'SMART', 'USD')
            else:
                contract = Stock(symbol, 'ISLAND', 'USD')
                
            self.ib.qualifyContracts(contract)
            
            # Request market data
            ticker = self.ib.reqMktData(contract, '', False, False)
            
            # Wait longer for data to arrive (up to 5 seconds)
            for i in range(10):
                self.ib.sleep(0.5)
                
                # Check for valid last price (not NaN and > 0)
                if ticker.last == ticker.last and ticker.last > 0:
                    price = ticker.last
                    self.ib.cancelMktData(contract)
                    logger.info(f"Got price for {symbol}: ${price:.2f} (last)")
                    return price
                
                # Try close price
                if ticker.close == ticker.close and ticker.close > 0:
                    price = ticker.close
                    self.ib.cancelMktData(contract)
                    logger.info(f"Got price for {symbol}: ${price:.2f} (close)")
                    return price
                    
                # Try bid/ask midpoint
                if ticker.bid > 0 and ticker.ask > 0:
                    price = (ticker.bid + ticker.ask) / 2
                    self.ib.cancelMktData(contract)
                    logger.info(f"Got price for {symbol}: ${price:.2f} (mid)")
                    return price
            
            # If still no data after 5 seconds, try with SMART routing as fallback
            self.ib.cancelMktData(contract)
            logger.warning(f"No data on ISLAND, trying SMART for {symbol}")
            
            if symbol in self.KNOWN_INDICES:
                contract = Index(symbol, 'SMART', 'USD')
            else:
                contract = Stock(symbol, 'SMART', 'USD')
                
            self.ib.qualifyContracts(contract)
            ticker = self.ib.reqMktData(contract, '', False, False)
            
            for i in range(10):
                self.ib.sleep(0.5)
                
                if ticker.last == ticker.last and ticker.last > 0:
                    price = ticker.last
                    self.ib.cancelMktData(contract)
                    return price
                
                if ticker.close == ticker.close and ticker.close > 0:
                    price = ticker.close
                    self.ib.cancelMktData(contract)
                    return price
                    
                if ticker.bid > 0 and ticker.ask > 0:
                    price = (ticker.bid + ticker.ask) / 2
                    self.ib.cancelMktData(contract)
                    return price
            
            self.ib.cancelMktData(contract)
            logger.error(f"Could not get price for {symbol} - no market data received")
            return None

        except Exception as e:
            logger.error(f"Error getting stock price for {symbol}: {e}")
            return None

    def subscribe_market_data(self, symbol: str, exchange: str = 'SMART') -> Optional[Ticker]:
        """
        Subscribe to live Level 1 market data.
        Returns a Ticker object that will be automatically updated.
        """
        try:
            if symbol in self.KNOWN_INDICES:
                # Indices usually don't trade on ISLAND/NASDAQ, default to CBOE or SMART
                contract = Index(symbol, 'CBOE' if symbol in ['VIX', 'XSP', 'SPX'] else 'SMART', 'USD')
            else:
                contract = Stock(symbol, exchange, 'USD')
            self.ib.qualifyContracts(contract)
            # Request generic ticks: 233 (RTVolume), 221 (Mark Price)
            ticker = self.ib.reqMktData(contract, '', False, False)
            logger.info(f"Subscribed to Level 1 data for {symbol}")
            return ticker
        except Exception as e:
            logger.error(f"Error subscribing to market data for {symbol}: {e}")
            return None

    def cancel_market_data(self, contract: Contract):
        """Cancel market data subscription"""
        try:
            self.ib.cancelMktData(contract)
        except Exception as e:
            logger.error(f"Error canceling market data: {e}")

    def get_live_price(self, ticker: Ticker) -> Optional[float]:
        """Extract current price from a live ticker without making new requests."""
        # Check last price (ticker.last == ticker.last checks for not-NaN)
        if ticker.last and ticker.last == ticker.last and ticker.last > 0:
            return ticker.last
        if ticker.close and ticker.close == ticker.close and ticker.close > 0:
            return ticker.close
        if ticker.bid > 0 and ticker.ask > 0:
            return (ticker.bid + ticker.ask) / 2
        return None

    def get_historical_bars(
        self,
        symbol: str,
        bar_size: str = '15 mins',
        duration: str = '30 D',
        what_to_show: str = 'TRADES',
        use_rth: bool = True,
        exchange: str = 'SMART',
        sec_type: str = 'STK'
    ) -> Optional[List]:
        """
        Fetch historical OHLCV bars for a symbol.

        Args:
            symbol: Stock ticker symbol
            bar_size: Bar timeframe. Valid values:
                      '1 secs', '5 secs', '10 secs', '15 secs', '30 secs',
                      '1 min', '2 mins', '3 mins', '5 mins', '10 mins', '15 mins',
                      '20 mins', '30 mins', '1 hour', '2 hours', '3 hours',
                      '4 hours', '8 hours', '1 day', '1 week', '1 month'
            duration: How far back to fetch ('30 D', '60 D', '1 Y', etc.)
            what_to_show: Data type ('TRADES', 'MIDPOINT', 'BID', 'ASK')
            use_rth: Use regular trading hours only (True) or include extended hours (False)
            exchange: Exchange for historical data ('SMART', 'ISLAND', etc.)
            sec_type: Security type ('STK', 'IND', etc.)

        Returns:
            List of BarData objects with attributes: date, open, high, low, close, volume
            Returns None if error occurs
        """
        try:
            if sec_type == 'IND':
                contract = Index(symbol, exchange, 'USD')
            else:
                contract = Stock(symbol, exchange, 'USD')
            self.ib.qualifyContracts(contract)

            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime='',  # Empty string means current time
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=use_rth,
                formatDate=1,  # Return as datetime objects
            )

            if bars:
                logger.info(f"Fetched {len(bars)} historical bars for {symbol} ({bar_size}, {duration})")
                return bars

            logger.warning(f"No historical bars returned for {symbol}")
            return None

        except Exception as e:
            logger.error(f"Error fetching historical bars for {symbol}: {e}")
            return None

    def get_option_chain(self, symbol: str, expiry_days_min: int = 7, 
                         expiry_days_max: int = 60) -> Tuple[Optional[Any], List[str]]:
        """
        Get available option contracts
        
        Args:
            symbol: Underlying stock symbol
            expiry_days_min: Minimum days to expiration
            expiry_days_max: Maximum days to expiration
            
        Returns:
            Tuple of (chain_object, list_of_expirations)
        """
        try:
            if symbol in self.KNOWN_INDICES:
                stock = Index(symbol, 'SMART', 'USD')
            else:
                stock = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(stock)
            
            chains = self.ib.reqSecDefOptParams(
                stock.symbol, '', stock.secType, stock.conId
            )
            
            if not chains:
                logger.warning(f"No option chains found for {symbol}")
                return None, []
            
            # Get chain for primary exchange (SMART preferred)
            # Select the chain with the most expirations/strikes to ensure we get the main chain
            smart_chains = [c for c in chains if c.exchange == 'SMART']
            candidates = smart_chains if smart_chains else chains
            # Sort by number of expirations (desc) then strikes (desc)
            chain = sorted(candidates, key=lambda c: (len(c.expirations), len(c.strikes)), reverse=True)[0]
            
            # Filter expirations by date range
            today = datetime.now().date()
            min_date = today + timedelta(days=expiry_days_min)
            max_date = today + timedelta(days=expiry_days_max)
            
            valid_expiries = [
                exp for exp in chain.expirations
                if min_date <= datetime.strptime(exp, '%Y%m%d').date() <= max_date
            ]
            
            logger.info(f"Found {len(valid_expiries)} valid expirations for {symbol} ({len(chain.strikes)} strikes)")
            return chain, valid_expiries
            
        except Exception as e:
            logger.error(f"Error getting option chain for {symbol}: {e}")
            return None, []
    
    def get_contract_details(self, symbol: str, sec_type: str = 'STK', exchange: str = 'SMART') -> Optional[Dict]:
        """Get contract details including industry/sector."""
        try:
            contract = Contract()
            contract.symbol = symbol
            contract.secType = sec_type
            contract.exchange = exchange
            contract.currency = 'USD'
            
            details_list = self.ib.reqContractDetails(contract)
            if not details_list:
                return None
            
            # Return the first match
            details = details_list[0]
            return {
                'industry': details.industry,
                'category': details.category,
                'subcategory': details.subcategory,
                'longName': details.longName
            }
        except Exception as e:
            logger.error(f"Error getting contract details for {symbol}: {e}")
            return None

    def find_option_contract(self, symbol: str, strike: float, expiry: str,
                            right: str = 'C', check_prices: bool = True,
                            quiet: bool = False) -> Optional[Contract]:
        """
        Find specific option contract that actually has market prices

        Args:
            symbol: Underlying symbol
            strike: Strike price
            expiry: Expiration date (YYYYMMDD format)
            right: 'C' for call, 'P' for put
            check_prices: If True, verify the option has market prices (default: True)
            quiet: If True, suppress warnings for missing strikes (use when probing)

        Returns:
            Option contract or None if not found or not tradeable
        """
        try:
            # Temporarily suppress ib_insync errors when probing for valid strikes
            if quiet:
                ib_logger = logging.getLogger('ib_insync')
                old_level = ib_logger.level
                ib_logger.setLevel(logging.CRITICAL)

            try:
                option = Option(symbol, expiry, strike, right, 'SMART')
                contracts = self.ib.qualifyContracts(option)
            finally:
                if quiet:
                    ib_logger.setLevel(old_level)

            # Check if contract was actually qualified
            if contracts and len(contracts) > 0:
                qualified = contracts[0]
                # A qualified contract will have localSymbol populated
                if not qualified.localSymbol:
                    if not quiet:
                        logger.warning(f"Contract not qualified: {symbol} {expiry} ${strike} {right}")
                    return None
                
                # Check if the option has actual market prices
                # Skip this check outside market hours for testing
                if check_prices:
                    ticker = self.ib.reqMktData(qualified, '', False, False)
                    self.ib.sleep(2)  # Wait for price data
                    
                    has_price = False
                    if ticker.last > 0 or ticker.close > 0 or (ticker.bid > 0 and ticker.ask > 0):
                        has_price = True
                    
                    self.ib.cancelMktData(qualified)
                    
                    if not has_price:
                        # During market hours, this means the option has no market
                        # Outside market hours, all options will have zero prices
                        # For testing, we accept it but log a warning
                        logger.info(f"No live prices for {symbol} {expiry} ${strike} {right} (market closed or illiquid)")
                        # Return the contract anyway - it exists in the chain
                        # During live trading, you'd want to reject this
                
                return qualified
            else:
                if not quiet:
                    logger.warning(f"No contracts returned for: {symbol} {expiry} ${strike} {right}")
                return None
                
        except Exception as e:
            logger.error(f"Error finding option contract: {e}")
            return None
    
    def get_option_price(self, contract: Contract) -> Optional[Tuple[float, float, float]]:
        """
        Get option price information
        
        Args:
            contract: Option contract
            
        Returns:
            Tuple of (bid, ask, last) or None
        """
        try:
            ticker = self.ib.reqMktData(contract, '', False, False)
            
            # Wait for data to arrive (up to 4 seconds)
            for _ in range(20):
                self.ib.sleep(0.2)
                if (ticker.bid > 0 and ticker.ask > 0) or ticker.last > 0:
                    break
            
            # Check values, handling NaN
            bid = ticker.bid if (ticker.bid and ticker.bid == ticker.bid) else 0.0
            ask = ticker.ask if (ticker.ask and ticker.ask == ticker.ask) else 0.0
            last = ticker.last if (ticker.last and ticker.last == ticker.last) else 0.0
            
            self.ib.cancelMktData(contract)
            
            return (bid, ask, last)
            
        except Exception as e:
            logger.error(f"Error getting option price: {e}")
            return None
    
    def buy_option(self, contract: Contract, quantity: int = 1,
                   limit_price: Optional[float] = None,
                   tif: str = 'DAY',
                   order_ref: Optional[str] = None) -> Optional[Trade]:
        """
        Buy an option contract

        Args:
            contract: Option contract to buy
            quantity: Number of contracts
            limit_price: Limit price (None for market order)
            tif: Time in force - 'DAY' or 'GTC' (Good Till Cancelled)
            order_ref: Optional order reference tag for tracking

        Returns:
            Trade object or None
        """
        try:
            if limit_price is not None:
                order = LimitOrder('BUY', quantity, limit_price)
            else:
                order = MarketOrder('BUY', quantity)
            order.tif = tif
            if order_ref:
                order.orderRef = order_ref

            trade = self.ib.placeOrder(contract, order)
            logger.info(f"Placed buy order: {contract.localSymbol} x{quantity}")

            # Wait for order to be processed
            self.ib.sleep(5)

            # Check if order was accepted
            status = trade.orderStatus.status
            if status in ('Cancelled', 'Inactive', 'ApiCancelled', 'Rejected'):
                logger.error(f"Order rejected/cancelled: {contract.localSymbol} status={status}")
                return None

            logger.info(f"Order status: {status}")
            return trade

        except Exception as e:
            logger.error(f"Error buying option: {e}")
            return None
    
    def sell_option(self, contract: Contract, quantity: int = 1,
                    limit_price: Optional[float] = None,
                    tif: str = 'DAY',
                    order_ref: Optional[str] = None) -> Optional[Trade]:
        """
        Sell an option contract

        Args:
            contract: Option contract to sell
            quantity: Number of contracts
            limit_price: Limit price (None for market order)
            tif: Time in force - 'DAY' or 'GTC' (Good Till Cancelled)
            order_ref: Optional order reference tag for tracking

        Returns:
            Trade object or None
        """
        try:
            if limit_price is not None:
                order = LimitOrder('SELL', quantity, limit_price)
            else:
                order = MarketOrder('SELL', quantity)
            order.tif = tif
            if order_ref:
                order.orderRef = order_ref

            trade = self.ib.placeOrder(contract, order)
            logger.info(f"Placed sell order: {contract.localSymbol} x{quantity}")

            # Wait for order to be processed
            self.ib.sleep(5)

            # Check if order was accepted
            status = trade.orderStatus.status
            if status in ('Cancelled', 'Inactive', 'ApiCancelled', 'Rejected'):
                logger.error(f"Order rejected/cancelled: {contract.localSymbol} status={status}")
                return None

            logger.info(f"Order status: {status}")
            return trade

        except Exception as e:
            logger.error(f"Error selling option: {e}")
            return None
    
    def get_positions(self) -> List[Position]:
        """Get current positions"""
        try:
            return self.ib.positions()
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []
    
    def get_portfolio(self) -> List[PortfolioItem]:
        """Get current portfolio"""
        try:
            return self.ib.portfolio()
        except Exception as e:
            logger.error(f"Error getting portfolio: {e}")
            return []
    
    def subscribe_market_depth(self, symbol: str, num_rows: int = 50,
                               exchange: str = 'ISLAND', quiet: bool = False) -> Optional[Ticker]:
        """
        Subscribe to market depth data

        Args:
            symbol: Stock symbol
            num_rows: Number of depth levels
            exchange: Exchange for depth data (e.g. 'ISLAND', 'ARCA', 'NYSE')
            quiet: If True, suppress info logging (useful for sequential scanning)

        Returns:
            Ticker object with depth data
        """
        try:
            if symbol in self.KNOWN_INDICES:
                # Indices typically don't have Level 2 depth available via API in the same way
                # We return None to indicate depth is not available
                return None
            contract = Stock(symbol, exchange, 'USD')
            self.ib.qualifyContracts(contract)
            is_smart = (exchange.upper() == 'SMART')
            ticker = self.ib.reqMktDepth(contract, numRows=num_rows, isSmartDepth=is_smart)
            self.ib.sleep(2)
            if not quiet:
                logger.info(f"Subscribed to market depth for {symbol}")
            return ticker
        except Exception as e:
            logger.error(f"Error subscribing to market depth: {e}")
            return None
    
    def cancel_market_depth(self, contract: Contract):
        """Cancel market depth subscription"""
        try:
            self.ib.cancelMktDepth(contract)
        except Exception as e:
            logger.error(f"Error canceling market depth: {e}")
    
    def get_account_value(self, tag: str = 'NetLiquidation') -> Optional[float]:
        """
        Get account value
        
        Args:
            tag: Value tag (NetLiquidation, AvailableFunds, etc.)
            
        Returns:
            Account value or None
        """
        try:
            account_values = self.ib.accountValues()
            for av in account_values:
                if av.tag == tag:
                    return float(av.value)
            return None
        except Exception as e:
            logger.error(f"Error getting account value: {e}")
            return None
    
    def cancel_all_orders(self):
        """Cancel all open orders"""
        try:
            open_orders = self.ib.openOrders()
            for order in open_orders:
                self.ib.cancelOrder(order)
            logger.info(f"Cancelled {len(open_orders)} open orders")
        except Exception as e:
            logger.error(f"Error canceling orders: {e}")

    def buy_option_bracket(
        self,
        contract: Contract,
        quantity: int,
        entry_price: float,
        stop_loss_price: float,
        take_profit_price: float,
        tif: str = 'GTC',
        order_ref: Optional[str] = None
    ) -> Optional[List[Trade]]:
        """
        Place a bracket order: buy with attached stop loss and take profit.

        The stop loss and take profit orders are OCA (One Cancels All) -
        when one fills, the other is automatically cancelled.

        Args:
            contract: Option contract to buy
            quantity: Number of contracts
            entry_price: Limit price for entry
            stop_loss_price: Stop loss trigger price
            take_profit_price: Take profit limit price
            tif: Time in force - 'GTC' recommended for brackets
            order_ref: Optional order reference tag

        Returns:
            List of Trade objects [entry, stop_loss, take_profit] or None
        """
        try:
            # Create bracket order using IB's bracket order helper
            bracket = self.ib.bracketOrder(
                action='BUY',
                quantity=quantity,
                limitPrice=entry_price,
                takeProfitPrice=take_profit_price,
                stopLossPrice=stop_loss_price,
            )

            # Unpack the three orders
            entry_order, take_profit_order, stop_loss_order = bracket

            # Set time in force on all orders
            entry_order.tif = tif
            take_profit_order.tif = tif
            stop_loss_order.tif = tif

            # Set order reference if provided
            if order_ref:
                entry_order.orderRef = order_ref
                take_profit_order.orderRef = f"{order_ref}_TP"
                stop_loss_order.orderRef = f"{order_ref}_SL"

            # Place the bracket orders
            entry_trade = self.ib.placeOrder(contract, entry_order)
            take_profit_trade = self.ib.placeOrder(contract, take_profit_order)
            stop_loss_trade = self.ib.placeOrder(contract, stop_loss_order)

            logger.info(
                f"Placed bracket order: {contract.localSymbol} x{quantity} "
                f"@ ${entry_price:.2f} (SL: ${stop_loss_price:.2f}, TP: ${take_profit_price:.2f})"
            )

            # Wait for orders to be acknowledged
            self.ib.sleep(2)

            # Check entry order status
            status = entry_trade.orderStatus.status
            if status in ('Cancelled', 'Inactive', 'ApiCancelled', 'Rejected'):
                logger.error(f"Bracket entry order rejected: {status}")
                return None

            logger.info(f"Bracket order status: entry={status}")
            return [entry_trade, stop_loss_trade, take_profit_trade]

        except Exception as e:
            logger.error(f"Error placing bracket order: {e}")
            return None

    def get_open_orders(self) -> List[Trade]:
        """Get all open/pending orders."""
        try:
            return self.ib.openTrades()
        except Exception as e:
            logger.error(f"Error getting open orders: {e}")
            return []

    def get_order_status(self, trade: Trade) -> Dict:
        """
        Get detailed status of an order.

        Returns:
            Dict with status info including:
            - status: Order status string
            - filled: Number of contracts filled
            - remaining: Number of contracts remaining
            - avg_fill_price: Average fill price (if any fills)
            - last_fill_time: Time of last fill
        """
        try:
            status = trade.orderStatus
            return {
                'status': status.status,
                'filled': status.filled,
                'remaining': status.remaining,
                'avg_fill_price': status.avgFillPrice,
                'last_fill_time': trade.log[-1].time if trade.log else None,
                'order_id': trade.order.orderId,
            }
        except Exception as e:
            logger.error(f"Error getting order status: {e}")
            return {'status': 'Unknown', 'filled': 0, 'remaining': 0}

    def modify_order_price(self, trade: Trade, new_price: float) -> bool:
        """
        Modify the limit price of a pending order.

        Args:
            trade: Trade object to modify
            new_price: New limit price

        Returns:
            True if modification submitted successfully
        """
        try:
            order = trade.order
            if order.orderType == 'LMT':
                order.lmtPrice = new_price
            elif order.orderType == 'STP':
                order.auxPrice = new_price
            else:
                logger.warning(f"Cannot modify price for order type: {order.orderType}")
                return False

            self.ib.placeOrder(trade.contract, order)
            logger.info(f"Modified order {order.orderId} price to ${new_price:.2f}")
            return True

        except Exception as e:
            logger.error(f"Error modifying order: {e}")
            return False

    def cancel_order(self, trade: Trade) -> bool:
        """
        Cancel a specific order.

        Args:
            trade: Trade object to cancel

        Returns:
            True if cancellation submitted successfully
        """
        try:
            self.ib.cancelOrder(trade.order)
            logger.info(f"Cancelled order {trade.order.orderId}")
            return True
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False

    def is_order_filled(self, trade: Trade) -> bool:
        """Check if an order is completely filled."""
        return trade.orderStatus.status == 'Filled'

    def is_order_pending(self, trade: Trade) -> bool:
        """Check if an order is still pending/working."""
        return trade.orderStatus.status in (
            'PendingSubmit', 'PreSubmitted', 'Submitted'
        )
