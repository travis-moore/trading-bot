#!/usr/bin/env python3
"""
Comprehensive Test Program for Trading Bot Functions
Tests with proper validation - tests FAIL if data is invalid
"""

import time
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import logging

# Import actual trading bot components
from ib_wrapper import IBWrapper
from liquidity_analyzer import LiquidityAnalyzer, Pattern
from trading_engine import TradingEngine, TradeDirection

# Setup logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# ============================================================================
# GLOBAL TEST CONFIGURATION
# ============================================================================

test_config = {
    'host': '127.0.0.1',
    'port': 4002,  # Paper trading port (Gateway), use 7497 for TWS paper
    'client_id': 999  # Use unique ID for testing
}


# ============================================================================
# TEST SUITE
# ============================================================================

class TradingAPITester:
    """Comprehensive test suite for trading bot functions"""
    
    def __init__(self, ib: IBWrapper):
        self.test_results = []
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.ib = ib
        self.test_symbols = ["AAPL", "NVDA"]
        
    def log_test(self, test_name: str, success: bool, details: str = "", skipped: bool = False):
        """Log test result"""
        if skipped:
            status = "⊘ SKIP"
            self.skipped += 1
        elif success:
            status = "✓ PASS"
            self.passed += 1
        else:
            status = "✗ FAIL"
            self.failed += 1
            
        self.test_results.append({
            "test": test_name,
            "status": status,
            "details": details
        })
        print(f"{status}: {test_name}")
        if details:
            print(f"  {details}")
    
    def run_test(self, test_name: str, test_func, can_skip: bool = False):
        """Run a single test with error handling"""
        try:
            test_func()
            self.log_test(test_name, True)
        except SkipTest as e:
            if can_skip:
                self.log_test(test_name, False, str(e), skipped=True)
            else:
                self.log_test(test_name, False, str(e))
        except Exception as e:
            self.log_test(test_name, False, str(e))
    
    # ========================================================================
    # CONNECTION TESTS
    # ========================================================================
    
    def test_connection(self):
        """Test IB connection"""
        if not self.ib or not self.ib.connected:
            raise Exception("Not connected to IB")
        print(f"  Connected to IB at {self.ib.host}:{self.ib.port}")
    
    # ========================================================================
    # STOCK PRICE TESTS
    # ========================================================================
    
    def test_get_stock_price_basic(self):
        """Test basic stock price retrieval"""
        symbol = self.test_symbols[0]
        price = self.ib.get_stock_price(symbol)
        
        if price is None:
            raise Exception(f"get_stock_price() returned None for {symbol}")
        if price <= 0:
            raise Exception(f"Invalid price: ${price} (must be > 0)")
            
        print(f"  {symbol}: ${price:.2f}")
    
    def test_get_stock_price_multiple(self):
        """Test getting prices for multiple symbols"""
        prices = {}
        for symbol in self.test_symbols:
            price = self.ib.get_stock_price(symbol)
            if price is None or price <= 0:
                raise Exception(f"Failed to get valid price for {symbol}")
            prices[symbol] = price
            print(f"  {symbol}: ${price:.2f}")
    
    # ========================================================================
    # MARKET DEPTH TESTS
    # ========================================================================
    
    def test_subscribe_market_depth(self):
        """Test subscribing to market depth"""
        symbol = self.test_symbols[0]
        ticker = self.ib.subscribe_market_depth(symbol, num_rows=10)
        
        if ticker is None:
            raise Exception(f"subscribe_market_depth() returned None")
        
        # Wait for data
        time.sleep(3)
        
        has_bids = ticker.domBids and len(ticker.domBids) > 0
        has_asks = ticker.domAsks and len(ticker.domAsks) > 0
        
        # Clean up first
        self.ib.cancel_market_depth(ticker.contract)
        
        if not has_bids or not has_asks:
            raise SkipTest(f"No depth data - requires market data subscription (Level 2)")
        
        print(f"  {len(ticker.domBids)} bid levels, {len(ticker.domAsks)} ask levels")
    
    def test_cancel_market_depth(self):
        """Test cancelling market depth subscription"""
        symbol = self.test_symbols[0]
        ticker = self.ib.subscribe_market_depth(symbol)
        
        if ticker is None:
            raise Exception("subscribe_market_depth() returned None")
        
        # This should not raise an exception
        try:
            self.ib.cancel_market_depth(ticker.contract)
            print(f"  Cancelled subscription for {symbol}")
        except Exception as e:
            raise Exception(f"cancel_market_depth() failed: {e}")
    
    # ========================================================================
    # OPTIONS TESTS
    # ========================================================================
    
    def test_get_option_chain(self):
        """Test getting option chain"""
        symbol = self.test_symbols[0]
        chain, expiries = self.ib.get_option_chain(
            symbol, 
            expiry_days_min=7, 
            expiry_days_max=45
        )
        
        if chain is None:
            raise Exception(f"get_option_chain() returned None for chain")
        if not expiries or len(expiries) == 0:
            raise Exception(f"get_option_chain() returned no expirations")
        
        print(f"  Found {len(expiries)} expirations")
        print(f"  Next expiry: {expiries[0]}")
    
    def test_find_option_contract(self):
        """Test finding specific option contract"""
        symbol = self.test_symbols[0]
        
        # Get chain first
        chain, expiries = self.ib.get_option_chain(symbol)
        if not expiries:
            raise Exception("No expirations available")
        
        if not chain or not chain.strikes:
            raise Exception("No strikes available in chain")
        
        # Get current price for strike selection
        current_price = self.ib.get_stock_price(symbol)
        if not current_price or current_price <= 0:
            raise Exception("Could not get current price for strike selection")
        
        # Find nearest available strike (2% OTM)
        target_strike = current_price * 1.02
        available_strikes = sorted(chain.strikes)
        
        # Find closest strike to target
        strike = min(available_strikes, key=lambda x: abs(x - target_strike))
        
        print(f"  Target strike: ${target_strike:.2f}, Using: ${strike}")
        
        contract = self.ib.find_option_contract(symbol, strike, expiries[0], 'C')
        
        if contract is None:
            raise Exception(f"find_option_contract() returned None")
        
        # CRITICAL: Check if contract was actually qualified by IB
        if not contract.localSymbol:
            raise Exception(f"Contract not qualified - strike ${strike} may not exist")
        
        print(f"  Contract: {contract.localSymbol}")
        print(f"  Strike: ${contract.strike}, Expiry: {contract.lastTradeDateOrContractMonth}")
    
    def test_get_option_price(self):
        """Test getting option price"""
        symbol = self.test_symbols[0]
        
        # Find a valid contract first
        chain, expiries = self.ib.get_option_chain(symbol)
        if not expiries:
            raise Exception("No expirations")
        
        if not chain or not chain.strikes:
            raise Exception("No strikes available")
        
        current_price = self.ib.get_stock_price(symbol)
        if not current_price:
            raise Exception("Could not get current price")
        
        # Find nearest available strike
        target_strike = current_price * 1.02
        available_strikes = sorted(chain.strikes)
        strike = min(available_strikes, key=lambda x: abs(x - target_strike))
            
        contract = self.ib.find_option_contract(symbol, strike, expiries[0], 'C')
        
        if not contract or not contract.localSymbol:
            raise Exception("Could not find valid contract")
        
        # Get price
        price_data = self.ib.get_option_price(contract)
        
        if price_data is None:
            raise Exception("get_option_price() returned None")
        
        bid, ask, last = price_data
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else last
        
        # At least one price should be valid for a real option
        if bid == 0 and ask == 0 and last == 0:
            raise Exception(f"All prices are zero - option may not exist or is illiquid")
        
        print(f"  Bid: ${bid:.2f}, Ask: ${ask:.2f}, Last: ${last:.2f}")
    
    # ========================================================================
    # ACCOUNT TESTS
    # ========================================================================
    
    def test_get_account_value(self):
        """Test getting account value"""
        value = self.ib.get_account_value('NetLiquidation')
        
        if value is None:
            raise Exception("get_account_value() returned None")
        
        if value <= 0:
            raise Exception(f"Invalid account value: ${value}")
        
        is_paper = value > 900000  # Paper accounts usually ~$1M
        account_type = "Paper" if is_paper else "Live"
        print(f"  Net Liquidation: ${value:,.2f} ({account_type})")
    
    def test_get_positions(self):
        """Test getting positions"""
        positions = self.ib.get_positions()
        
        # Note: Empty list is valid (no positions)
        print(f"  Current positions: {len(positions)}")
        
        for pos in positions[:3]:
            print(f"    {pos.contract.symbol}: {pos.position} @ ${pos.avgCost:.2f}")
    
    def test_get_portfolio(self):
        """Test getting portfolio"""
        portfolio = self.ib.get_portfolio()
        
        # Note: Empty list is valid
        print(f"  Portfolio items: {len(portfolio)}")
    
    # ========================================================================
    # LIQUIDITY ANALYZER TESTS
    # ========================================================================
    
    def test_liquidity_analyzer(self):
        """Test liquidity analyzer"""
        symbol = self.test_symbols[1]
        
        # Subscribe to depth
        ticker = self.ib.subscribe_market_depth(symbol, num_rows=10)
        if not ticker:
            raise Exception("Could not subscribe")
        
        time.sleep(3)
        
        # Create analyzer
        config = {
            'liquidity_threshold': 1000,
            'zone_proximity': 0.10,
            'imbalance_threshold': 0.6,
            'num_levels': 10
        }
        analyzer = LiquidityAnalyzer(config)
        
        # Analyze
        analysis = analyzer.analyze_book(ticker)
        
        # Clean up
        self.ib.cancel_market_depth(ticker.contract)
        
        # Check if we got depth data
        has_data = (ticker.domBids and len(ticker.domBids) > 0 and
                   ticker.domAsks and len(ticker.domAsks) > 0)
        
        if not has_data:
            raise SkipTest("No market depth data - requires Level 2 subscription")
        
        print(f"  Support zones: {len(analysis['support'])}")
        print(f"  Resistance zones: {len(analysis['resistance'])}")
        print(f"  Order imbalance: {analysis['imbalance']:.2%}")
    
    def test_pattern_detection(self):
        """Test pattern detection"""
        symbol = self.test_symbols[1]
        
        current_price = self.ib.get_stock_price(symbol)
        if not current_price:
            raise Exception("Could not get price")
        
        ticker = self.ib.subscribe_market_depth(symbol, num_rows=10)
        if not ticker:
            raise Exception("Could not subscribe")
        
        time.sleep(3)
        
        config = {
            'liquidity_threshold': 1000,
            'zone_proximity': 0.10,
            'imbalance_threshold': 0.6,
            'num_levels': 10
        }
        analyzer = LiquidityAnalyzer(config)
        
        signal = analyzer.detect_pattern(ticker, current_price)
        
        # Clean up
        self.ib.cancel_market_depth(ticker.contract)
        
        if not signal:
            raise Exception("detect_pattern() returned None")
        
        # Even without depth data, should return consolidation pattern
        print(f"  Pattern: {signal.pattern.value}")
        print(f"  Confidence: {signal.confidence:.2%}")
    
    # ========================================================================
    # TRADING ENGINE TESTS
    # ========================================================================
    
    def test_trading_engine_init(self):
        """Test trading engine initialization"""
        analyzer_config = {
            'liquidity_threshold': 1000,
            'zone_proximity': 0.10,
            'imbalance_threshold': 0.6,
            'num_levels': 10
        }
        analyzer = LiquidityAnalyzer(analyzer_config)
        
        engine_config = {
            'max_position_size': 1000,
            'max_positions': 2,
            'position_size_pct': 0.01,
            'profit_target_pct': 0.50,
            'stop_loss_pct': 0.30,
            'max_hold_days': 30,
            'rejection_support_confidence': 0.65,
            'breakout_up_confidence': 0.70,
            'rejection_resistance_confidence': 0.65,
            'breakout_down_confidence': 0.70,
            'min_dte': 14,
            'max_dte': 45,
            'call_strike_pct': 1.02,
            'put_strike_pct': 0.98
        }
        
        engine = TradingEngine(self.ib, analyzer, engine_config)
        
        if not engine.rules or len(engine.rules) == 0:
            raise Exception("Trading engine has no rules configured")
        
        print(f"  Max positions: {engine.max_positions}")
        print(f"  Trading rules: {len(engine.rules)}")
    
    def test_position_sizing(self):
        """Test position size calculation"""
        analyzer_config = {'liquidity_threshold': 1000, 'zone_proximity': 0.10, 
                          'imbalance_threshold': 0.6, 'num_levels': 10}
        analyzer = LiquidityAnalyzer(analyzer_config)
        
        engine_config = {
            'max_position_size': 1000,
            'max_positions': 2,
            'position_size_pct': 0.01,
            'profit_target_pct': 0.50,
            'stop_loss_pct': 0.30,
            'max_hold_days': 30,
            'min_dte': 14,
            'max_dte': 45,
            'call_strike_pct': 1.02,
            'put_strike_pct': 0.98
        }
        
        engine = TradingEngine(self.ib, analyzer, engine_config)
        
        test_price = 2.50
        quantity = engine.calculate_position_size(test_price)
        total_cost = quantity * test_price * 100
        
        if quantity <= 0:
            raise Exception(f"Invalid position size: {quantity}")
        
        if total_cost > engine.max_position_size:
            raise Exception(f"Position ${total_cost:.2f} exceeds max ${engine.max_position_size}")
        
        print(f"  Option @ ${test_price} → {quantity} contracts (${total_cost:.2f})")
    
    def test_option_selection(self):
        """Test option selection"""
        symbol = self.test_symbols[0]
        
        analyzer_config = {'liquidity_threshold': 1000, 'zone_proximity': 0.10, 
                          'imbalance_threshold': 0.6, 'num_levels': 10}
        analyzer = LiquidityAnalyzer(analyzer_config)
        
        engine_config = {
            'max_position_size': 1000,
            'max_positions': 2,
            'position_size_pct': 0.01,
            'profit_target_pct': 0.50,
            'stop_loss_pct': 0.30,
            'max_hold_days': 30,
            'min_dte': 14,
            'max_dte': 45,
            'call_strike_pct': 1.02,
            'put_strike_pct': 0.98
        }
        
        engine = TradingEngine(self.ib, analyzer, engine_config)
        
        current_price = self.ib.get_stock_price(symbol)
        if not current_price:
            raise Exception("Could not get price")
        
        contract = engine.select_option(symbol, TradeDirection.LONG_CALL, current_price)
        
        if not contract:
            raise Exception("select_option() returned None")
        
        if not contract.localSymbol:
            raise Exception("Option contract not qualified - may not exist")
        
        print(f"  Selected: {contract.localSymbol}")
        print(f"  Strike: ${contract.strike}, Right: {contract.right}")
    
    # ========================================================================
    # MASTER TEST RUNNER
    # ========================================================================
    
    def run_all_tests(self):
        """Run all tests"""
        print("=" * 80)
        print("TRADING BOT COMPREHENSIVE TEST SUITE")
        print("=" * 80)
        print()
        
        # Connection
        print("--- CONNECTION ---")
        self.run_test("IB Connection", self.test_connection)
        
        if not self.ib or not self.ib.connected:
            print("\n❌ Cannot proceed without connection!")
            return
        
        # Stock Prices
        print("\n--- STOCK PRICES ---")
        self.run_test("get_stock_price", self.test_get_stock_price_basic)
        self.run_test("get_stock_price (multiple)", self.test_get_stock_price_multiple)
        
        # Market Depth (can skip if no subscription)
        print("\n--- MARKET DEPTH ---")
        # self.run_test("subscribe_market_depth", self.test_subscribe_market_depth, can_skip=True)
        # self.run_test("cancel_market_depth", self.test_cancel_market_depth)
        
        # Options
        print("\n--- OPTIONS ---")
        self.run_test("get_option_chain", self.test_get_option_chain)
        self.run_test("find_option_contract", self.test_find_option_contract)
        self.run_test("get_option_price", self.test_get_option_price)
        
        # Account
        print("\n--- ACCOUNT ---")
        self.run_test("get_account_value", self.test_get_account_value)
        self.run_test("get_positions", self.test_get_positions)
        self.run_test("get_portfolio", self.test_get_portfolio)
        
        # Liquidity Analyzer (can skip if no depth data)
        print("\n--- LIQUIDITY ANALYZER ---")
        self.run_test("analyze_order_book", self.test_liquidity_analyzer, can_skip=True)
        self.run_test("detect_pattern", self.test_pattern_detection)
        
        # Trading Engine
        print("\n--- TRADING ENGINE ---")
        self.run_test("engine_initialization", self.test_trading_engine_init)
        self.run_test("position_sizing", self.test_position_sizing)
        self.run_test("option_selection", self.test_option_selection)
        
        # Summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary"""
        print()
        print("=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)
        total = self.passed + self.failed + self.skipped
        print(f"Total: {total} | Passed: {self.passed} | Failed: {self.failed} | Skipped: {self.skipped}")
        if self.passed + self.failed > 0:
            print(f"Success Rate: {(self.passed / (self.passed + self.failed) * 100):.1f}%")
        print("=" * 80)
        
        if self.failed > 0:
            print("\n❌ Failed Tests:")
            for result in self.test_results:
                if "✗" in result["status"]:
                    print(f"  • {result['test']}")
                    if result['details']:
                        print(f"    {result['details']}")
        
        if self.skipped > 0:
            print("\n⊘ Skipped Tests (require market data subscription):")
            for result in self.test_results:
                if "⊘" in result["status"]:
                    print(f"  • {result['test']}")


# ============================================================================
# CUSTOM EXCEPTION FOR SKIPPABLE TESTS
# ============================================================================

class SkipTest(Exception):
    """Exception to indicate a test should be skipped"""
    pass


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("TRADING BOT TEST SUITE")
    print("=" * 80)
    print()
    print("⚠️  IMPORTANT: Make sure TWS or IB Gateway is running!")
    print("   Paper trading ports: 4002 (Gateway) or 7497 (TWS)")
    print()
    
    # Determine port
    if len(sys.argv) > 1 and sys.argv[1] == "--live":
        print("⚠️  WARNING: Using LIVE trading port!")
        port = 7496
        confirm = input("Type 'YES' to test on LIVE account: ")
        if confirm != "YES":
            print("Aborted.")
            sys.exit(1)
    else:
        port = test_config['port']
        print(f"Using paper trading (port {port})")
    
    # Connect
    print(f"\nConnecting to IB...")
    ib = IBWrapper(
        host=test_config['host'],
        port=port,
        client_id=test_config['client_id']
    )
    
    if not ib.connect():
        print("❌ Connection failed!")
        print("\nTroubleshooting:")
        print("  • Is TWS/Gateway running?")
        print("  • Are API settings enabled?")
        print("  • Is the port correct?")
        sys.exit(1)
    
    print("✓ Connected!\n")
    
    try:
        # Run tests
        tester = TradingAPITester(ib)
        tester.run_all_tests()
        exit_code = 0 if tester.failed == 0 else 1
        
    finally:
        print("\nDisconnecting...")
        ib.disconnect()
        print("✓ Done")
    
    sys.exit(exit_code)
