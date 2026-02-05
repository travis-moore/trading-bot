#!/usr/bin/env python3
"""
Swing Trading Bot - Main Program
Automated options trading based on order book liquidity analysis
"""

import yaml
import logging
import time
import signal
import sys
import threading
import select
from datetime import datetime, time as dt_time
from typing import Dict
from zoneinfo import ZoneInfo

from ib_insync import Contract
from ib_wrapper import IBWrapper
from liquidity_analyzer import LiquidityAnalyzer, Pattern
from trading_engine import TradingEngine, TradeDirection, Position
from trade_db import TradeDatabase

# Try to import strategies module
try:
    from strategies import StrategyManager
    STRATEGIES_AVAILABLE = True
except ImportError:
    STRATEGIES_AVAILABLE = False
    StrategyManager = None


class SwingTradingBot:
    """
    Main trading bot coordinator
    """
    
    def __init__(self, config_path: str = 'config.yaml'):
        """Initialize bot with configuration"""
        self.config = self._load_config(config_path)
        self.running = False
        
        # Setup logging
        self._setup_logging()
        
        # Initialize components
        self.ib = None
        self.analyzer = None
        self.engine = None
        self.db = None
        self.strategy_manager = None  # StrategyManager instance if available
        self.tickers = {}  # symbol -> ticker mapping
        self.price_tickers = {}  # symbol -> ticker mapping (Level 1 Price)

        # Command processing
        self._command_thread = None
        self._pending_command = None
        self._command_lock = threading.Lock()
        
        # Statistics
        self.stats = {
            'scans': 0,
            'signals_detected': 0,
            'trades_entered': 0,
            'trades_exited': 0,
            'start_time': None
        }
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from YAML file"""
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    
    def _setup_logging(self):
        """Setup logging configuration"""
        log_level = self.config['operation'].get('log_level', 'INFO')
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

        # File handler - captures everything including verbose ib_insync messages
        file_handler = logging.FileHandler('trading_bot.log')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(log_format))

        # Console handler - filters out noisy ib_insync messages
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level))
        console_handler.setFormatter(logging.Formatter(log_format))

        # Filter to exclude ib_insync verbose messages from console
        class IbInsyncFilter(logging.Filter):
            def filter(self, record):
                return not record.name.startswith('ib_insync')

        console_handler.addFilter(IbInsyncFilter())

        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

        self.logger = logging.getLogger(__name__)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info("Shutdown signal received, stopping bot...")
        self.running = False
    
    def initialize(self) -> bool:
        """Initialize all components"""
        self.logger.info("Initializing trading bot...")
        
        try:
            # Initialize IB connection
            ib_config = self.config['ib_connection']
            self.ib = IBWrapper(
                host=ib_config['host'],
                port=ib_config['port'],
                client_id=ib_config['client_id']
            )
            
            if not self.ib.connect():
                self.logger.error("Failed to connect to Interactive Brokers")
                return False
            
            # Initialize liquidity analyzer
            self.analyzer = LiquidityAnalyzer(self.config['liquidity_analysis'])
            
            # Initialize database
            db_path = self.config.get('database', {}).get('path', 'trading_bot.db')
            self.db = TradeDatabase(db_path)

            # Initialize strategy manager if available
            if STRATEGIES_AVAILABLE and StrategyManager is not None:
                self.strategy_manager = StrategyManager(self.config)
                loaded = self.strategy_manager.load_all_configured()
                self.logger.info(f"Loaded {loaded} trading strategies")

                # Initialize budgets for strategies that have them configured
                self._initialize_strategy_budgets()

                # Wire up IB wrapper and database to strategies for historical data
                self._wire_strategy_dependencies()

            # Initialize trading engine
            engine_config = {
                **self.config['risk_management'],
                **self.config['trading_rules'],
                **self.config['option_selection'],
                **self.config.get('order_management', {}),
            }
            self.engine = TradingEngine(
                self.ib, self.analyzer, engine_config,
                trade_db=self.db,
                strategy_manager=self.strategy_manager
            )

            # Reconcile DB positions with IB account state
            self._reconcile_positions()
            
            # Subscribe to market depth for all symbols
            # Subscribe to market data for all symbols
            for symbol in self.config['symbols']:
                # Level 2 (Depth)
                ticker = self.ib.subscribe_market_depth(symbol)
                if ticker:
                    self.tickers[symbol] = ticker
                    self.logger.info(f"Subscribed to market depth for {symbol}")
                else:
                    self.logger.warning(f"Failed to subscribe to {symbol}")
                    self.logger.warning(f"Failed to subscribe to depth for {symbol}")
                
                # Level 1 (Price)
                price_ticker = self.ib.subscribe_market_data(symbol)
                if price_ticker:
                    self.price_tickers[symbol] = price_ticker
            
            if not self.tickers:
                self.logger.error("No market depth subscriptions active")
                return False
            
            self.logger.info("Initialization complete")
            return True
            
        except Exception as e:
            self.logger.error(f"Initialization failed: {e}", exc_info=True)
            return False
    
    def _initialize_strategy_budgets(self):
        """Initialize budgets for strategies that have them configured."""
        if not self.db or not self.strategy_manager:
            return

        strategies_config = self.config.get('strategies', {})
        initialized = 0

        for instance_name, strat_config in strategies_config.items():
            budget = strat_config.get('budget')
            if budget is not None and budget > 0:
                # Check if this strategy already has budget state
                existing = self.db.get_strategy_budget(instance_name)
                if existing:
                    # Budget already exists - don't reset drawdown
                    # Just update the budget cap if it changed
                    if existing['budget'] != budget:
                        self.db.set_strategy_budget(instance_name, budget, reset_drawdown=False)
                        self.logger.info(
                            f"Updated budget for '{instance_name}': "
                            f"${existing['budget']:.2f} -> ${budget:.2f}"
                        )
                    else:
                        self.logger.info(
                            f"Strategy '{instance_name}' budget: ${budget:.2f} "
                            f"(available: ${existing['available']:.2f})"
                        )
                else:
                    # New strategy - check if there's trade history to calculate from
                    self.db.recalculate_budget_from_history(instance_name, budget)
                    state = self.db.get_strategy_budget(instance_name)
                    if state:
                        self.logger.info(
                            f"Initialized budget for '{instance_name}': ${budget:.2f} "
                            f"(available: ${state['available']:.2f})"
                        )
                initialized += 1

        if initialized > 0:
            self.logger.info(f"Initialized budgets for {initialized} strategies")

    def _wire_strategy_dependencies(self):
        """Wire up IB wrapper and trade database to strategies for historical data."""
        if not self.strategy_manager:
            return

        wired = 0
        for strategy in self.strategy_manager.get_all_strategies().values():
            # Check if strategy has the setter methods (e.g., SwingTradingStrategy)
            if hasattr(strategy, 'set_ib_wrapper') and self.ib:
                strategy.set_ib_wrapper(self.ib)
                wired += 1
            if hasattr(strategy, 'set_trade_db') and self.db:
                strategy.set_trade_db(self.db)

        if wired > 0:
            self.logger.info(f"Wired IB/DB dependencies to {wired} strategies for historical data")

    def _reconcile_positions(self):
        """Reconcile DB positions with IB account state on startup."""
        db_positions = self.db.get_open_positions()
        if not db_positions:
            self.logger.info("Reconciliation: no open positions in database")
            return

        self.logger.info(f"Reconciliation: {len(db_positions)} position(s) in database")

        # Build lookup of IB portfolio by conId
        ib_portfolio = self.ib.get_portfolio()
        ib_by_conid = {}
        for item in ib_portfolio:
            ib_by_conid[item.contract.conId] = item

        restored = 0
        closed = 0

        for row in db_positions:
            con_id = row['con_id']
            ib_item = ib_by_conid.get(con_id)
            ib_qty = int(abs(ib_item.position)) if ib_item else 0

            if ib_qty > 0:
                # Position still exists in IB — reconstruct and restore
                contract = Contract(conId=con_id)
                self.ib.ib.qualifyContracts(contract)

                actual_qty = min(ib_qty, row['quantity'])
                if ib_qty < row['quantity']:
                    self.logger.warning(
                        f"  {row['local_symbol']}: partial — DB={row['quantity']}, IB={ib_qty}"
                    )
                    self.db.update_position_quantity(row['id'], actual_qty)

                # Handle pending_fill that actually filled
                if row['status'] == 'pending_fill':
                    self.db.update_position_status(row['id'], 'open')

                # Get strategy (default to swing_trading for older records)
                strategy = row['strategy'] if 'strategy' in row.keys() else 'swing_trading'

                position = Position(
                    contract=contract,
                    entry_price=row['entry_price'],
                    entry_time=datetime.fromisoformat(row['entry_time']),
                    quantity=actual_qty,
                    direction=TradeDirection(row['direction']),
                    stop_loss=row['stop_loss'],
                    profit_target=row['profit_target'],
                    pattern=Pattern(row['pattern']),
                    db_id=row['id'],
                    order_ref=row['order_ref'],
                    strategy_name=strategy,
                )
                self.engine.positions.append(position)
                restored += 1
                self.logger.info(f"  Restored: {row['local_symbol']} x{actual_qty}")
            else:
                # Position gone from IB — closed externally or expired
                self.db.close_position(
                    position_id=row['id'],
                    exit_price=0,
                    exit_reason='reconciliation_not_found',
                )
                closed += 1
                self.logger.warning(f"  Closed (not in IB): {row['local_symbol']}")

        self.logger.info(
            f"Reconciliation complete: {restored} restored, {closed} closed"
        )

    def _is_market_hours(self) -> bool:
        """Check if current time is during NYSE market hours (US Eastern)"""
        if not self.config['safety']['trading_hours_only']:
            return True

        now_et = datetime.now(ZoneInfo("America/New_York")).time()
        market_open = dt_time(9, 30)
        market_close = dt_time(16, 0)

        return market_open <= now_et <= market_close
    
    def scan_for_signals(self):
        """Scan all symbols for trading signals"""
        self.stats['scans'] += 1

        for symbol, ticker in self.tickers.items():
            try:
                # Get current price
                current_price = self.ib.get_stock_price(symbol)
                if current_price is None:
                price_ticker = self.price_tickers.get(symbol)
                current_price = self.ib.get_live_price(price_ticker) if price_ticker else None
                if not current_price:
                    continue

                # Analyze order book for support/resistance (for logging)
                analysis = self.analyzer.analyze_book(ticker)
                nearest = self.analyzer.get_nearest_zones(current_price, analysis)

                # Format support/resistance for logging
                support_str = f"${nearest['support'].price:.2f}" if nearest['support'] else "none"
                resistance_str = f"${nearest['resistance'].price:.2f}" if nearest['resistance'] else "none"

                # Use strategy manager if available, otherwise fall back to legacy analyzer
                if self.strategy_manager:
                    # Get signals from all enabled strategy instances
                    context = {
                        'symbol': symbol,
                        'positions': self.engine.positions,
                        'account_value': self.ib.get_account_value(),
                    }
                    signals = self.strategy_manager.analyze_all(ticker, current_price, context)

                    for signal in signals:
                        # Get strategy instance info from signal metadata
                        strategy_name = signal.metadata.get('strategy', 'unknown')
                        strategy_type = signal.metadata.get('strategy_type', strategy_name)
                        strategy_label = f"{strategy_type}:{strategy_name}" if strategy_type != strategy_name else strategy_name

                        # Log the signal with strategy instance info
                        imbalance = signal.metadata.get('imbalance', 0)
                        imbalance_dir = "^" if imbalance > 0 else "v" if imbalance < 0 else "-"
                        self.logger.info(
                            f"[{strategy_label}] {symbol}: ${current_price:.2f} - {signal.pattern_name} "
                            f"(confidence: {signal.confidence:.2f}) | "
                            f"support: {support_str}, resistance: {resistance_str}, "
                            f"imbalance: {imbalance:+.2f} {imbalance_dir}"
                        )
                        self.stats['signals_detected'] += 1

                        # Evaluate if signal meets trading rules
                        direction = self.engine.evaluate_signal(signal)

                        if direction and direction != TradeDirection.NO_TRADE:
                            self._handle_trade_signal(symbol, direction, signal, current_price)
                else:
                    # Legacy path: use analyzer directly
                    signal = self.analyzer.detect_pattern(ticker, current_price)

                    if signal is None:
                        continue

                    # Log non-consolidation patterns with support/resistance info
                    if signal.pattern != Pattern.CONSOLIDATION:
                        imbalance = signal.imbalance if signal.imbalance is not None else 0
                        imbalance_dir = "^" if imbalance > 0 else "v" if imbalance < 0 else "-"
                        self.logger.info(
                            f"{symbol}: ${current_price:.2f} - {signal.pattern.value} "
                            f"(confidence: {signal.confidence:.2f}) | "
                            f"support: {support_str}, resistance: {resistance_str}, "
                            f"imbalance: {imbalance:+.2f} {imbalance_dir}"
                        )
                        self.stats['signals_detected'] += 1

                        # Evaluate if signal meets trading rules
                        direction = self.engine.evaluate_signal(signal)

                        if direction and direction != TradeDirection.NO_TRADE:
                            self._handle_trade_signal(symbol, direction, signal, current_price)

            except Exception as e:
                self.logger.error(f"Error scanning {symbol}: {e}", exc_info=True)
    
    def _handle_trade_signal(self, symbol: str, direction: TradeDirection,
                            signal, current_price: float):
        """Handle a valid trade signal"""
        # Check safety conditions
        if self.config['safety']['emergency_stop']:
            self.logger.warning("Emergency stop active, skipping trade")
            return
        
        if not self._is_market_hours():
            self.logger.info("Outside market hours, skipping trade")
            return
        
        # Check if manual approval required
        if self.config['safety']['require_manual_approval']:
            self.logger.info(
                f"Trade signal: {symbol} {direction.value} @ ${current_price:.2f}"
            )
            approval = input("Approve trade? (yes/no): ").lower()
            if approval != 'yes':
                self.logger.info("Trade not approved")
                return
        
        # Enter trade
        self.logger.info(f"Attempting to enter trade: {symbol} {direction.value}")
        
        success = self.engine.enter_trade(symbol, direction, signal)
        
        if success:
            self.stats['trades_entered'] += 1
            self.logger.info("Trade entered successfully")
        else:
            self.logger.warning("Failed to enter trade")
    
    def check_positions(self):
        """Check and manage open positions"""
        if not self.engine.positions:
            return
        
        self.logger.debug(f"Checking {len(self.engine.positions)} open positions")
        
        initial_count = len(self.engine.positions)
        self.engine.check_exits()
        final_count = len(self.engine.positions)
        
        if final_count < initial_count:
            self.stats['trades_exited'] += (initial_count - final_count)
    
    def print_status(self):
        """Print current bot status"""
        status = self.engine.get_status()
        uptime = datetime.now() - self.stats['start_time']

        self.logger.info("=" * 60)
        self.logger.info("BOT STATUS")
        self.logger.info("=" * 60)
        self.logger.info(f"Uptime: {uptime}")
        self.logger.info(f"Scans completed: {self.stats['scans']}")
        self.logger.info(f"Signals detected: {self.stats['signals_detected']}")
        self.logger.info(f"Trades entered: {self.stats['trades_entered']}")
        self.logger.info(f"Trades exited: {self.stats['trades_exited']}")
        self.logger.info(
            f"Positions: {status['positions']} open, "
            f"{status['pending_orders']} pending"
        )

        # Show positions by strategy
        positions_by_strat = status.get('positions_by_strategy', {})
        if positions_by_strat:
            strat_summary = ", ".join(f"{k}: {v}" for k, v in positions_by_strat.items())
            self.logger.info(f"By strategy: {strat_summary}")

        if status['pending_contracts']:
            self.logger.info(f"Pending: {', '.join(status['pending_contracts'])}")

        if status['active_contracts']:
            self.logger.info(f"Open: {', '.join(status['active_contracts'])}")

        if status['account_value']:
            self.logger.info(f"Account value: ${status['account_value']:,.2f}")

        pnl = status.get('pnl')
        if pnl and pnl['total_trades'] > 0:
            self.logger.info(
                f"Bot P&L: ${pnl['total_pnl']:+,.2f} "
                f"({pnl['wins']}W / {pnl['losses']}L over {pnl['total_trades']} trades)"
            )

        self.logger.info("=" * 60)

    # =========================================================================
    # Interactive Commands
    # =========================================================================

    def _start_command_thread(self):
        """Start background thread to read user commands."""
        self._command_thread = threading.Thread(target=self._command_reader, daemon=True)
        self._command_thread.start()
        self.logger.info("Command processor started. Type /help for available commands.")

    def _command_reader(self):
        """Background thread that reads commands from stdin."""
        while self.running:
            try:
                # Use select on Unix, simple input on Windows
                if sys.platform == 'win32':
                    import msvcrt
                    if msvcrt.kbhit():
                        line = input()
                        with self._command_lock:
                            self._pending_command = line.strip()
                    else:
                        time.sleep(0.1)
                else:
                    # Unix - use select for non-blocking input
                    readable, _, _ = select.select([sys.stdin], [], [], 0.1)
                    if readable:
                        line = sys.stdin.readline()
                        if line:
                            with self._command_lock:
                                self._pending_command = line.strip()
            except Exception:
                time.sleep(0.1)

    def _process_pending_command(self):
        """Process any pending command from the user."""
        with self._command_lock:
            if self._pending_command is None:
                return
            command = self._pending_command
            self._pending_command = None

        if not command:
            return

        self.logger.info(f"Processing command: {command}")

        if command == '/help':
            self._cmd_help()
        elif command == '/status':
            self.print_status()
        elif command == '/strategies':
            self._cmd_strategies()
        elif command == '/reload':
            self._cmd_reload()
        elif command.startswith('/reload '):
            strategy_name = command.split(' ', 1)[1].strip()
            self._cmd_reload(strategy_name)
        elif command.startswith('/enable '):
            strategy_name = command.split(' ', 1)[1].strip()
            self._cmd_enable(strategy_name)
        elif command.startswith('/disable '):
            strategy_name = command.split(' ', 1)[1].strip()
            self._cmd_disable(strategy_name)
        elif command == '/discover':
            self._cmd_discover()
        elif command == '/pnl':
            self._cmd_pnl()
        elif command == '/budgets':
            self._cmd_budgets()
        elif command == '/metrics':
            self._cmd_metrics()
        elif command.startswith('/metrics '):
            args = command.split(' ', 1)[1].strip()
            self._cmd_metrics(args)
        elif command == '/trades':
            self._cmd_trades()
        elif command.startswith('/trades '):
            args = command.split(' ', 1)[1].strip()
            self._cmd_trades(args)
        elif command == '/export':
            self._cmd_export()
        elif command.startswith('/export '):
            args = command.split(' ', 1)[1].strip()
            self._cmd_export(args)
        elif command == '/quit' or command == '/stop':
            self.logger.info("Stop command received")
            self.running = False
        else:
            self.logger.warning(f"Unknown command: {command}. Type /help for available commands.")

    def _cmd_help(self):
        """Display available commands."""
        help_text = """
Available commands:
  /help              - Show this help message
  /status            - Show bot status
  /strategies        - List all strategies and their status
  /reload            - Reload all strategies from disk
  /reload <name>     - Reload a specific strategy
  /enable <name>     - Enable a strategy
  /disable <name>    - Disable a strategy
  /discover          - Discover and load new strategy files
  /pnl               - Show P&L breakdown by strategy
  /budgets           - Show strategy budget status
  /metrics [symbol]  - Show detailed performance metrics
  /trades [filters]  - Query trade history (e.g., /trades NVDA winners)
  /export [type]     - Export trades to CSV (trades, report)
  /quit or /stop     - Stop the bot gracefully
"""
        print(help_text)

    def _cmd_strategies(self):
        """List all strategies and their status."""
        if not self.strategy_manager:
            self.logger.warning("Strategy manager not available")
            return

        status = self.strategy_manager.get_status()
        print("\n" + "=" * 60)
        print("TRADING STRATEGIES")
        print("=" * 60)
        print(f"Loaded: {status['loaded']}  |  Enabled: {status['enabled']}")
        print("-" * 60)

        for name, info in status['strategies'].items():
            state = "✓ ENABLED" if info['enabled'] else "✗ disabled"
            print(f"  {name:20} v{info['version']:8} {state}")
            print(f"    {info['description']}")

        # Show unloaded strategies
        unloaded = self.strategy_manager.get_unloaded_strategies()
        if unloaded:
            print("-" * 60)
            print("Available but not loaded:")
            for name in unloaded:
                print(f"  {name}")

        print("=" * 60 + "\n")

    def _cmd_reload(self, strategy_name=None):
        """Reload strategies from disk."""
        if not self.strategy_manager:
            self.logger.warning("Strategy manager not available")
            return

        if strategy_name:
            success = self.strategy_manager.reload_strategy(strategy_name)
            if success:
                self.logger.info(f"Successfully reloaded strategy: {strategy_name}")
            else:
                self.logger.error(f"Failed to reload strategy: {strategy_name}")
        else:
            results = self.strategy_manager.reload_all()
            successes = sum(1 for v in results.values() if v)
            failures = sum(1 for v in results.values() if not v)
            self.logger.info(f"Reloaded strategies: {successes} succeeded, {failures} failed")

    def _cmd_enable(self, strategy_name: str):
        """Enable a strategy."""
        if not self.strategy_manager:
            self.logger.warning("Strategy manager not available")
            return

        if strategy_name not in self.strategy_manager.get_all_strategies():
            # Try to load it first
            if self.strategy_manager.load_strategy(strategy_name):
                self.logger.info(f"Loaded and enabled strategy: {strategy_name}")
            else:
                self.logger.error(f"Strategy not found: {strategy_name}")
            return

        self.strategy_manager.enable_strategy(strategy_name)

    def _cmd_disable(self, strategy_name: str):
        """Disable a strategy."""
        if not self.strategy_manager:
            self.logger.warning("Strategy manager not available")
            return

        self.strategy_manager.disable_strategy(strategy_name)

    def _cmd_discover(self):
        """Discover and optionally load new strategy files."""
        if not self.strategy_manager:
            self.logger.warning("Strategy manager not available")
            return

        available = self.strategy_manager.discover_strategies()
        loaded = set(self.strategy_manager.get_all_strategies().keys())
        new_strategies = available - loaded

        if not new_strategies:
            self.logger.info("No new strategy files found")
            return

        print(f"\nFound {len(new_strategies)} new strategy file(s):")
        for name in new_strategies:
            print(f"  - {name}")

        # Load any that are enabled in config
        loaded_count = self.strategy_manager.load_new_strategies()
        if loaded_count > 0:
            self.logger.info(f"Auto-loaded {loaded_count} new strategies (enabled in config)")
        else:
            print("\nTo load a strategy, use: /enable <name>")

    def _cmd_pnl(self):
        """Show P&L breakdown by strategy."""
        if not self.db:
            self.logger.warning("Database not available")
            return

        pnl_by_strategy = self.db.get_pnl_by_strategy()

        print("\n" + "=" * 70)
        print("P&L BY STRATEGY")
        print("=" * 70)

        if not pnl_by_strategy:
            print("  No completed trades yet")
        else:
            print(f"  {'Strategy':<20} {'Trades':>8} {'W/L':>10} {'Total P&L':>12} {'Avg P&L':>10}")
            print("-" * 70)
            for strategy, stats in pnl_by_strategy.items():
                wl = f"{stats['wins']}/{stats['losses']}"
                print(
                    f"  {strategy:<20} {stats['total_trades']:>8} {wl:>10} "
                    f"${stats['total_pnl']:>+10,.2f} ${stats['avg_pnl']:>+8,.2f}"
                )

        # Also show total
        total = self.db.get_bot_pnl_summary()
        print("-" * 70)
        wl_total = f"{total['wins']}/{total['losses']}"
        print(
            f"  {'TOTAL':<20} {total['total_trades']:>8} {wl_total:>10} "
            f"${total['total_pnl']:>+10,.2f}"
        )
        print("=" * 70 + "\n")

    def _cmd_budgets(self):
        """Show strategy budget status."""
        if not self.db:
            self.logger.warning("Database not available")
            return

        budgets = self.db.get_all_budgets()

        print("\n" + "=" * 85)
        print("STRATEGY BUDGETS")
        print("=" * 85)

        if not budgets:
            print("  No strategy budgets configured")
            print("  Add 'budget: <amount>' to strategy config in config.yaml")
        else:
            print(f"  {'Strategy':<22} {'Budget':>10} {'Committed':>11} {'Drawdown':>10} {'Available':>11} {'%Avail':>8}")
            print("-" * 85)
            for strategy_name, state in budgets.items():
                budget = state['budget']
                available = state['available']
                drawdown = state['drawdown']
                committed = state.get('committed', 0)
                pct_avail = (available / budget * 100) if budget > 0 else 0
                print(
                    f"  {strategy_name:<22} ${budget:>8,.0f} ${committed:>9,.2f} "
                    f"${drawdown:>8,.2f} ${available:>9,.2f} {pct_avail:>6.1f}%"
                )

        print("=" * 85 + "\n")

    def _cmd_metrics(self, args: str = ''):
        """Show detailed performance metrics."""
        if not self.db:
            self.logger.warning("Database not available")
            return

        # Parse optional symbol filter
        symbol = args.upper() if args else None  # None is valid for db.get_performance_metrics

        metrics = self.db.get_performance_metrics(symbol=symbol)

        title = f"PERFORMANCE METRICS - {symbol}" if symbol else "PERFORMANCE METRICS"
        print("\n" + "=" * 70)
        print(title)
        print("=" * 70)

        if metrics['total_trades'] == 0:
            print("  No completed trades yet")
            print("=" * 70 + "\n")
            return

        print(f"  Total Trades:     {metrics['total_trades']}")
        print(f"  Winners/Losers:   {metrics['winners']}/{metrics['losers']}")
        print(f"  Win Rate:         {metrics['win_rate']:.1f}%")
        print("-" * 70)
        print(f"  Total P&L:        ${metrics['total_pnl']:+,.2f}")
        print(f"  Average P&L:      ${metrics['avg_pnl']:+,.2f} ({metrics['avg_pnl_pct']:+.1f}%)")
        print(f"  Average Winner:   ${metrics['avg_winner']:+,.2f}")
        print(f"  Average Loser:    ${metrics['avg_loser']:+,.2f}")
        print("-" * 70)
        print(f"  Largest Winner:   ${metrics['largest_winner']:+,.2f}")
        print(f"  Largest Loser:    ${metrics['largest_loser']:+,.2f}")
        print(f"  Profit Factor:    {metrics['profit_factor']}")
        print(f"  Avg Hold Time:    {metrics['avg_hold_hours']:.1f} hours")

        if metrics['best_trade']:
            best = metrics['best_trade']
            print("-" * 70)
            print(f"  Best Trade:  {best['local_symbol']} ${best['pnl']:+,.2f}")

        if metrics['worst_trade']:
            worst = metrics['worst_trade']
            print(f"  Worst Trade: {worst['local_symbol']} ${worst['pnl']:+,.2f}")

        print("=" * 70 + "\n")

    def _cmd_trades(self, args: str = ''):
        """Query and display trade history."""
        if not self.db:
            self.logger.warning("Database not available")
            return

        # Parse filters from args
        symbol = None
        winners_only = False
        losers_only = False
        limit = 20

        if args:
            parts = args.split()
            for part in parts:
                part_upper = part.upper()
                if part_upper == 'WINNERS':
                    winners_only = True
                elif part_upper == 'LOSERS':
                    losers_only = True
                elif part_upper.isdigit():
                    limit = int(part_upper)
                elif len(part_upper) <= 5:  # Likely a symbol
                    symbol = part_upper

        trades = self.db.query_trades(
            symbol=symbol,
            winners_only=winners_only,
            losers_only=losers_only,
            limit=limit,
        )

        filter_desc = []
        if symbol:
            filter_desc.append(symbol)
        if winners_only:
            filter_desc.append("winners")
        if losers_only:
            filter_desc.append("losers")
        title = "TRADE HISTORY"
        if filter_desc:
            title += f" ({', '.join(filter_desc)})"

        print("\n" + "=" * 90)
        print(title)
        print("=" * 90)

        if not trades:
            print("  No trades found matching criteria")
            print("=" * 90 + "\n")
            return

        print(f"  {'Date':<12} {'Symbol':<20} {'Dir':<8} {'Entry':>8} {'Exit':>8} {'P&L':>10} {'Reason':<15}")
        print("-" * 90)

        for trade in trades:
            exit_date = trade['exit_time'][:10] if trade['exit_time'] else 'N/A'
            pnl = trade['pnl'] or 0
            print(
                f"  {exit_date:<12} {trade['local_symbol']:<20} {trade['direction']:<8} "
                f"${trade['entry_price']:>6.2f} ${trade['exit_price'] or 0:>6.2f} "
                f"${pnl:>+8,.2f} {trade['exit_reason'] or '':<15}"
            )

        print("-" * 90)
        print(f"  Showing {len(trades)} trades (use '/trades <symbol> [winners|losers] [limit]')")
        print("=" * 90 + "\n")

    def _cmd_export(self, args: str = ''):
        """Export trades or report to CSV."""
        if not self.db:
            self.logger.warning("Database not available")
            return

        from datetime import datetime as dt
        timestamp = dt.now().strftime("%Y%m%d_%H%M%S")

        export_type = (args or 'trades').lower()

        if export_type == 'report':
            filepath = f"performance_report_{timestamp}.csv"
            self.db.export_performance_report(filepath)
            print(f"\nExported performance report to: {filepath}\n")
        else:
            # Default to trades export
            filepath = f"trades_{timestamp}.csv"
            count = self.db.export_trades_to_csv(filepath)
            print(f"\nExported {count} trades to: {filepath}\n")

    def run(self):
        """Main bot loop"""
        if not self.initialize():
            self.logger.error("Failed to initialize bot")
            return

        self.running = True
        self.stats['start_time'] = datetime.now()

        self.logger.info("=" * 60)
        self.logger.info("SWING TRADING BOT STARTED")
        self.logger.info("=" * 60)
        self.logger.info(f"Monitoring symbols: {', '.join(self.config['symbols'])}")
        self.logger.info(f"Paper trading: {self.config['operation']['enable_paper_trading']}")
        if self.strategy_manager:
            status = self.strategy_manager.get_status()
            self.logger.info(f"Strategies: {status['enabled']} enabled / {status['loaded']} loaded")
        self.logger.info("=" * 60)

        # Start command processing thread
        self._start_command_thread()

        scan_interval = self.config['operation']['scan_interval']
        status_counter = 0
        discovery_counter = 0

        try:
            while self.running:
                # Process any pending user commands
                self._process_pending_command()

                # Check pending orders for fills/timeouts
                self.engine.check_pending_orders()

                # Scan for signals
                self.scan_for_signals()

                # Check open positions
                self.check_positions()

                # Print status every 10 scans
                status_counter += 1
                if status_counter >= 10:
                    self.print_status()
                    status_counter = 0

                # Auto-discover new strategies every 60 scans (~5 min at 5s interval)
                discovery_counter += 1
                if discovery_counter >= 60 and self.strategy_manager:
                    loaded = self.strategy_manager.load_new_strategies()
                    if loaded > 0:
                        self.logger.info(f"Auto-discovered and loaded {loaded} new strategies")
                    discovery_counter = 0

                # Wait for next scan
                time.sleep(scan_interval)

        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received")
        except Exception as e:
            self.logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Clean shutdown"""
        self.logger.info("Shutting down bot...")
        
        # Print final status
        self.print_status()
        
        # Cancel market depth subscriptions
        for symbol, ticker in self.tickers.items():
            try:
                contract = ticker.contract
                self.ib.cancel_market_depth(contract)
            except Exception as e:
                self.logger.error(f"Error canceling depth for {symbol}: {e}")
        
        # Cancel market data subscriptions
        for symbol, ticker in self.price_tickers.items():
            try:
                self.ib.cancel_market_data(ticker.contract)
            except Exception as e:
                self.logger.error(f"Error canceling market data for {symbol}: {e}")

        # Close database
        if self.db:
            self.db.close()

        # Disconnect from IB
        if self.ib:
            self.ib.disconnect()

        self.logger.info("Bot shutdown complete")


def main():
    """Entry point"""
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║         SWING TRADING BOT - Options Trading System        ║
    ║                    Based on Order Flow                    ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    bot = SwingTradingBot('config.yaml')
    bot.run()


if __name__ == '__main__':
    main()
