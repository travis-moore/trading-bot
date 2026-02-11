"""
SQLite persistence layer for trading bot positions and trade history.
"""

import sqlite3
import logging
import time
from datetime import datetime
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = "trading_bot.db"


class TradeDatabase:
    """SQLite database for tracking bot trades and positions."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._order_seq = 0
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        logger.info(f"Trade database opened: {db_path}")

    def _create_tables(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS positions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol          TEXT NOT NULL,
                local_symbol    TEXT NOT NULL,
                con_id          INTEGER NOT NULL,
                strike          REAL NOT NULL,
                expiry          TEXT NOT NULL,
                right           TEXT NOT NULL,
                exchange        TEXT NOT NULL DEFAULT 'SMART',
                entry_price     REAL NOT NULL,
                entry_time      TEXT NOT NULL,
                quantity        INTEGER NOT NULL,
                direction       TEXT NOT NULL,
                stop_loss       REAL NOT NULL,
                profit_target   REAL NOT NULL,
                pattern         TEXT NOT NULL,
                strategy        TEXT NOT NULL DEFAULT 'swing_trading',
                entry_order_id  INTEGER,
                order_ref       TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'open',
                peak_price      REAL,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS trade_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id     INTEGER,
                symbol          TEXT NOT NULL,
                local_symbol    TEXT NOT NULL,
                con_id          INTEGER NOT NULL,
                strike          REAL NOT NULL,
                expiry          TEXT NOT NULL,
                right           TEXT NOT NULL,
                direction       TEXT NOT NULL,
                pattern         TEXT NOT NULL,
                strategy        TEXT NOT NULL DEFAULT 'swing_trading',
                quantity        INTEGER NOT NULL,
                entry_price     REAL NOT NULL,
                entry_time      TEXT NOT NULL,
                entry_order_id  INTEGER,
                order_ref       TEXT NOT NULL,
                exit_price      REAL,
                exit_time       TEXT,
                exit_reason     TEXT,
                exit_order_id   INTEGER,
                pnl             REAL,
                pnl_pct         REAL,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Strategy budget tracking
            -- drawdown tracks cumulative losses (0 = no losses)
            -- committed tracks capital locked in open positions
            -- available = budget - drawdown - committed
            CREATE TABLE IF NOT EXISTS strategy_budgets (
                strategy_name   TEXT PRIMARY KEY,
                budget          REAL NOT NULL,
                drawdown        REAL NOT NULL DEFAULT 0,
                committed       REAL NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Historical price bar caching for bounce detection
            CREATE TABLE IF NOT EXISTS historical_bars (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol          TEXT NOT NULL,
                bar_size        TEXT NOT NULL,
                timestamp       TEXT NOT NULL,
                open            REAL NOT NULL,
                high            REAL NOT NULL,
                low             REAL NOT NULL,
                close           REAL NOT NULL,
                volume          INTEGER NOT NULL,
                fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(symbol, bar_size, timestamp)
            );

            CREATE INDEX IF NOT EXISTS idx_hist_bars_symbol_time
            ON historical_bars(symbol, bar_size, timestamp);
        """)
        self.conn.commit()
        self._migrate_add_strategy_column()
        self._migrate_add_peak_price_column()

    def _migrate_add_strategy_column(self):
        """Add strategy column to existing tables if missing (migration)."""
        cursor = self.conn.execute("PRAGMA table_info(positions)")
        columns = {row[1] for row in cursor.fetchall()}
        if 'strategy' not in columns:
            logger.info("Migrating: adding strategy column to positions table")
            self.conn.execute(
                "ALTER TABLE positions ADD COLUMN strategy TEXT NOT NULL DEFAULT 'swing_trading'"
            )
            self.conn.commit()

        cursor = self.conn.execute("PRAGMA table_info(trade_history)")
        columns = {row[1] for row in cursor.fetchall()}
        if 'strategy' not in columns:
            logger.info("Migrating: adding strategy column to trade_history table")
            self.conn.execute(
                "ALTER TABLE trade_history ADD COLUMN strategy TEXT NOT NULL DEFAULT 'swing_trading'"
            )
            self.conn.commit()

        # Add committed column to strategy_budgets if missing
        cursor = self.conn.execute("PRAGMA table_info(strategy_budgets)")
        columns = {row[1] for row in cursor.fetchall()}
        if 'committed' not in columns:
            logger.info("Migrating: adding committed column to strategy_budgets table")
            self.conn.execute(
                "ALTER TABLE strategy_budgets ADD COLUMN committed REAL NOT NULL DEFAULT 0"
            )
            self.conn.commit()

    def _migrate_add_peak_price_column(self):
        """Add peak_price column to positions table if missing."""
        cursor = self.conn.execute("PRAGMA table_info(positions)")
        columns = {row[1] for row in cursor.fetchall()}
        if 'peak_price' not in columns:
            logger.info("Migrating: adding peak_price column to positions table")
            self.conn.execute(
                "ALTER TABLE positions ADD COLUMN peak_price REAL"
            )
            self.conn.commit()

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Trade database closed")

    # --- Position CRUD ---

    def insert_position(self, data: Dict[str, Any]) -> int:
        """
        Insert a new position row.

        Args:
            data: dict with keys matching positions table columns
                  (strategy defaults to 'swing_trading' if not provided)

        Returns:
            The new row id.
        """
        # Default strategy if not provided
        if 'strategy' not in data:
            data['strategy'] = 'swing_trading'

        # Default peak_price to entry_price if not provided
        if 'peak_price' not in data and 'entry_price' in data:
            data['peak_price'] = data['entry_price']

        cursor = self.conn.execute("""
            INSERT INTO positions (
                symbol, local_symbol, con_id, strike, expiry, right, exchange,
                entry_price, entry_time, quantity, direction,
                stop_loss, profit_target, pattern, strategy,
                entry_order_id, order_ref, status, peak_price
            ) VALUES (
                :symbol, :local_symbol, :con_id, :strike, :expiry, :right, :exchange,
                :entry_price, :entry_time, :quantity, :direction,
                :stop_loss, :profit_target, :pattern, :strategy,
                :entry_order_id, :order_ref, :status, :peak_price
            )
        """, data)
        self.conn.commit()
        row_id = cursor.lastrowid
        logger.info(f"Inserted position id={row_id}: {data.get('local_symbol')}")
        return row_id

    def get_open_positions(self) -> List[sqlite3.Row]:
        """Return all positions with status 'open' or 'pending_fill'."""
        cursor = self.conn.execute(
            "SELECT * FROM positions WHERE status IN ('open', 'pending_fill')"
        )
        return cursor.fetchall()

    def update_position_status(self, position_id: int, status: str):
        """Update the status of a position."""
        self.conn.execute(
            "UPDATE positions SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, position_id)
        )
        self.conn.commit()

    def update_position_order_id(self, position_id: int, order_id: int):
        """Update the entry_order_id after order placement."""
        self.conn.execute(
            "UPDATE positions SET entry_order_id = ?, updated_at = datetime('now') WHERE id = ?",
            (order_id, position_id)
        )
        self.conn.commit()

    def update_position_quantity(self, position_id: int, quantity: int):
        """Update quantity (used during reconciliation for partial fills)."""
        self.conn.execute(
            "UPDATE positions SET quantity = ?, updated_at = datetime('now') WHERE id = ?",
            (quantity, position_id)
        )
        self.conn.commit()

    def update_position_peak_price(self, position_id: int, peak_price: float):
        """Update the peak price reached for a position (for trailing stops)."""
        self.conn.execute(
            "UPDATE positions SET peak_price = ?, updated_at = datetime('now') WHERE id = ?",
            (peak_price, position_id)
        )
        self.conn.commit()

    # --- Trade History ---

    def close_position(self, position_id: int, exit_price: float,
                       exit_reason: str, exit_order_id: Optional[int] = None):
        """
        Atomically move an open position to trade_history and delete from positions.
        Also releases committed budget and applies P&L to drawdown.
        """
        row = self.conn.execute(
            "SELECT * FROM positions WHERE id = ?", (position_id,)
        ).fetchone()

        if not row:
            logger.warning(f"Position id={position_id} not found in DB")
            return

        # Calculate entry cost and exit value (options = price * quantity * 100)
        entry_cost = row['entry_price'] * row['quantity'] * 100
        exit_value = exit_price * row['quantity'] * 100 if exit_price and exit_price > 0 else 0

        # Calculate P&L
        pnl = None
        pnl_pct = None
        if exit_price and exit_price > 0 and row['entry_price'] > 0:
            pnl = exit_value - entry_cost
            pnl_pct = (exit_price - row['entry_price']) / row['entry_price'] * 100

        exit_time = datetime.now().isoformat()

        try:
            # Get strategy (default to swing_trading for older records without it)
            strategy = row['strategy'] if 'strategy' in row.keys() else 'swing_trading'

            self.conn.execute("BEGIN")
            self.conn.execute("""
                INSERT INTO trade_history (
                    position_id, symbol, local_symbol, con_id, strike, expiry, right,
                    direction, pattern, strategy, quantity,
                    entry_price, entry_time, entry_order_id, order_ref,
                    exit_price, exit_time, exit_reason, exit_order_id,
                    pnl, pnl_pct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position_id, row['symbol'], row['local_symbol'], row['con_id'],
                row['strike'], row['expiry'], row['right'],
                row['direction'], row['pattern'], strategy, row['quantity'],
                row['entry_price'], row['entry_time'], row['entry_order_id'],
                row['order_ref'],
                exit_price, exit_time, exit_reason, exit_order_id,
                pnl, pnl_pct
            ))
            self.conn.execute("DELETE FROM positions WHERE id = ?", (position_id,))
            self.conn.commit()
            logger.info(
                f"[{strategy}] Closed position: {row['local_symbol']} "
                f"reason={exit_reason} pnl=${pnl:+.2f}" if pnl else
                f"[{strategy}] Closed position: {row['local_symbol']} reason={exit_reason}"
            )

            # Release committed budget and apply P&L
            if exit_value > 0:
                self.release_budget(strategy, entry_cost, exit_value)
            else:
                # Position closed without exit price (manual close, expired, etc.)
                # Release committed amount as total loss
                self.release_budget(strategy, entry_cost, 0)

        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error closing position id={position_id}: {e}")
            raise

    def get_trade_history(self, symbol: Optional[str] = None,
                          limit: int = 100) -> List[sqlite3.Row]:
        """Query trade history with optional symbol filter."""
        if symbol:
            cursor = self.conn.execute(
                "SELECT * FROM trade_history WHERE symbol = ? ORDER BY created_at DESC LIMIT ?",
                (symbol, limit)
            )
        else:
            cursor = self.conn.execute(
                "SELECT * FROM trade_history ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
        return cursor.fetchall()

    def get_bot_pnl_summary(self) -> Dict[str, Any]:
        """Return P&L summary for bot-managed trades only (excludes manual closes)."""
        cursor = self.conn.execute("""
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
                COALESCE(SUM(pnl), 0) as total_pnl
            FROM trade_history
            WHERE exit_reason NOT IN ('manual_close', 'reconciliation_not_found')
              AND pnl IS NOT NULL
        """)
        row = cursor.fetchone()
        return {
            'total_trades': row['total_trades'] or 0,
            'wins': row['wins'] or 0,
            'losses': row['losses'] or 0,
            'total_pnl': row['total_pnl'] or 0.0,
        }

    def get_pnl_by_strategy(self) -> Dict[str, Dict[str, Any]]:
        """Return P&L summary grouped by strategy."""
        cursor = self.conn.execute("""
            SELECT
                strategy,
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
                COALESCE(SUM(pnl), 0) as total_pnl,
                COALESCE(AVG(pnl), 0) as avg_pnl,
                COALESCE(AVG(pnl_pct), 0) as avg_pnl_pct
            FROM trade_history
            WHERE exit_reason NOT IN ('manual_close', 'reconciliation_not_found')
              AND pnl IS NOT NULL
            GROUP BY strategy
            ORDER BY total_pnl DESC
        """)
        result = {}
        for row in cursor.fetchall():
            result[row['strategy']] = {
                'total_trades': row['total_trades'] or 0,
                'wins': row['wins'] or 0,
                'losses': row['losses'] or 0,
                'total_pnl': row['total_pnl'] or 0.0,
                'avg_pnl': row['avg_pnl'] or 0.0,
                'avg_pnl_pct': row['avg_pnl_pct'] or 0.0,
            }
        return result

    # --- Order Tagging ---

    def generate_order_ref(self) -> str:
        """Generate a unique order reference tag for bot orders."""
        self._order_seq += 1
        return f"SWINGBOT-{int(time.time())}-{self._order_seq}"

    def get_order_refs(self) -> set:
        """Return all order_ref values from open positions and history."""
        refs = set()
        for row in self.conn.execute("SELECT order_ref FROM positions"):
            refs.add(row['order_ref'])
        for row in self.conn.execute("SELECT order_ref FROM trade_history"):
            refs.add(row['order_ref'])
        return refs

    def has_traded_symbol_today(self, symbol: str, strategy_name: str) -> bool:
        """
        Check if a strategy has already initiated a trade for a symbol today.
        Checks both pending positions and trade history.
        """
        today = datetime.now().date().isoformat()

        # Check trade_history for closed trades initiated today
        # Using entry_time to correctly identify when the trade was started
        cursor = self.conn.execute("""
            SELECT 1 FROM trade_history
            WHERE symbol = ? AND strategy = ? AND DATE(entry_time) = ?
            LIMIT 1
        """, (symbol, strategy_name, today))
        if cursor.fetchone():
            return True

        # Check positions table for open/pending trades initiated today
        # Using created_at as it reflects when the DB record was made
        cursor = self.conn.execute("""
            SELECT 1 FROM positions
            WHERE symbol = ? AND strategy = ? AND DATE(created_at) = ?
            LIMIT 1
        """, (symbol, strategy_name, today))
        if cursor.fetchone():
            return True

        return False

    # =========================================================================
    # Strategy Budget Management
    # =========================================================================
    #
    # Budget model:
    # - Each strategy has a max budget (cap)
    # - Losses reduce available budget (increase drawdown)
    # - Wins recover available budget up to the cap (decrease drawdown)
    # - Profits beyond the cap don't increase available budget
    #
    # Formula: available = budget - drawdown
    # After trade: drawdown = max(0, drawdown - pnl)
    #   - Win (+pnl) reduces drawdown
    #   - Loss (-pnl) increases drawdown

    def get_strategy_budget(self, strategy_name: str) -> Optional[Dict[str, Any]]:
        """
        Get current budget state for a strategy.

        Returns:
            Dict with 'budget', 'drawdown', 'committed', 'available' or None if not found
        """
        cursor = self.conn.execute(
            "SELECT * FROM strategy_budgets WHERE strategy_name = ?",
            (strategy_name,)
        )
        row = cursor.fetchone()
        if not row:
            return None

        budget = row['budget']
        drawdown = row['drawdown']
        committed = row['committed'] if 'committed' in row.keys() else 0
        return {
            'strategy_name': strategy_name,
            'budget': budget,
            'drawdown': drawdown,
            'committed': committed,
            'available': budget - drawdown - committed,
            'updated_at': row['updated_at'],
        }

    def set_strategy_budget(self, strategy_name: str, budget: float,
                            reset_drawdown: bool = False) -> Dict[str, Any]:
        """
        Initialize or update a strategy's budget.

        Args:
            strategy_name: The strategy instance name
            budget: Maximum budget for this strategy
            reset_drawdown: If True, reset drawdown to 0 (full budget available)

        Returns:
            Current budget state
        """
        existing = self.get_strategy_budget(strategy_name)

        if existing:
            if reset_drawdown:
                self.conn.execute("""
                    UPDATE strategy_budgets
                    SET budget = ?, drawdown = 0, committed = 0, updated_at = datetime('now')
                    WHERE strategy_name = ?
                """, (budget, strategy_name))
            else:
                # Keep existing drawdown, but cap it at new budget
                new_drawdown = min(existing['drawdown'], budget)
                self.conn.execute("""
                    UPDATE strategy_budgets
                    SET budget = ?, drawdown = ?, updated_at = datetime('now')
                    WHERE strategy_name = ?
                """, (budget, new_drawdown, strategy_name))
        else:
            self.conn.execute("""
                INSERT INTO strategy_budgets (strategy_name, budget, drawdown, committed)
                VALUES (?, ?, 0, 0)
            """, (strategy_name, budget))

        self.conn.commit()
        logger.info(f"Set budget for '{strategy_name}': ${budget:.2f}" +
                    (" (drawdown reset)" if reset_drawdown else ""))
        # This should never be None since we just inserted/updated
        result = self.get_strategy_budget(strategy_name)
        assert result is not None
        return result

    def commit_budget(self, strategy_name: str, amount: float) -> Optional[Dict[str, Any]]:
        """
        Commit (reserve) budget when a position is opened.

        This reduces available budget immediately when a trade fills,
        preventing the strategy from over-allocating.

        Args:
            strategy_name: The strategy instance name
            amount: Dollar amount to commit (trade cost)

        Returns:
            Updated budget state, or None if strategy has no budget configured
        """
        existing = self.get_strategy_budget(strategy_name)
        if not existing:
            logger.debug(f"No budget configured for strategy '{strategy_name}'")
            return None

        old_committed = existing['committed']
        new_committed = old_committed + amount

        self.conn.execute("""
            UPDATE strategy_budgets
            SET committed = ?, updated_at = datetime('now')
            WHERE strategy_name = ?
        """, (new_committed, strategy_name))
        self.conn.commit()

        new_state = self.get_strategy_budget(strategy_name)
        if new_state:
            logger.info(
                f"[{strategy_name}] Budget committed: +${amount:.2f}, "
                f"committed ${old_committed:.2f}->${new_committed:.2f}, "
                f"available ${new_state['available']:.2f}"
            )
        return new_state

    def release_budget(self, strategy_name: str, committed_amount: float,
                       exit_value: float) -> Optional[Dict[str, Any]]:
        """
        Release committed budget when a position is closed.

        This removes the committed amount and applies P&L to drawdown.
        - If exit_value > committed_amount: profit reduces drawdown
        - If exit_value < committed_amount: loss increases drawdown

        Args:
            strategy_name: The strategy instance name
            committed_amount: Original amount committed (entry cost)
            exit_value: Value received on exit

        Returns:
            Updated budget state, or None if strategy has no budget configured
        """
        existing = self.get_strategy_budget(strategy_name)
        if not existing:
            logger.debug(f"No budget configured for strategy '{strategy_name}'")
            return None

        pnl = exit_value - committed_amount
        old_committed = existing['committed']
        old_drawdown = existing['drawdown']

        # Release the committed amount
        new_committed = max(0, old_committed - committed_amount)

        # Apply P&L to drawdown
        # Loss (negative pnl) increases drawdown
        # Win (positive pnl) decreases drawdown (but not below 0)
        new_drawdown = max(0, old_drawdown - pnl)

        self.conn.execute("""
            UPDATE strategy_budgets
            SET committed = ?, drawdown = ?, updated_at = datetime('now')
            WHERE strategy_name = ?
        """, (new_committed, new_drawdown, strategy_name))
        self.conn.commit()

        new_state = self.get_strategy_budget(strategy_name)
        if new_state:
            logger.info(
                f"[{strategy_name}] Budget released: pnl=${pnl:+.2f}, "
                f"committed ${old_committed:.2f}->${new_committed:.2f}, "
                f"drawdown ${old_drawdown:.2f}->${new_drawdown:.2f}, "
                f"available ${new_state['available']:.2f}"
            )
        return new_state

    def update_budget_after_trade(self, strategy_name: str, pnl: float) -> Optional[Dict[str, Any]]:
        """
        Adjust strategy budget after a trade closes.

        The drawdown model:
        - Win (pnl > 0): reduces drawdown, recovering budget up to cap
        - Loss (pnl < 0): increases drawdown, reducing available budget

        Args:
            strategy_name: The strategy instance name
            pnl: The trade's P&L (positive = profit, negative = loss)

        Returns:
            Updated budget state, or None if strategy has no budget configured
        """
        existing = self.get_strategy_budget(strategy_name)
        if not existing:
            logger.debug(f"No budget configured for strategy '{strategy_name}'")
            return None

        # New drawdown = max(0, old_drawdown - pnl)
        # Win (+pnl) reduces drawdown, loss (-pnl) increases it
        old_drawdown = existing['drawdown']
        new_drawdown = max(0, old_drawdown - pnl)

        self.conn.execute("""
            UPDATE strategy_budgets
            SET drawdown = ?, updated_at = datetime('now')
            WHERE strategy_name = ?
        """, (new_drawdown, strategy_name))
        self.conn.commit()

        new_state = self.get_strategy_budget(strategy_name)
        if new_state:
            logger.info(
                f"Budget update for '{strategy_name}': pnl=${pnl:+.2f}, "
                f"drawdown ${old_drawdown:.2f}->${new_drawdown:.2f}, "
                f"available ${new_state['available']:.2f}/${existing['budget']:.2f}"
            )
        return new_state

    def get_available_budget(self, strategy_name: str) -> float:
        """
        Get the current available budget for a strategy.

        Available = budget - drawdown - committed

        Returns:
            Available budget amount, or 0 if strategy has no budget configured
        """
        state = self.get_strategy_budget(strategy_name)
        if not state:
            return 0.0
        return state['available']

    def get_all_budgets(self) -> Dict[str, Dict[str, Any]]:
        """
        Get budget state for all configured strategies.

        Returns:
            Dict mapping strategy_name -> budget state
        """
        cursor = self.conn.execute("SELECT * FROM strategy_budgets ORDER BY strategy_name")
        result = {}
        for row in cursor.fetchall():
            budget = row['budget']
            drawdown = row['drawdown']
            committed = row['committed'] if 'committed' in row.keys() else 0
            result[row['strategy_name']] = {
                'budget': budget,
                'drawdown': drawdown,
                'committed': committed,
                'available': budget - drawdown - committed,
                'updated_at': row['updated_at'],
            }
        return result

    def recalculate_budget_from_history(self, strategy_name: str, initial_budget: float) -> Dict[str, Any]:
        """
        Recalculate a strategy's budget state from trade history and open positions.

        This is useful for:
        - Recovering from corrupted budget data
        - Initializing budget for a strategy with existing trades

        Args:
            strategy_name: The strategy instance name
            initial_budget: The strategy's configured budget cap

        Returns:
            Recalculated budget state
        """
        # Get all trades for this strategy in chronological order
        cursor = self.conn.execute("""
            SELECT pnl FROM trade_history
            WHERE strategy = ? AND pnl IS NOT NULL
            ORDER BY exit_time ASC
        """, (strategy_name,))

        drawdown = 0.0
        for row in cursor.fetchall():
            pnl = row['pnl']
            drawdown = max(0, drawdown - pnl)

        # Calculate committed from open positions
        cursor = self.conn.execute("""
            SELECT entry_price, quantity FROM positions
            WHERE strategy = ? AND status IN ('open', 'pending_fill')
        """, (strategy_name,))

        committed = 0.0
        for row in cursor.fetchall():
            committed += row['entry_price'] * row['quantity'] * 100

        # Update or insert the budget record
        self.conn.execute("""
            INSERT INTO strategy_budgets (strategy_name, budget, drawdown, committed)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(strategy_name) DO UPDATE SET
                budget = excluded.budget,
                drawdown = excluded.drawdown,
                committed = excluded.committed,
                updated_at = datetime('now')
        """, (strategy_name, initial_budget, drawdown, committed))
        self.conn.commit()

        available = initial_budget - drawdown - committed
        logger.info(f"Recalculated budget for '{strategy_name}' from history: "
                    f"drawdown=${drawdown:.2f}, committed=${committed:.2f}, "
                    f"available=${available:.2f}")
        # This should never be None since we just inserted/updated
        result = self.get_strategy_budget(strategy_name)
        assert result is not None
        return result

    # =========================================================================
    # Historical Bar Caching
    # =========================================================================

    def cache_historical_bars(self, symbol: str, bar_size: str, bars: List) -> int:
        """
        Cache historical bars, replacing existing data for this symbol/bar_size.

        Args:
            symbol: Stock ticker symbol
            bar_size: Bar size string (e.g., '15 mins')
            bars: List of BarData objects from IB API with attributes:
                  date, open, high, low, close, volume

        Returns:
            Number of bars cached
        """
        if not bars:
            return 0

        # Delete existing bars for this symbol/bar_size
        self.conn.execute(
            "DELETE FROM historical_bars WHERE symbol = ? AND bar_size = ?",
            (symbol, bar_size)
        )

        # Insert new bars
        count = 0
        for bar in bars:
            try:
                # BarData.date can be datetime or date object
                timestamp = bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date)
                self.conn.execute("""
                    INSERT INTO historical_bars (symbol, bar_size, timestamp, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (symbol, bar_size, timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume))
                count += 1
            except Exception as e:
                logger.warning(f"Error caching bar for {symbol}: {e}")

        self.conn.commit()
        logger.info(f"Cached {count} historical bars for {symbol} ({bar_size})")
        return count

    def get_cached_bars(self, symbol: str, bar_size: str,
                        max_age_hours: int = 24) -> Optional[List[Dict[str, Any]]]:
        """
        Get cached historical bars if fresh enough.

        Args:
            symbol: Stock ticker symbol
            bar_size: Bar size string (e.g., '15 mins')
            max_age_hours: Maximum age of cache in hours

        Returns:
            List of bar dicts with keys: timestamp, open, high, low, close, volume
            Returns None if cache is stale or empty
        """
        # Check if we have fresh data
        cursor = self.conn.execute("""
            SELECT MAX(fetched_at) as last_fetch
            FROM historical_bars
            WHERE symbol = ? AND bar_size = ?
        """, (symbol, bar_size))

        row = cursor.fetchone()
        if not row or not row['last_fetch']:
            return None

        # Check age
        last_fetch = datetime.fromisoformat(row['last_fetch'])
        age_hours = (datetime.now() - last_fetch).total_seconds() / 3600

        if age_hours > max_age_hours:
            logger.debug(f"Historical bars cache for {symbol} is stale ({age_hours:.1f}h old)")
            return None

        # Fetch cached bars
        cursor = self.conn.execute("""
            SELECT timestamp, open, high, low, close, volume
            FROM historical_bars
            WHERE symbol = ? AND bar_size = ?
            ORDER BY timestamp ASC
        """, (symbol, bar_size))

        bars = []
        for row in cursor.fetchall():
            bars.append({
                'timestamp': datetime.fromisoformat(row['timestamp']),
                'open': row['open'],
                'high': row['high'],
                'low': row['low'],
                'close': row['close'],
                'volume': row['volume'],
            })

        if bars:
            logger.debug(f"Retrieved {len(bars)} cached bars for {symbol} ({bar_size})")

        return bars if bars else None

    def clear_historical_cache(self, symbol: Optional[str] = None,
                               bar_size: Optional[str] = None) -> int:
        """
        Clear historical bar cache.

        Args:
            symbol: Clear only this symbol (all if None)
            bar_size: Clear only this bar size (all if None)

        Returns:
            Number of rows deleted
        """
        if symbol and bar_size:
            cursor = self.conn.execute(
                "DELETE FROM historical_bars WHERE symbol = ? AND bar_size = ?",
                (symbol, bar_size)
            )
        elif symbol:
            cursor = self.conn.execute(
                "DELETE FROM historical_bars WHERE symbol = ?",
                (symbol,)
            )
        elif bar_size:
            cursor = self.conn.execute(
                "DELETE FROM historical_bars WHERE bar_size = ?",
                (bar_size,)
            )
        else:
            cursor = self.conn.execute("DELETE FROM historical_bars")

        self.conn.commit()
        count = cursor.rowcount
        logger.info(f"Cleared {count} historical bar cache entries")
        return count

    # =========================================================================
    # Trade Query & Reporting
    # =========================================================================

    def query_trades(
        self,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        direction: Optional[str] = None,
        pattern: Optional[str] = None,
        exit_reason: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        winners_only: bool = False,
        losers_only: bool = False,
        min_pnl: Optional[float] = None,
        max_pnl: Optional[float] = None,
        limit: int = 1000,
        offset: int = 0,
        order_by: str = 'exit_time',
        descending: bool = True,
    ) -> List[sqlite3.Row]:
        """
        Query trade history with flexible filtering.

        Args:
            symbol: Filter by underlying symbol (e.g., 'NVDA')
            strategy: Filter by strategy name
            direction: Filter by direction ('bullish' or 'bearish')
            pattern: Filter by pattern name
            exit_reason: Filter by exit reason
            start_date: Filter trades with exit_time >= start_date (ISO format)
            end_date: Filter trades with exit_time <= end_date (ISO format)
            winners_only: Only return profitable trades
            losers_only: Only return losing trades
            min_pnl: Minimum P&L filter
            max_pnl: Maximum P&L filter
            limit: Maximum number of results
            offset: Skip first N results (for pagination)
            order_by: Column to sort by
            descending: Sort descending if True

        Returns:
            List of trade rows matching criteria
        """
        conditions = []
        params = []

        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)

        if strategy:
            conditions.append("strategy = ?")
            params.append(strategy)

        if direction:
            conditions.append("direction = ?")
            params.append(direction)

        if pattern:
            conditions.append("pattern = ?")
            params.append(pattern)

        if exit_reason:
            conditions.append("exit_reason = ?")
            params.append(exit_reason)

        if start_date:
            conditions.append("exit_time >= ?")
            params.append(start_date)

        if end_date:
            conditions.append("exit_time <= ?")
            params.append(end_date)

        if winners_only:
            conditions.append("pnl > 0")

        if losers_only:
            conditions.append("pnl <= 0")

        if min_pnl is not None:
            conditions.append("pnl >= ?")
            params.append(min_pnl)

        if max_pnl is not None:
            conditions.append("pnl <= ?")
            params.append(max_pnl)

        # Build query
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        order_direction = "DESC" if descending else "ASC"

        # Validate order_by to prevent SQL injection
        valid_columns = {
            'id', 'symbol', 'local_symbol', 'strategy', 'direction', 'pattern',
            'entry_price', 'exit_price', 'entry_time', 'exit_time',
            'pnl', 'pnl_pct', 'quantity', 'exit_reason'
        }
        if order_by not in valid_columns:
            order_by = 'exit_time'

        query = f"""
            SELECT * FROM trade_history
            WHERE {where_clause}
            ORDER BY {order_by} {order_direction}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        cursor = self.conn.execute(query, params)
        return cursor.fetchall()

    def count_trades(
        self,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> int:
        """Count trades matching criteria (useful for pagination)."""
        conditions = []
        params = []

        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if strategy:
            conditions.append("strategy = ?")
            params.append(strategy)
        if start_date:
            conditions.append("exit_time >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("exit_time <= ?")
            params.append(end_date)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        cursor = self.conn.execute(
            f"SELECT COUNT(*) as count FROM trade_history WHERE {where_clause}",
            params
        )
        return cursor.fetchone()['count']

    def get_performance_metrics(
        self,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        exclude_manual: bool = True,
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive performance metrics.

        Args:
            symbol: Filter by symbol
            strategy: Filter by strategy
            start_date: Start date filter (ISO format)
            end_date: End date filter (ISO format)
            exclude_manual: Exclude manual closes and reconciliation entries

        Returns:
            Dict with performance metrics:
            - total_trades, winners, losers
            - win_rate, loss_rate
            - total_pnl, avg_pnl, avg_pnl_pct
            - avg_winner, avg_loser
            - largest_winner, largest_loser
            - profit_factor (gross profit / gross loss)
            - avg_hold_time_hours
            - best_trade, worst_trade (full trade details)
        """
        conditions = ["pnl IS NOT NULL"]
        params = []

        if exclude_manual:
            conditions.append("exit_reason NOT IN ('manual_close', 'reconciliation_not_found')")

        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)

        if strategy:
            conditions.append("strategy = ?")
            params.append(strategy)

        if start_date:
            conditions.append("exit_time >= ?")
            params.append(start_date)

        if end_date:
            conditions.append("exit_time <= ?")
            params.append(end_date)

        where_clause = " AND ".join(conditions)

        # Get aggregate metrics
        cursor = self.conn.execute(f"""
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winners,
                SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losers,
                COALESCE(SUM(pnl), 0) as total_pnl,
                COALESCE(AVG(pnl), 0) as avg_pnl,
                COALESCE(AVG(pnl_pct), 0) as avg_pnl_pct,
                COALESCE(AVG(CASE WHEN pnl > 0 THEN pnl END), 0) as avg_winner,
                COALESCE(AVG(CASE WHEN pnl <= 0 THEN pnl END), 0) as avg_loser,
                COALESCE(MAX(pnl), 0) as largest_winner,
                COALESCE(MIN(pnl), 0) as largest_loser,
                COALESCE(SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END), 0) as gross_profit,
                COALESCE(SUM(CASE WHEN pnl < 0 THEN ABS(pnl) ELSE 0 END), 0) as gross_loss
            FROM trade_history
            WHERE {where_clause}
        """, params)

        row = cursor.fetchone()
        total_trades = row['total_trades'] or 0
        winners = row['winners'] or 0
        losers = row['losers'] or 0

        # Calculate derived metrics
        win_rate = (winners / total_trades * 100) if total_trades > 0 else 0
        loss_rate = (losers / total_trades * 100) if total_trades > 0 else 0
        profit_factor = (row['gross_profit'] / row['gross_loss']) if row['gross_loss'] > 0 else float('inf') if row['gross_profit'] > 0 else 0

        # Get best and worst trades
        best_trade = None
        worst_trade = None
        if total_trades > 0:
            cursor = self.conn.execute(f"""
                SELECT * FROM trade_history
                WHERE {where_clause}
                ORDER BY pnl DESC LIMIT 1
            """, params)
            best_row = cursor.fetchone()
            if best_row:
                best_trade = dict(best_row)

            cursor = self.conn.execute(f"""
                SELECT * FROM trade_history
                WHERE {where_clause}
                ORDER BY pnl ASC LIMIT 1
            """, params)
            worst_row = cursor.fetchone()
            if worst_row:
                worst_trade = dict(worst_row)

        # Calculate average hold time
        cursor = self.conn.execute(f"""
            SELECT AVG(
                (julianday(exit_time) - julianday(entry_time)) * 24
            ) as avg_hold_hours
            FROM trade_history
            WHERE {where_clause}
        """, params)
        avg_hold_row = cursor.fetchone()
        avg_hold_hours = avg_hold_row['avg_hold_hours'] or 0

        return {
            'total_trades': total_trades,
            'winners': winners,
            'losers': losers,
            'win_rate': round(win_rate, 2),
            'loss_rate': round(loss_rate, 2),
            'total_pnl': round(row['total_pnl'] or 0, 2),
            'avg_pnl': round(row['avg_pnl'] or 0, 2),
            'avg_pnl_pct': round(row['avg_pnl_pct'] or 0, 2),
            'avg_winner': round(row['avg_winner'] or 0, 2),
            'avg_loser': round(row['avg_loser'] or 0, 2),
            'largest_winner': round(row['largest_winner'] or 0, 2),
            'largest_loser': round(row['largest_loser'] or 0, 2),
            'gross_profit': round(row['gross_profit'] or 0, 2),
            'gross_loss': round(row['gross_loss'] or 0, 2),
            'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 'inf',
            'avg_hold_hours': round(avg_hold_hours, 2),
            'best_trade': best_trade,
            'worst_trade': worst_trade,
        }

    def get_daily_pnl(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get P&L aggregated by day.

        Returns:
            List of dicts with date, trade_count, pnl, cumulative_pnl
        """
        conditions = ["pnl IS NOT NULL"]
        params = []

        if start_date:
            conditions.append("exit_time >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("exit_time <= ?")
            params.append(end_date)
        if strategy:
            conditions.append("strategy = ?")
            params.append(strategy)

        where_clause = " AND ".join(conditions)

        cursor = self.conn.execute(f"""
            SELECT
                DATE(exit_time) as trade_date,
                COUNT(*) as trade_count,
                SUM(pnl) as daily_pnl,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses
            FROM trade_history
            WHERE {where_clause}
            GROUP BY DATE(exit_time)
            ORDER BY trade_date ASC
        """, params)

        results = []
        cumulative = 0
        for row in cursor.fetchall():
            cumulative += row['daily_pnl']
            results.append({
                'date': row['trade_date'],
                'trade_count': row['trade_count'],
                'wins': row['wins'],
                'losses': row['losses'],
                'daily_pnl': round(row['daily_pnl'], 2),
                'cumulative_pnl': round(cumulative, 2),
            })

        return results

    def get_today_realized_pnl(self, strategy: Optional[str] = None) -> float:
        """Get total realized P&L for the current day (local time)."""
        today = datetime.now().date().isoformat()
        
        query = "SELECT SUM(pnl) as total_pnl FROM trade_history WHERE DATE(exit_time) = ?"
        params = [today]
        
        if strategy:
            query += " AND strategy = ?"
            params.append(strategy)
            
        cursor = self.conn.execute(query, params)
        row = cursor.fetchone()
        return row['total_pnl'] or 0.0

    def get_consecutive_losses(self, strategy: Optional[str] = None) -> int:
        """
        Count consecutive losses (pnl < 0) from most recent trades backwards.
        Excludes manual closes and reconciliation entries.
        """
        conditions = ["pnl IS NOT NULL", "exit_reason NOT IN ('manual_close', 'reconciliation_not_found')"]
        params = []

        if strategy:
            conditions.append("strategy = ?")
            params.append(strategy)

        where_clause = " AND ".join(conditions)
        
        # Get most recent 50 trades to check for streak
        query = f"""
            SELECT pnl FROM trade_history 
            WHERE {where_clause}
            ORDER BY exit_time DESC LIMIT 50
        """
        cursor = self.conn.execute(query, params)
        
        losses = 0
        for row in cursor.fetchall():
            if row['pnl'] < 0:
                losses += 1
            else:
                break
        return losses

    def get_symbol_breakdown(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get P&L breakdown by symbol."""
        conditions = ["pnl IS NOT NULL"]
        params = []

        if start_date:
            conditions.append("exit_time >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("exit_time <= ?")
            params.append(end_date)

        where_clause = " AND ".join(conditions)

        cursor = self.conn.execute(f"""
            SELECT
                symbol,
                COUNT(*) as trade_count,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losses,
                SUM(pnl) as total_pnl,
                AVG(pnl) as avg_pnl
            FROM trade_history
            WHERE {where_clause}
            GROUP BY symbol
            ORDER BY total_pnl DESC
        """, params)

        return [
            {
                'symbol': row['symbol'],
                'trade_count': row['trade_count'],
                'wins': row['wins'],
                'losses': row['losses'],
                'win_rate': round(row['wins'] / row['trade_count'] * 100, 1) if row['trade_count'] > 0 else 0,
                'total_pnl': round(row['total_pnl'], 2),
                'avg_pnl': round(row['avg_pnl'], 2),
            }
            for row in cursor.fetchall()
        ]

    # =========================================================================
    # CSV Export
    # =========================================================================

    def export_trades_to_csv(
        self,
        filepath: str,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        include_all: bool = False,
    ) -> int:
        """
        Export trade history to CSV file.

        Args:
            filepath: Output CSV file path
            symbol: Filter by symbol
            strategy: Filter by strategy
            start_date: Filter by start date
            end_date: Filter by end date
            include_all: Include manual closes and reconciliation entries

        Returns:
            Number of trades exported
        """
        import csv

        # Query trades with filters
        conditions = []
        params = []

        if not include_all:
            conditions.append("exit_reason NOT IN ('manual_close', 'reconciliation_not_found', 'order_cancelled', 'order_no_fills')")

        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if strategy:
            conditions.append("strategy = ?")
            params.append(strategy)
        if start_date:
            conditions.append("exit_time >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("exit_time <= ?")
            params.append(end_date)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        cursor = self.conn.execute(f"""
            SELECT * FROM trade_history
            WHERE {where_clause}
            ORDER BY exit_time ASC
        """, params)

        rows = cursor.fetchall()
        if not rows:
            logger.info("No trades to export")
            return 0

        # Define CSV columns (human-friendly order)
        columns = [
            'id', 'symbol', 'local_symbol', 'direction', 'pattern', 'strategy',
            'quantity', 'entry_price', 'exit_price', 'entry_time', 'exit_time',
            'exit_reason', 'pnl', 'pnl_pct', 'strike', 'expiry', 'right',
            'con_id', 'order_ref', 'entry_order_id', 'exit_order_id'
        ]

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(columns)

            for row in rows:
                writer.writerow([row[col] if col in row.keys() else '' for col in columns])

        logger.info(f"Exported {len(rows)} trades to {filepath}")
        return len(rows)

    def export_performance_report(
        self,
        filepath: str,
        strategy: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> None:
        """
        Export a comprehensive performance report to CSV.

        Includes:
        - Summary metrics
        - Daily P&L
        - Symbol breakdown
        - Strategy breakdown
        """
        import csv

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow(['TRADING BOT PERFORMANCE REPORT'])
            writer.writerow([f'Generated: {datetime.now().isoformat()}'])
            if start_date or end_date:
                writer.writerow([f'Period: {start_date or "start"} to {end_date or "now"}'])
            if strategy:
                writer.writerow([f'Strategy: {strategy}'])
            writer.writerow([])

            # Summary metrics
            metrics = self.get_performance_metrics(
                strategy=strategy, start_date=start_date, end_date=end_date
            )

            writer.writerow(['=== SUMMARY METRICS ==='])
            writer.writerow(['Metric', 'Value'])
            writer.writerow(['Total Trades', metrics['total_trades']])
            writer.writerow(['Winners', metrics['winners']])
            writer.writerow(['Losers', metrics['losers']])
            writer.writerow(['Win Rate %', metrics['win_rate']])
            writer.writerow(['Total P&L', f"${metrics['total_pnl']:.2f}"])
            writer.writerow(['Average P&L', f"${metrics['avg_pnl']:.2f}"])
            writer.writerow(['Average P&L %', f"{metrics['avg_pnl_pct']:.2f}%"])
            writer.writerow(['Average Winner', f"${metrics['avg_winner']:.2f}"])
            writer.writerow(['Average Loser', f"${metrics['avg_loser']:.2f}"])
            writer.writerow(['Largest Winner', f"${metrics['largest_winner']:.2f}"])
            writer.writerow(['Largest Loser', f"${metrics['largest_loser']:.2f}"])
            writer.writerow(['Profit Factor', metrics['profit_factor']])
            writer.writerow(['Avg Hold Time (hours)', metrics['avg_hold_hours']])
            writer.writerow([])

            # Daily P&L
            writer.writerow(['=== DAILY P&L ==='])
            writer.writerow(['Date', 'Trades', 'Wins', 'Losses', 'Daily P&L', 'Cumulative P&L'])
            daily = self.get_daily_pnl(start_date=start_date, end_date=end_date, strategy=strategy)
            for day in daily:
                writer.writerow([
                    day['date'], day['trade_count'], day['wins'], day['losses'],
                    f"${day['daily_pnl']:.2f}", f"${day['cumulative_pnl']:.2f}"
                ])
            writer.writerow([])

            # Symbol breakdown
            writer.writerow(['=== SYMBOL BREAKDOWN ==='])
            writer.writerow(['Symbol', 'Trades', 'Wins', 'Losses', 'Win Rate %', 'Total P&L', 'Avg P&L'])
            symbols = self.get_symbol_breakdown(start_date=start_date, end_date=end_date)
            for sym in symbols:
                writer.writerow([
                    sym['symbol'], sym['trade_count'], sym['wins'], sym['losses'],
                    f"{sym['win_rate']:.1f}%", f"${sym['total_pnl']:.2f}", f"${sym['avg_pnl']:.2f}"
                ])
            writer.writerow([])

            # Strategy breakdown (if not filtering by strategy)
            if not strategy:
                writer.writerow(['=== STRATEGY BREAKDOWN ==='])
                writer.writerow(['Strategy', 'Trades', 'Wins', 'Losses', 'Win Rate %', 'Total P&L', 'Avg P&L'])
                by_strategy = self.get_pnl_by_strategy()
                for strat_name, stats in by_strategy.items():
                    win_rate = (stats['wins'] / stats['total_trades'] * 100) if stats['total_trades'] > 0 else 0
                    writer.writerow([
                        strat_name, stats['total_trades'], stats['wins'], stats['losses'],
                        f"{win_rate:.1f}%", f"${stats['total_pnl']:.2f}", f"${stats['avg_pnl']:.2f}"
                    ])

        logger.info(f"Exported performance report to {filepath}")
