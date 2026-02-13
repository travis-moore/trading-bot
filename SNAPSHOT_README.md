# Market Snapshot & Analysis System

The Market Snapshot system captures the exact state of the market (Order Book, Price, Account) at critical moments during the trading lifecycle. This data is essential for analyzing **Slippage**, **Execution Latency**, and **Execution Quality**.

## 1. Configuration

The system is **enabled by default** in the `TradingEngine`.

- **Storage Location**: Snapshots are saved as JSON files in the `snapshots/` directory.
- **Naming Convention**: `YYYYMMDD_HHMMSS_microseconds_Ticker_Phase_TradeID.json`
- **Performance**: Snapshots are saved asynchronously in a separate thread to prevent blocking the trading loop.

No additional configuration in `config.yaml` is required.

## 2. How It Works

The system records two snapshots for every trade:

1.  **Signal Phase (`signal_phase`)**:
    *   **Trigger**: Recorded immediately when the bot decides to enter a trade (before the order is sent).
    *   **Purpose**: Captures the "theoretical" entry price and the liquidity available at that moment.
    *   **Data**: Top 10 levels of Bid/Ask, Spread, Market Regime, Account Balance, Timestamp.

2.  **Execution Phase (`execution_phase`)**:
    *   **Trigger**: Recorded immediately after the order is filled by the broker.
    *   **Purpose**: Captures the "actual" fill price and the state of the book after your order hit it.
    *   **Data**: Fill Price, Trade Size, Execution Latency, Fresh Order Book state.

## 3. Usage: Analyzing Slippage

A utility script `snapshot_analyzer.py` is provided to compare these two snapshots and calculate slippage.

### Command
```bash
python snapshot_analyzer.py <TRADE_ID>
```

*Replace `<TRADE_ID>` with the Order Reference found in your logs or database (e.g., `SWINGBOT-1739500000-1`).*

### Interpreting the Output

```text
--- Trade Analysis: SWINGBOT-1739500000-1 ---
Asset: NVDA
Signal Time: 2024-02-14T10:30:01.123456
Best Ask at Signal: $740.50
Actual Fill Price:  $740.55
Slippage:           $0.05 (+0.01%)
Latency:            450 ms
Spread (Signal):    5.2 bps
Market Regime:      high_volatility
Trade Size: 5
Top Level Liquidity: 2
WARNING: Trade size exceeded top level liquidity (likely caused slippage)

--- Order Book Wall Visualization ---
$740.50:    2 
$740.55:  100 ██████████ (FILLED)
```

- **Slippage**: The difference between the price you expected (Best Ask at Signal) and the price you got (Fill Price). Positive slippage means you paid more than expected.
- **Liquidity Warning**: If your `Trade Size` > `Top Level Liquidity`, you likely ate through the first level of the order book, causing immediate slippage. This indicates your position size might be too large for the current market depth.

## 4. Data Schema

Each snapshot JSON contains:

```json
{
  "timestamp": "ISO-8601 Timestamp",
  "asset_ticker": "Symbol",
  "best_bid": 100.00,
  "best_ask": 100.05,
  "order_book_depth": {"bids": [{"price": 100.00, "size": 500}, ...], "asks": [...]},
  "phase": "signal_phase" | "execution_phase",
  "trade_id": "Unique Order Ref"
}
```