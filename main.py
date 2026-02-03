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
from datetime import datetime, time as dt_time
from typing import Dict
from zoneinfo import ZoneInfo

from ib_insync import Contract
from ib_wrapper import IBWrapper
from liquidity_analyzer import LiquidityAnalyzer, Pattern
from trading_engine import TradingEngine, TradeDirection, Position
from trade_db import TradeDatabase


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
        self.tickers = {}  # symbol -> ticker mapping
        
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
        
        logging.basicConfig(
            level=getattr(logging, log_level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('trading_bot.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        
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

            # Initialize trading engine
            engine_config = {
                **self.config['risk_management'],
                **self.config['trading_rules'],
                **self.config['option_selection']
            }
            self.engine = TradingEngine(self.ib, self.analyzer, engine_config, trade_db=self.db)

            # Reconcile DB positions with IB account state
            self._reconcile_positions()
            
            # Subscribe to market depth for all symbols
            for symbol in self.config['symbols']:
                ticker = self.ib.subscribe_market_depth(symbol)
                if ticker:
                    self.tickers[symbol] = ticker
                    self.logger.info(f"Subscribed to market depth for {symbol}")
                else:
                    self.logger.warning(f"Failed to subscribe to {symbol}")
            
            if not self.tickers:
                self.logger.error("No market depth subscriptions active")
                return False
            
            self.logger.info("Initialization complete")
            return True
            
        except Exception as e:
            self.logger.error(f"Initialization failed: {e}", exc_info=True)
            return False
    
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
                    continue
                
                # Detect pattern
                signal = self.analyzer.detect_pattern(ticker, current_price)
                
                if signal is None:
                    continue
                
                # Log non-consolidation patterns
                if signal.pattern != Pattern.CONSOLIDATION:
                    self.logger.info(
                        f"{symbol}: {signal.pattern.value} "
                        f"(confidence: {signal.confidence:.2f}, "
                        f"imbalance: {signal.imbalance:.2f})"
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
        self.logger.info(f"Open positions: {status['positions']}/{status['max_positions']}")
        
        if status['active_contracts']:
            self.logger.info(f"Active contracts: {', '.join(status['active_contracts'])}")
        
        if status['account_value']:
            self.logger.info(f"Account value: ${status['account_value']:,.2f}")

        pnl = status.get('pnl')
        if pnl and pnl['total_trades'] > 0:
            self.logger.info(
                f"Bot P&L: ${pnl['total_pnl']:+,.2f} "
                f"({pnl['wins']}W / {pnl['losses']}L over {pnl['total_trades']} trades)"
            )

        self.logger.info("=" * 60)
    
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
        self.logger.info("=" * 60)
        
        scan_interval = self.config['operation']['scan_interval']
        status_counter = 0
        
        try:
            while self.running:
                # Scan for signals
                self.scan_for_signals()
                
                # Check open positions
                self.check_positions()
                
                # Print status every 10 scans
                status_counter += 1
                if status_counter >= 10:
                    self.print_status()
                    status_counter = 0
                
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
