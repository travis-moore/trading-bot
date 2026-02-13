#!/usr/bin/env python3
"""
Swing Trading Bot - Main Program
Automated options trading based on order book liquidity analysis
"""

import csv
import yaml
import os
import logging
import time
import signal
import sys
import threading
import select
import asyncio
from datetime import datetime, time as dt_time
from typing import Dict
from zoneinfo import ZoneInfo

# Try to import colorama for proper Windows color support
try:
    import colorama
    colorama.init()
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False

# Fix for ib_insync/eventkit import error on newer Python versions
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import Contract
from ib_wrapper import IBWrapper
from liquidity_analyzer import LiquidityAnalyzer, Pattern
from trading_engine import TradingEngine, TradeDirection, Position
from trade_db import TradeDatabase
from notifications import DiscordNotifier
from market_context import MarketRegimeDetector, SectorRotationManager

# Try to import strategies module
try:
    from strategies import StrategyManager
    STRATEGIES_AVAILABLE = True
except ImportError:
    STRATEGIES_AVAILABLE = False
    StrategyManager = None


class ColoredFormatter(logging.Formatter):
    """Custom formatter for colored console output"""
    
    # ANSI colors
    GREY = "\x1b[90m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    RED = "\x1b[31m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"
    CYAN = "\x1b[36m"
    
    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt, datefmt)
        
        # Disable colors on Windows if colorama is not available to prevent line wrapping bugs
        if sys.platform == 'win32' and not COLORAMA_AVAILABLE:
            self.GREY = ""
            self.GREEN = ""
            self.YELLOW = ""
            self.RED = ""
            self.BOLD_RED = ""
            self.RESET = ""
            self.CYAN = ""
            
        self.fmt = fmt or '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        self.FORMATS = {
            logging.DEBUG: self.GREY + self.fmt + self.RESET,
            logging.INFO: self.RESET + self.fmt + self.RESET,
            logging.WARNING: self.YELLOW + self.fmt + self.RESET,
            logging.ERROR: self.RED + self.fmt + self.RESET,
            logging.CRITICAL: self.BOLD_RED + self.fmt + self.RESET
        }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        
        # Custom coloring for specific messages
        if record.levelno == logging.INFO:
            msg = record.getMessage().lower()
            # Signals and Trade Entries -> Green
            if "confidence:" in msg or "trade entered" in msg or "attempting to enter" in msg:
                log_fmt = self.GREEN + self.fmt + self.RESET
            # Bot Status / Account Info -> Cyan
            elif "account value:" in msg or "bot status" in msg or "uptime:" in msg:
                log_fmt = self.CYAN + self.fmt + self.RESET
        
        formatter = logging.Formatter(log_fmt, datefmt=self.datefmt)
        return formatter.format(record)


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
        
        # Notifications
        self.notifier = None
        
        # Context
        self.market_regime = None
        self.sector_manager = None
        
        # Statistics
        self.stats = {
            'scans': 0,
            'signals_detected': 0,
            'trades_entered': 0,
            'trades_exited': 0,
            'start_time': None
        }

        # Data Collection
        self.data_log_file = None
        self.data_writer = None
        
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
        from logging.handlers import TimedRotatingFileHandler
        file_handler = TimedRotatingFileHandler('trading_bot.log', when='midnight', interval=1, backupCount=30)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(log_format))

        # Console handler - filters out noisy ib_insync messages
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level))
        console_handler.setFormatter(ColoredFormatter(log_format))

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
        """Handle shutdown signals. Second signal forces immediate exit."""
        if not self.running:
            # Already shutting down — second Ctrl+C forces immediate exit
            self.logger.warning("Force shutdown requested, exiting immediately...")
            os._exit(1)
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
            
            # Verify Account Type (Paper vs Live) - Early Safety Check
            self.ib.ib.sleep(1)  # Wait briefly for account data to sync
            
            acct_id = "Unknown"
            if isinstance(self.ib.ib.managedAccounts, list) and self.ib.ib.managedAccounts:
                acct_id = self.ib.ib.managedAccounts[0]
            
            # Fallback: Try to extract from accountValues if managedAccounts is empty
            if acct_id == "Unknown":
                account_values = self.ib.ib.accountValues()
                if account_values:
                    acct_id = account_values[0].account
            
            is_paper_acct = acct_id.startswith('D')
            enable_paper = self.config['operation'].get('enable_paper_trading', True)
            
            # Strict Account Validation (Env Vars or Config)
            expected_paper = os.environ.get('IB_PAPER_ACCOUNT') or self.config['ib_connection'].get('paper_account_id')
            expected_live = os.environ.get('IB_LIVE_ACCOUNT') or self.config['ib_connection'].get('live_account_id')
            
            # Safety Check: Enforce Paper Trading Mode if configured
            if acct_id != "Unknown":
                if enable_paper:
                    if expected_paper and acct_id != expected_paper:
                        self.logger.critical(f"SAFETY STOP: Expected paper account {expected_paper} but connected to {acct_id}!")
                        return False
                    if not is_paper_acct:
                        self.logger.critical(f"SAFETY STOP: Configured for PAPER TRADING but connected to LIVE account {acct_id}!")
                        return False
                else:
                    if expected_live and acct_id != expected_live:
                        self.logger.critical(f"SAFETY STOP: Expected live account {expected_live} but connected to {acct_id}!")
                        return False

            # Initialize liquidity analyzer
            self.analyzer = LiquidityAnalyzer(self.config['liquidity_analysis'])
            
            # Initialize database
            db_path = self.config.get('database', {}).get('path', 'trading_bot.db')
            self.db = TradeDatabase(db_path)

            # Initialize notifier
            webhook_url = self.config.get('notifications', {}).get('discord_webhook')
            if webhook_url:
                self.notifier = DiscordNotifier(webhook_url)
                self.notifier.send_message("🤖 **Swing Trading Bot Started**")
            
            # Initialize Market Context
            self.market_regime = MarketRegimeDetector(self.ib, self.config.get('market_regime'))
            self.sector_manager = SectorRotationManager(self.ib, self.config.get('sector_rotation'))

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
                strategy_manager=self.strategy_manager,
                market_regime_detector=self.market_regime,
                sector_manager=self.sector_manager,
                notifier=self.notifier
            )

            # Reconcile DB positions with IB account state
            self._reconcile_positions()
            
            # Collect all symbols to monitor (global + per-strategy)
            all_symbols = set(self.config.get('symbols', []) or [])
            
            # Add symbols from configured strategies
            if 'strategies' in self.config:
                for strat_config in self.config['strategies'].values():
                    if strat_config.get('enabled', True):
                        strat_symbols = strat_config.get('symbols', [])
                        if strat_symbols:
                            all_symbols.update(strat_symbols)
            
            # Update config with full list so logging/etc works
            self.config['symbols'] = list(all_symbols)

            # Initialize Per-Symbol Data (Sector Mapping)
            self.logger.info("Initializing symbol sector mapping...")
            for symbol in self.config['symbols']:
                details = self.ib.get_contract_details(symbol)
                if details:
                    self.sector_manager.map_symbol_to_sector(symbol, details.get('industry', ''))

            # Subscribe to market data for all symbols
            depth_exchange = self.config['ib_connection'].get('market_depth_exchange', 'ISLAND')
            is_sequential = self.config['ib_connection'].get('sequential_scanning', False)
            
            for symbol in self.config['symbols']:
                # Level 2 (Depth)
                if not is_sequential:
                    ticker = self.ib.subscribe_market_depth(symbol, exchange=depth_exchange)
                    if ticker:
                        self.tickers[symbol] = ticker
                        self.logger.info(f"Subscribed to market depth for {symbol}")
                    else:
                        self.logger.warning(f"Failed to subscribe to depth for {symbol}")
                
                # Level 1 (Price)
                price_ticker = self.ib.subscribe_market_data(symbol)
                if price_ticker:
                    self.price_tickers[symbol] = price_ticker
            
            if not self.tickers and not is_sequential:
                self.logger.error("No market depth subscriptions active")
                return False
            
            # Initial Context Assessment
            self.market_regime.assess_regime()
            self.sector_manager.assess_rotation()
            
            # Initialize data logger if enabled
            if self.config['operation'].get('data_collection_mode', False):
                self._init_data_logger()

            self.logger.info("Initialization complete")
            return True
            
        except Exception as e:
            self.logger.error(f"Initialization failed: {e}", exc_info=True)
            return False
    
    def _init_data_logger(self):
        """Initialize CSV logger for market data collection."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"market_data_{timestamp}.csv"
        try:
            self.data_log_file = open(filename, 'w', newline='')
            self.data_writer = csv.writer(self.data_log_file)
            self.data_writer.writerow([
                'Timestamp', 'Symbol', 'Price', 'Bid', 'Ask', 'Spread', 
                'Imbalance', 'Bid_Depth', 'Ask_Depth', 
                'Nearest_Support', 'Nearest_Resistance'
            ])
            self.logger.info(f"Data collection mode enabled. Logging to {filename}")
        except Exception as e:
            self.logger.error(f"Failed to initialize data logger: {e}")

    def _log_market_data(self, symbol: str, current_price: float, price_ticker, analysis: Dict):
        """Log market data snapshot to CSV."""
        if not self.data_writer:
            return
            
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
            bid = price_ticker.bid if price_ticker and price_ticker.bid else 0
            ask = price_ticker.ask if price_ticker and price_ticker.ask else 0
            spread = ask - bid if (ask and bid) else 0
            
            nearest = self.analyzer.get_nearest_zones(current_price, analysis)
            sup_price = nearest['support'].price if nearest['support'] else 0
            res_price = nearest['resistance'].price if nearest['resistance'] else 0

            self.data_writer.writerow([
                timestamp, symbol, current_price, bid, ask, spread,
                analysis.get('imbalance', 0), analysis.get('bid_depth_total', 0), analysis.get('ask_depth_total', 0),
                sup_price, res_price
            ])
            self.data_log_file.flush()
        except Exception as e:
            self.logger.error(f"Error logging market data: {e}")

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
            
        # Get all open orders to re-attach bracket orders if possible
        open_trades = self.ib.get_open_orders()

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

                # Ensure entry_time is timezone-aware to prevent strategy errors
                entry_time = datetime.fromisoformat(row['entry_time'])
                if entry_time.tzinfo is None:
                    entry_time = entry_time.astimezone()

                # Handle legacy/invalid pattern names from DB
                try:
                    pattern = Pattern(row['pattern'])
                except ValueError:
                    # Pattern is not in the legacy Enum (likely a strategy-specific string)
                    pattern = row['pattern']
                
                # Try to re-attach bracket orders using order_ref
                tp_trade = None
                sl_trade = None
                trailing_active = False
                order_ref = row['order_ref']
                if order_ref:
                    tp_ref = f"{order_ref}_TP"
                    sl_ref = f"{order_ref}_SL"
                    trail_ref = f"{order_ref}_TRAIL"
                    for trade in open_trades:
                        if trade.order.orderRef == tp_ref:
                            tp_trade = trade
                        elif trade.order.orderRef == sl_ref:
                            sl_trade = trade
                        elif trade.order.orderRef == trail_ref:
                            sl_trade = trade
                            trailing_active = True
                        elif trade.order.orderRef == sl_ref and trade.order.orderType == 'TRAIL':
                            trailing_active = True

                position = Position(
                    contract=contract,
                    entry_price=row['entry_price'],
                    entry_time=entry_time,
                    quantity=actual_qty,
                    direction=TradeDirection(row['direction']),
                    stop_loss=row['stop_loss'],
                    profit_target=row['profit_target'],
                    pattern=pattern,
                    db_id=row['id'],
                    order_ref=row['order_ref'],
                    strategy_name=strategy,
                    peak_price=row['peak_price'] if 'peak_price' in row.keys() else row['entry_price'],
                    stop_loss_trade=sl_trade,
                    take_profit_trade=tp_trade,
                    trailing_stop_active=trailing_active
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
        now = datetime.now(ZoneInfo("America/New_York"))
        
        # Check weekend (Saturday=5, Sunday=6)
        if now.weekday() >= 5:
            return False
            
        now_et = now.time()
        market_open = dt_time(9, 30)
        market_close = dt_time(16, 0)

        return market_open <= now_et <= market_close
    
    def scan_for_signals(self):
        """Scan all symbols for trading signals"""
        self.stats['scans'] += 1

        # Check daily loss limit
        if self._check_daily_loss_limit():
            return

        # Check global consecutive loss limit (Strategy Health Check)
        if self._check_global_consecutive_losses():
            return

        # Update Market Context (Frequency checks handled inside or here)
        # Simple check: run regime at open/mid-day, sector every hour
        # For simplicity in this loop, we rely on the managers to check time or we check here
        now = datetime.now()

        # Re-assess regime periodically (default every 30 min)
        if self.market_regime:
            regime_interval = self.config.get('market_regime', {}).get('update_interval_minutes', 30)
            if self.market_regime.last_update is None or (now - self.market_regime.last_update).total_seconds() > regime_interval * 60:
                self.market_regime.assess_regime()

        # Re-assess sectors periodically (default every 60 min)
        if self.sector_manager:
            sector_interval = self.config.get('sector_rotation', {}).get('update_interval_minutes', 60)
            if self.sector_manager.last_update is None or (now - self.sector_manager.last_update).total_seconds() > sector_interval * 60:
                self.sector_manager.assess_rotation()

        # Identify paused strategies (per-strategy daily loss limit)
        paused_strategies = set()
        if self.strategy_manager:
            for name in self.strategy_manager.get_all_strategies():
                if self._check_strategy_loss_limit(name):
                    paused_strategies.add(name)
                    if self.stats['scans'] % 60 == 0:  # Log periodically
                        self.logger.warning(f"Strategy '{name}' paused: hit daily loss limit.")
                    continue

                # Check consecutive losses
                if self._check_strategy_consecutive_losses(name):
                    paused_strategies.add(name)
                    if self.stats['scans'] % 60 == 0:
                        msg = f"Strategy '{name}' paused: hit consecutive loss limit."
                        self.logger.warning(msg)
                        if self.notifier:
                            self.notifier.send_message(f"⚠️ {msg}")

        # Determine symbols to scan (Sequential vs Parallel)
        is_sequential = self.config['ib_connection'].get('sequential_scanning', False)
        symbols_to_scan = self.config['symbols']

        for symbol in symbols_to_scan:
            ticker = None
            
            # Handle Sequential Scanning (Subscribe -> Analyze -> Unsubscribe)
            if is_sequential:
                depth_exchange = self.config['ib_connection'].get('market_depth_exchange', 'ISLAND')
                # quiet=True to avoid log spam
                ticker = self.ib.subscribe_market_depth(symbol, exchange=depth_exchange, quiet=True)
                # Note: subscribe_market_depth already sleeps 2s to allow data to populate
            else:
                ticker = self.tickers.get(symbol) # Might be None if depth failed (e.g. XSP)

            try:
                # Get current price
                price_ticker = self.price_tickers.get(symbol)
                current_price = self.ib.get_live_price(price_ticker) if price_ticker else None
                if not current_price:
                    continue

                # Always analyze book if we need it for logging or trading
                analysis = None
                if ticker and ticker.domBids and ticker.domAsks:
                    analysis = self.analyzer.analyze_book(ticker)
                elif self.data_writer:
                    # If logging is on but no depth, get empty analysis so we can still log price/spread
                    analysis = {
                        'support': [],
                        'resistance': [],
                        'bid_depth_total': 0,
                        'ask_depth_total': 0,
                        'imbalance': 0
                    }

                # Analyze order book for support/resistance (for logging)
                if analysis and ticker and ticker.domBids and ticker.domAsks:
                    nearest = self.analyzer.get_nearest_zones(current_price, analysis)
                    support_str = f"${nearest['support'].price:.2f}" if nearest['support'] else "none"
                    resistance_str = f"${nearest['resistance'].price:.2f}" if nearest['resistance'] else "none"
                else:
                    support_str = "no_depth"
                    resistance_str = "no_depth"

                # Log data if enabled
                if self.data_writer and analysis:
                    self._log_market_data(symbol, current_price, price_ticker, analysis)

                # Use strategy manager if available, otherwise fall back to legacy analyzer
                if self.strategy_manager:
                    # FIX: Ensure position timestamps are timezone-aware to prevent strategy errors
                    for pos in self.engine.positions:
                        if hasattr(pos, 'entry_time') and isinstance(pos.entry_time, datetime) and pos.entry_time.tzinfo is None:
                            pos.entry_time = pos.entry_time.astimezone()

                    # Get signals from all enabled strategy instances
                    context = {
                        'symbol': symbol,
                        'positions': self.engine.positions,
                        'account_value': self.ib.get_account_value(),
                        'market_regime': self.market_regime.current_regime,
                        'sector_rs': self.sector_manager.get_sector_rs(symbol)
                    }
                    signals = self.strategy_manager.analyze_all(ticker, current_price, context) # ticker can be None

                    for signal in signals:
                        # Get strategy instance info from signal metadata
                        strategy_name = signal.metadata.get('strategy', 'unknown')
                        
                        # Skip signals from paused strategies
                        if strategy_name in paused_strategies:
                            continue
                            
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
                        # We pass symbol via metadata hack or rely on engine to have context
                        # Engine has sector_manager, but needs symbol to check RS.
                        # evaluate_signal signature is evaluate_signal(signal).
                        # We can attach symbol to signal metadata if not present.
                        if 'symbol' not in signal.metadata:
                            signal.metadata['symbol'] = symbol
                        
                        direction = self.engine.evaluate_signal(signal)
                        outcome = 'rejected'

                        if direction and direction != TradeDirection.NO_TRADE:
                            if self._handle_trade_signal(symbol, direction, signal, current_price):
                                outcome = 'executed'
                            else:
                                outcome = 'failed_entry'
                        
                        # Log signal for Opportunity Utilization analysis
                        if self.db:
                            self.db.log_signal(
                                symbol=symbol,
                                strategy=strategy_name,
                                pattern=signal.pattern_name,
                                confidence=signal.confidence,
                                price=current_price,
                                outcome=outcome
                            )
                else:
                    # Legacy path: use analyzer directly
                    signal = self.analyzer.detect_pattern(ticker, current_price) if ticker else None

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
                        outcome = 'rejected'

                        if direction and direction != TradeDirection.NO_TRADE:
                            if self._handle_trade_signal(symbol, direction, signal, current_price):
                                outcome = 'executed'
                            else:
                                outcome = 'failed_entry'
                        
                        if self.db:
                            self.db.log_signal(
                                symbol=symbol,
                                strategy='legacy',
                                pattern=signal.pattern.value,
                                confidence=signal.confidence,
                                price=current_price,
                                outcome=outcome
                            )

            except Exception as e:
                self.logger.error(f"Error scanning {symbol}: {e}", exc_info=True)
            finally:
                # Clean up subscription if in sequential mode
                if is_sequential and ticker:
                    self.ib.cancel_market_depth(ticker.contract)
    
    def _check_daily_loss_limit(self) -> bool:
        """Check if daily loss limit has been reached. Returns True if trading should stop."""
        limit = self.config['safety'].get('daily_loss_limit')
        if limit is None or limit <= 0:
            return False
            
        today_pnl = self.db.get_today_realized_pnl()
        if today_pnl <= -limit:
            if self.stats['scans'] % 60 == 0:  # Log periodically (every ~5 mins)
                self.logger.warning(f"Daily loss limit reached (${today_pnl:.2f} <= -${limit:.2f}). Pausing new trades.")
            return True
            
        return False
        
    def _check_strategy_loss_limit(self, strategy_name: str) -> bool:
        """Check if a specific strategy has hit its daily loss limit."""
        if not self.strategy_manager:
            return False
            
        strategy = self.strategy_manager.get_strategy(strategy_name)
        if not strategy:
            return False
            
        limit = strategy.get_config('daily_loss_limit')
        if limit is None or limit <= 0:
            return False
            
        today_pnl = self.db.get_today_realized_pnl(strategy=strategy_name)
        return today_pnl <= -limit

    def _check_global_consecutive_losses(self) -> bool:
        """Check if global consecutive loss limit has been reached."""
        limit = self.config['safety'].get('max_consecutive_losses')
        if limit is None or limit <= 0:
            return False
            
        losses = self.db.get_consecutive_losses()
        if losses >= limit:
            if self.stats['scans'] % 60 == 0:
                msg = f"Global consecutive loss limit reached ({losses} >= {limit}). Pausing new trades."
                self.logger.warning(msg)
                if self.notifier:
                    self.notifier.send_message(f"🛑 {msg}")
            return True
        return False

    def _check_strategy_consecutive_losses(self, strategy_name: str) -> bool:
        """Check if strategy consecutive loss limit has been reached."""
        if not self.strategy_manager:
            return False
            
        strategy = self.strategy_manager.get_strategy(strategy_name)
        if not strategy:
            return False
            
        limit = strategy.get_config('max_consecutive_losses')
        if limit is None or limit <= 0:
            return False
            
        losses = self.db.get_consecutive_losses(strategy=strategy_name)
        return losses >= limit

    def _handle_trade_signal(self, symbol: str, direction: TradeDirection,
                            signal, current_price: float):
        """Handle a valid trade signal. Returns True if trade entered successfully."""
        # Check safety conditions
        if self.config['safety']['emergency_stop']:
            self.logger.warning("Emergency stop active, skipping trade")
            return False
        
        if not self._is_market_hours():
            self.logger.info("Outside market hours, skipping trade")
            return False
        
        # Check if manual approval required
        if self.config['safety']['require_manual_approval']:
            self.logger.info(
                f"Trade signal: {symbol} {direction.value} @ ${current_price:.2f}"
            )
            approval = input("Approve trade? (yes/no): ").lower()
            if approval != 'yes':
                self.logger.info("Trade not approved")
                return False
        
        # Enter trade
        self.logger.info(f"Attempting to enter trade: {symbol} {direction.value}")
        
        success = self.engine.enter_trade(symbol, direction, signal)
        
        if success:
            self.stats['trades_entered'] += 1
            self.logger.info("Trade entered successfully")
            return True
        else:
            self.logger.warning("Failed to enter trade")
            return False
    
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
        elif command == '/positions':
            self._cmd_positions()
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
        elif command == '/test_notify':
            self._cmd_test_notify()
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
  /positions         - Show open positions and pending orders
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
  /test_notify       - Send a test notification to Discord
  /quit or /stop     - Stop the bot gracefully
"""
        print(help_text)

    def _cmd_positions(self):
        """Show detailed info for all open positions and pending orders."""
        positions = self.engine.positions
        pending = self.engine.pending_orders

        print("\n" + "=" * 60)
        print("OPEN POSITIONS")
        print("=" * 60)

        if not positions and not pending:
            print("  No open positions or pending orders.")
            print("=" * 60 + "\n")
            return

        now = datetime.now()
        for i, p in enumerate(positions, 1):
            symbol = p.contract.symbol if hasattr(p.contract, 'symbol') else p.contract.localSymbol
            local = getattr(p.contract, 'localSymbol', symbol)
            days_held = (now - p.entry_time.replace(tzinfo=None) if p.entry_time.tzinfo else now - p.entry_time).days

            # Get current price for P&L
            current_price = None
            try:
                price_data = self.ib.get_option_price(p.contract)
                if price_data:
                    bid, ask, last = price_data
                    current_price = (bid + ask) / 2 if bid > 0 and ask > 0 else last
            except Exception:
                pass

            pnl_str = ""
            if current_price and current_price > 0:
                pnl_per_contract = (current_price - p.entry_price) * 100
                pnl_total = pnl_per_contract * p.quantity
                pnl_pct = (current_price - p.entry_price) / p.entry_price * 100
                pnl_str = f"  P&L: ${pnl_total:+.2f} ({pnl_pct:+.1f}%) | Current: ${current_price:.2f}"

            strategy = p.strategy_name or "unknown"
            direction = p.direction.value if hasattr(p.direction, 'value') else str(p.direction)

            print(f"  [{i}] {local} ({direction})")
            print(f"      Strategy: {strategy} | Qty: {p.quantity}")
            print(f"      Entry: ${p.entry_price:.2f} | SL: ${p.stop_loss:.2f} | TP: ${p.profit_target:.2f}")
            print(f"      Held: {days_held}d | Since: {p.entry_time.strftime('%Y-%m-%d %H:%M')}")
            if p.peak_price:
                print(f"      Peak: ${p.peak_price:.2f}")
            if pnl_str:
                print(pnl_str)

        if pending:
            print("-" * 60)
            print("PENDING ORDERS")
            for i, po in enumerate(pending, 1):
                symbol = po.contract.symbol if hasattr(po.contract, 'symbol') else po.contract.localSymbol
                local = getattr(po.contract, 'localSymbol', symbol)
                strategy = po.strategy_name or "unknown"
                print(f"  [{i}] {local} | Strategy: {strategy} | Entry: ${po.entry_price:.2f}")

        print("=" * 60 + "\n")

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

        new_strategies = self.strategy_manager.get_unloaded_strategies()

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

    def _cmd_test_notify(self):
        """Send a test notification to Discord."""
        if self.notifier:
            self.notifier.send_message("🔔 **Test Notification** from Swing Trading Bot")
            self.logger.info("Sent test notification to Discord")
            print("Notification sent.")
        else:
            print("Discord notifier not configured (check config.yaml).")

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

        # Account Status & Value
        account_val = self.ib.get_account_value()
        
        acct_id = "Unknown"
        if isinstance(self.ib.ib.managedAccounts, list) and self.ib.ib.managedAccounts:
            acct_id = self.ib.ib.managedAccounts[0]
        
        # Fallback: Try to extract from accountValues if managedAccounts is empty
        if acct_id == "Unknown":
            account_values = self.ib.ib.accountValues()
            if account_values:
                acct_id = account_values[0].account
            
        is_paper_acct = acct_id.startswith('D')
        if acct_id == "Unknown":
            acct_type = "UNKNOWN STATUS"
        else:
            acct_type = "PAPER TRADING" if is_paper_acct else "LIVE TRADING"

        self.logger.info(f"Account: {acct_id} [{acct_type}]")
        if account_val:
            self.logger.info(f"Account Value: ${account_val:,.2f}")

        self.logger.info(f"Monitoring symbols: {', '.join(self.config['symbols'])}")
        self.logger.info(f"Config Paper Mode: {self.config['operation']['enable_paper_trading']}")
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

                # Wait for next scan (interruptible — checks self.running every 0.5s)
                elapsed = 0.0
                while elapsed < scan_interval and self.running:
                    time.sleep(min(0.5, scan_interval - elapsed))
                    elapsed += 0.5

        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received")
        except Exception as e:
            self.logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
        finally:
            self.shutdown()
    
    def _shutdown_with_timeout(self, func, description, timeout=5):
        """Run a shutdown step in a thread with a timeout."""
        t = threading.Thread(target=func, daemon=True)
        t.start()
        t.join(timeout=timeout)
        if t.is_alive():
            self.logger.warning(f"Shutdown step timed out after {timeout}s: {description}")

    def shutdown(self):
        """Clean shutdown with timeouts to prevent hanging."""
        self.logger.info("Shutting down bot...")

        # Print final status
        try:
            self.print_status()
        except Exception:
            pass

        # Cancel market depth subscriptions (with timeout)
        def cancel_depth():
            for symbol, ticker in self.tickers.items():
                try:
                    self.ib.cancel_market_depth(ticker.contract)
                except Exception as e:
                    self.logger.error(f"Error canceling depth for {symbol}: {e}")
        self._shutdown_with_timeout(cancel_depth, "cancel market depth")

        # Cancel market data subscriptions (with timeout)
        def cancel_market_data():
            for symbol, ticker in self.price_tickers.items():
                try:
                    self.ib.cancel_market_data(ticker.contract)
                except Exception as e:
                    self.logger.error(f"Error canceling market data for {symbol}: {e}")
        self._shutdown_with_timeout(cancel_market_data, "cancel market data")

        # Close database
        if self.db:
            try:
                self.db.close()
            except Exception:
                pass

        # Disconnect from IB (with timeout)
        if self.ib:
            self._shutdown_with_timeout(self.ib.disconnect, "IB disconnect")

        # Close data log
        if self.data_log_file:
            try:
                self.data_log_file.close()
            except Exception:
                pass

        # Send Discord notification (with timeout)
        if self.notifier:
            self._shutdown_with_timeout(
                lambda: self.notifier.send_message("🛑 **Swing Trading Bot Stopped**"),
                "Discord notification", timeout=5
            )

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
