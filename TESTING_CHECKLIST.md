# Trading Bot Testing Checklist

## Phase 1: Basic Connectivity & Setup ✓
- [x] IB Gateway/TWS connection works
  - Tested port: 7497 (TWS-Paper/Real & Gateway-Real) or 4002 (Gateway-Paper)
  - Connection successful: Yes
  - Date tested: 18/1/2026

## Phase 2: IB Wrapper Functions (ib_wrapper.py)

### Connection Management
- [x] `connect()` - Establishes connection successfully
  ```python
  from ib_wrapper import IBWrapper
  ib = IBWrapper(host='127.0.0.1', port=4002)
  ib.connect()  # Should return True
  ```
  - Works: Yes
  - Notes: ___________

- [x] `disconnect()` - Closes connection cleanly
  ```python
  ib.disconnect()
  ```
  - Works: Yes
  - Notes: ___________

### Market Data Functions
- [x] `get_stock_price()` - Returns current price
  ```python
  price = ib.get_stock_price('APPL')
  print(f"APPL price: ${price}")
  ```
  - Works: Yes
  - Price retrieved: $258.28
  - Notes: ___________

- [x] `subscribe_market_depth()` - Gets order book data
  ```python
  ticker = ib.subscribe_market_depth('APPL', num_rows=10)
  import time
  time.sleep(3)
  print(f"Bids: {len(ticker.domBids)}")
  print(f"Asks: {len(ticker.domAsks)}")
  ```
  - Works: Yes
  - Depth data received: Yes
  - Number of bid levels: 30
  - Number of ask levels: 30
  - Notes: ___________
  - **If fails:** Check if you have market data subscription

- [x] `cancel_market_depth()` - Unsubscribes from depth
  ```python
  ib.cancel_market_depth(ticker.contract)
  ```
  - Works: Yes
  - Notes: ___________

### Option Chain Functions
- [x] `get_option_chain()` - Retrieves available options
  ```python
  chain, expiries = ib.get_option_chain('APPL', expiry_days_min=7, expiry_days_max=45)
  print(f"Found {len(expiries)} expirations")
  print(f"First expiry: {expiries[0] if expiries else 'None'}")
  ```
  - Works: Yes
  - Number of expirations found: 7
  - Notes: ___________

- [x] `find_option_contract()` - Finds specific option
  ```python
  # Use an expiry from the previous test
  expiry = "20260209"  # YYYYMMDD format
  strike = 262.5
  contract = ib.find_option_contract('APPL', strike, expiry, 'C')
  print(f"Contract: {contract.localSymbol if contract else 'Not found'}")
  ```
  - Works: Yes
  - Contract found: Yes
  - Symbol: AAPL  260209C00262500
  - Notes: ___________

- [x] `get_option_price()` - Gets option pricing
  ```python
  # Using contract from previous test
  if contract:
      bid, ask, last = ib.get_option_price(contract)
      print(f"Bid: ${bid}, Ask: ${ask}, Last: ${last}")
  ```
  - Works: Yes
  - Bid: $1.97
  - Ask: $2.01
  - Last: $1.88
  - Notes:

### Account Functions
- [x] `get_account_value()` - Returns account balance
  ```python
  account_value = ib.get_account_value('NetLiquidation')
  print(f"Account value: ${account_value:,.2f}")
  ```
  - Works: Yes
  - Account value: Y154,863,979.64
  - Is this paper account? Yes
  - Notes: ___________

- [x] `get_positions()` - Shows current positions
  ```python
  positions = ib.get_positions()
  print(f"Number of positions: {len(positions)}")
  for pos in positions:
      print(f"  {pos.contract.symbol}: {pos.position} @ ${pos.avgCost}")
  ```
  - Works: Yes
  - Number of positions: 7
  - Notes: ___________

- [x] `get_portfolio()` - Shows portfolio items
  ```python
  portfolio = ib.get_portfolio()
  print(f"Portfolio items: {len(portfolio)}")
  ```
  - Works: Yes
  - Number of items: 7
  - Notes: ___________

### Trading Functions (TEST IN PAPER ONLY!)
⚠️ **CRITICAL: Ensure you're connected to paper trading before testing these!**

- [x] **VERIFY PAPER TRADING FIRST**
  ```python
  account_value = ib.get_account_value()
  print(f"Account value: ${account_value:,.2f}")
  # Paper accounts typically show ~$1,000,000
  # If this shows your real balance, STOP!
  ```
  - Account value indicates paper: Yes
  - Safe to proceed: Yes

- [x] `buy_option()` - Places buy order
  ```python
  # Find a cheap option first
  contract = ib.find_option_contract('AAPL', 180.0, '20250221', 'C')
  if contract:
      bid, ask, last = ib.get_option_price(contract)
      mid_price = (bid + ask) / 2 if bid > 0 and ask > 0 else last
      print(f"Placing order for ${mid_price:.2f}")
      trade = ib.buy_option(contract, quantity=1, limit_price=mid_price)
      print(f"Order placed: {trade is not None}")
  ```
  - Works: Yes
  - Order placed: Yes
  - Order status: Submitted
  - Notes: ___________

- [x] `sell_option()` - Places sell order
  ```python
  # Sell the option we just bought
  if contract and trade:
      trade = ib.sell_option(contract, quantity=1, limit_price=mid_price)
      print(f"Sell order placed: {trade is not None}")
  ```
  - Works: Yes
  - Order placed: Yes
  - Order status: Submitted
  - Notes: ___________

- [x] `cancel_sell_order()` - Cancels last sell order
  ```python
  ib.cancel_sell_order()
  ```
  - Works: Yes
  - Notes: ___________

## Phase 3: Liquidity Analyzer (liquidity_analyzer.py)

- [x] **Test with mock data** (no IB connection needed)
  ```python
  python test_bot.py
  ```
  - All tests pass: Yes
  - Notes: ___________

- [x] **Test with real market depth data**
  ```python
  from ib_wrapper import IBWrapper
  from liquidity_analyzer import LiquidityAnalyzer
  
  ib = IBWrapper(host='127.0.0.1', port=4002)
  ib.connect()
  
  config = {
      'liquidity_threshold': 1000,
      'zone_proximity': 0.10,
      'imbalance_threshold': 0.6,
      'num_levels': 10
  }
  
  analyzer = LiquidityAnalyzer(config)
  ticker = ib.subscribe_market_depth('APPL', num_rows=10)
  
  import time
  time.sleep(3)
  
  analysis = analyzer.analyze_book(ticker)
  print(f"Support zones: {len(analysis['support'])}")
  print(f"Resistance zones: {len(analysis['resistance'])}")
  print(f"Imbalance: {analysis['imbalance']:.2%}")
  ```
  - Works: Yes
  - Support zones found: 3
  - Resistance zones found: 6
  - Imbalance: -16.31%
  - Notes: ___________

- [ ] **Pattern detection**
  ```python
  price = ib.get_stock_price('APPL')
  signal = analyzer.detect_pattern(ticker, price)
  print(f"Pattern: {signal.pattern.value}")
  print(f"Confidence: {signal.confidence:.2%}")
  ```
  - Works: Yes
  - Pattern detected: consolidation
  - Confidence: 50.00%
  - Notes: ___________

## Phase 4: Trading Engine (trading_engine.py)

- [x] **Initialize engine**
  ```python
  from trading_engine import TradingEngine
  
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
  
  engine = TradingEngine(ib, analyzer, engine_config)
  print("Engine initialized")
  ```
  - Works: Yes
  - Notes: ___________

- [ ] **Signal evaluation**
  ```python
  direction = engine.evaluate_signal(signal)
  print(f"Recommended direction: {direction}")
  ```
  - Works: Yes/No
  - Direction recommended: ___________
  - Notes: ___________

- [x] **Position sizing calculation**
  ```python
  test_option_price = 2.50
  quantity = engine.calculate_position_size(test_option_price)
  print(f"Position size: {quantity} contracts")
  print(f"Total cost: ${quantity * test_option_price * 100:.2f}")
  ```
  - Works: Yes
  - Calculated quantity: 2
  - Total cost: $500
  - Reasonable for account size: Yes/No
  - Notes: ___________

- [x] **Option selection**
  ```python
  from trading_engine import TradeDirection
  price = ib.get_stock_price('APPL')
  contract = engine.select_option('APPL', TradeDirection.LONG_CALL, price)
  if contract:
      print(f"Selected: {contract.localSymbol}")
  ```
  - Works: Yes
  - Contract selected: AAPL  260220C00270000
  - Strike makes sense: Yes
  - Expiration makes sense: Yes/No
  - Notes: ___________

- [ ] **Full trade entry (PAPER ONLY!)**
  ⚠️ **Verify paper trading before running this!**
  ```python
  # Only if you want to test actual order placement
  success = engine.enter_trade('APPL', TradeDirection.LONG_CALL, signal)
  print(f"Trade entered: {success}")
  ```
  - Works: Yes/No
  - Trade entered: Yes/No
  - Position tracked: Yes/No
  - Stop loss set: $___________
  - Profit target set: $___________
  - Notes: ___________

- [ ] **Position exit checking**
  ```python
  # After entering a trade above
  engine.check_exits()
  print(f"Positions remaining: {len(engine.positions)}")
  ```
  - Works: Yes/No
  - Exits detected properly: Yes/No
  - Notes: ___________

## Phase 5: Configuration (config.yaml)

- [ ] Load and validate configuration
  ```python
  import yaml
  with open('config.yaml', 'r') as f:
      config = yaml.safe_load(f)
  
  print(f"Symbols: {config['symbols']}")
  print(f"Port: {config['ib_connection']['port']}")
  print(f"Max positions: {config['risk_management']['max_positions']}")
  ```
  - Loads successfully: Yes/No
  - Symbols configured: ___________
  - Port correct for paper: Yes/No
  - Position limits reasonable: Yes/No
  - Notes: ___________

- [ ] Verify all safety settings
  ```yaml
  safety:
    require_manual_approval: _____ (should be true for testing)
    max_daily_loss: _____ (reasonable?)
    trading_hours_only: _____ (true recommended)
    emergency_stop: _____ (should be false to run)
  ```
  - Manual approval enabled: Yes/No
  - Max daily loss set: $___________
  - Trading hours only: Yes/No
  - Notes: ___________

## Phase 6: Main Program (main.py)

- [ ] **Run example usage script**
  ```bash
  python example_usage.py
  ```
  - Runs without errors: Yes/No
  - Shows analysis: Yes/No
  - Notes: ___________

- [ ] **Dry run main program (short test)**
  - Edit config.yaml: Set `scan_interval: 30` (30 seconds for testing)
  - Set `require_manual_approval: true`
  ```bash
  python main.py
  ```
  - Starts successfully: Yes/No
  - Subscribes to depth: Yes/No
  - Scans for signals: Yes/No
  - Stops cleanly with Ctrl+C: Yes/No
  - Logs written to trading_bot.log: Yes/No
  - Notes: ___________

- [ ] **Check status output**
  - Wait for 10 scans to see status printout
  - Status shows correct info: Yes/No
  - Account value matches: Yes/No
  - Position count correct: Yes/No
  - Notes: ___________

## Phase 7: End-to-End Paper Trading Test

⚠️ **This is a live test - bot will actually trade in paper account!**

- [ ] **Pre-flight checks**
  - [ ] Connected to paper trading (port 4002 or paper login)
  - [ ] Account value confirms paper (~$1,000,000)
  - [ ] config.yaml has `enable_paper_trading: true`
  - [ ] Position sizes are small (max_position_size: 500)
  - [ ] Max positions limited (max_positions: 1 or 2)
  - [ ] Manual approval enabled for first test
  
- [ ] **Run bot for 1 hour**
  ```bash
  python main.py
  ```
  - Start time: ___________
  - End time: ___________
  - Total scans: ___________
  - Signals detected: ___________
  - Trades attempted: ___________
  - Trades entered: ___________
  - Trades exited: ___________
  - Errors encountered: ___________

- [ ] **Review logs**
  ```bash
  tail -100 trading_bot.log
  ```
  - Logs are clear and informative: Yes/No
  - No unexpected errors: Yes/No
  - Pattern detections logged: Yes/No
  - Trade entries logged: Yes/No
  - Notes: ___________

- [ ] **Verify trades in TWS/Gateway**
  - Check order log in TWS
  - Orders placed correctly: Yes/No
  - Prices reasonable: Yes/No
  - Stop losses set: Yes/No
  - Notes: ___________

## Phase 8: Strategy Validation (Run for 1-2 weeks)

- [ ] **Week 1 results**
  - Total trades: ___________
  - Win rate: ___________%
  - Avg profit per win: $___________
  - Avg loss per loss: $___________
  - Largest win: $___________
  - Largest loss: $___________
  - Net P/L: $___________
  - Notes: ___________

- [ ] **Review patterns**
  - Which patterns worked best? ___________
  - Which patterns had false signals? ___________
  - Any consistent issues? ___________

- [ ] **Adjust parameters**
  - Confidence thresholds adjusted: Yes/No
  - Position sizing adjusted: Yes/No
  - Exit rules adjusted: Yes/No
  - Changes made: ___________

## Phase 9: Pre-Live Checklist

⚠️ **Complete this before switching to live trading!**

- [ ] Minimum 2 weeks paper trading completed
- [ ] Strategy shows consistent edge
- [ ] All systems working reliably
- [ ] Understand all code behavior
- [ ] Comfortable with position sizes
- [ ] Emergency procedures documented
- [ ] Backup plan if bot fails
- [ ] Can monitor bot remotely
- [ ] Alerts set up for errors
- [ ] Ready to start with minimal capital

## Phase 10: Live Trading (When Ready)

- [ ] **Final safety checks**
  - [ ] Change port to live (7497 for TWS/Gateway live)
  - [ ] Log into LIVE account
  - [ ] Verify real account balance shows
  - [ ] Reduce position sizes for first week
  - [ ] Keep manual approval ON initially
  - [ ] Set max_positions to 1 initially
  - [ ] Set max_daily_loss to small amount

- [ ] **First live trade**
  - Date: ___________
  - Symbol: ___________
  - Entry price: $___________
  - Exit price: $___________
  - P/L: $___________
  - Notes: ___________

---

## Common Issues & Solutions

### "Failed to connect to IB"
- Check TWS/Gateway is running
- Verify correct port in config
- Enable API in TWS settings
- Check "Download open orders on connection"

### "No market depth data"
- Need market data subscription (~$15/mo)
- Or use free Cboe/IEX (limited depth)
- Check subscriptions in Account Management

### "Could not get option price"
- Option may be illiquid
- Try different strike/expiration
- Adjust min_dte/max_dte

### "Module not found"
- Run: `pip install -r requirements.txt`

### Bot enters no trades
- Lower confidence thresholds
- Check if patterns being detected
- Verify signal evaluation logic
- Check max_positions limit

---

## Notes & Observations

[Use this space for general notes, issues encountered, improvements needed, etc.]

___________________________________________________________________________

___________________________________________________________________________

___________________________________________________________________________

___________________________________________________________________________

___________________________________________________________________________

---

**Testing Progress:**
- Phase 1 Complete: ___/___
- Phase 2 Complete: ___/___  
- Phase 3 Complete: ___/___
- Phase 4 Complete: ___/___
- Phase 5 Complete: ___/___
- Phase 6 Complete: ___/___
- Phase 7 Complete: ___/___
- Phase 8 Complete: ___/___
- Phase 9 Complete: ___/___
- Phase 10 Started: ___/___

**Overall Status:** ☐ Testing | ☐ Paper Trading | ☐ Live Trading
