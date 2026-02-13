import json
import os
import threading
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

@dataclass
class MarketSnapshot:
    """
    Captures market state at a specific moment for analysis.
    """
    timestamp: str
    asset_ticker: str
    best_bid: float
    best_ask: float
    order_book_depth: Dict[str, List[Dict[str, Any]]]  # {'bids': [{'price': float, 'size': int}], 'asks': []}
    rsi_14: Optional[float]
    account_balance: float
    phase: str  # 'signal_phase' or 'execution_phase'
    trade_id: Optional[str] = None
    fill_price: Optional[float] = None
    trade_size: Optional[int] = None
    spread_bps: Optional[float] = None
    execution_latency_ms: Optional[float] = None
    market_regime: Optional[str] = None
    side: Optional[str] = None  # 'BUY' or 'SELL'

    def to_dict(self):
        return asdict(self)

def record_snapshot(snapshot: MarketSnapshot, directory: str = "snapshots"):
    """Saves a MarketSnapshot to a JSON file asynchronously."""
    def _save():
        try:
            if not os.path.exists(directory):
                os.makedirs(directory)
            
            # Filename: timestamp_ticker_phase_tradeid.json
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            trade_id_suffix = f"_{snapshot.trade_id}" if snapshot.trade_id else ""
            filename = f"{directory}/{ts_str}_{snapshot.asset_ticker}_{snapshot.phase}{trade_id_suffix}.json"
            
            with open(filename, 'w') as f:
                json.dump(snapshot.to_dict(), f, indent=2)
                
            logger.info(f"Snapshot saved: {filename}")
        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}")

    threading.Thread(target=_save, daemon=True).start()