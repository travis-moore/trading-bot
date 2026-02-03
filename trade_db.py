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
        """)
        self.conn.commit()
        self._migrate_add_strategy_column()

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

        cursor = self.conn.execute("""
            INSERT INTO positions (
                symbol, local_symbol, con_id, strike, expiry, right, exchange,
                entry_price, entry_time, quantity, direction,
                stop_loss, profit_target, pattern, strategy,
                entry_order_id, order_ref, status
            ) VALUES (
                :symbol, :local_symbol, :con_id, :strike, :expiry, :right, :exchange,
                :entry_price, :entry_time, :quantity, :direction,
                :stop_loss, :profit_target, :pattern, :strategy,
                :entry_order_id, :order_ref, :status
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

    # --- Trade History ---

    def close_position(self, position_id: int, exit_price: float,
                       exit_reason: str, exit_order_id: Optional[int] = None):
        """
        Atomically move an open position to trade_history and delete from positions.
        """
        row = self.conn.execute(
            "SELECT * FROM positions WHERE id = ?", (position_id,)
        ).fetchone()

        if not row:
            logger.warning(f"Position id={position_id} not found in DB")
            return

        # Calculate P&L
        pnl = None
        pnl_pct = None
        if exit_price and exit_price > 0 and row['entry_price'] > 0:
            pnl = (exit_price - row['entry_price']) * row['quantity'] * 100
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
                f"Closed position id={position_id}: {row['local_symbol']} "
                f"reason={exit_reason} pnl={pnl}"
            )
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
