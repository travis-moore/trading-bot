# 🤖 Automated Options Trading System: Logic & Strategy

## 1. The Core Philosophy
Unlike standard bots that rely on lagging indicators (like Moving Averages or RSI) on a price chart, this system trades based on **Liquidity** and **Order Flow**. It looks at the "depth" of the market—the pending buy and sell orders—to identify where institutional players are positioning themselves before the price even moves.

<details>
<summary><strong>🔍 How it sees the market (The "X-Ray Vision")</strong></summary>

Most traders look at a line chart. This bot looks at the **Order Book** (Level 2 Data).

*   **The "Wall":** It identifies massive clusters of buy orders (Support) or sell orders (Resistance).
*   **The "Fake-out":** It uses statistical analysis to ignore "spoof" orders that disappear when price gets close.
*   **The "Imbalance":** It measures if buyers are being more aggressive than sellers in real-time.

<details>
<summary><strong>📉 Deep Dive: Liquidity Analysis Mechanics</strong></summary>

1.  **Z-Score Filtering:** The bot calculates the average volume at every price level. It only pays attention to levels that are statistically significant (e.g., > 3 standard deviations above normal). This filters out noise.
2.  **Time Persistence:** A "wall" of orders must sit there for at least 5 minutes to be considered real. Flash orders are ignored.
3.  **Exclusion Zone:** It ignores orders right next to the current price (Market Maker noise) to focus on the structural levels further out.

</details>
</details>

## 2. Trading Strategies

The bot runs multiple strategies simultaneously, acting like a team of traders where each has a specific specialty.

<details>
<summary><strong>🌊 Strategy A: Swing Trading (Support & Resistance)</strong></summary>

This strategy waits for price to hit a "wall" and bounce. It's like playing ping-pong against a brick wall.

*   **Bullish:** Price drops to a massive Buy Wall (Support). The wall holds. Price bounces up. -> **Buy Call Options**.
*   **Bearish:** Price rallies to a massive Sell Wall (Resistance). Buyers can't break through. Price rejects down. -> **Buy Put Options**.

<details>
<summary><strong>⚙️ Specific Entry Triggers</strong></summary>

*   **Rejection at Support:**
    *   Price enters the "Proximity Zone" (e.g., within 0.2% of the wall).
    *   Price ticks UP away from the wall.
    *   Order flow shows buyers stepping in (Positive Imbalance).
    *   **Action:** Buy Call.

*   **Absorption Breakout (The "Sledgehammer"):**
    *   Price hits a wall.
    *   The wall doesn't move, but volume is trading heavily (the wall is being "eaten").
    *   If the wall breaks -> **Trade with the breakout**.

</details>
</details>

<details>
<summary><strong>⚡ Strategy B: Scalping (Momentum)</strong></summary>

This strategy is for speed. It doesn't care about levels; it cares about **Aggression**.

*   **Concept:** If 80% of the orders in the book are Buys, price is likely to tick up in the next few seconds/minutes.
*   **Action:** Jump in, grab a small profit, jump out.

<details>
<summary><strong>⏱️ The "Time Decay" Exit</strong></summary>

Scalping is dangerous if price stalls.
*   **The Rule:** If the trade doesn't move in our favor within **5 ticks** (price changes), the bot exits immediately.
*   **Why?** Momentum trades rely on speed. If it stops, the edge is gone.

</details>
</details>

<details>
<summary><strong>📊 Strategy C: VIX Momentum (Market Sentiment)</strong></summary>

This strategy watches the "Fear Gauge" (VIX) to confirm moves in the indices (QQQ/SPY).

*   **The Setup:** It marks the high and low price of the first 15 minutes of trading (9:30-9:45 AM).
*   **The Trigger:** If price breaks that range *AND* the VIX confirms it.

<details>
<summary><strong>✅ Confirmation Logic</strong></summary>

*   **Bullish Breakout:** Stock Price > 15-min High **AND** VIX is crashing (Fear is dropping).
*   **Bearish Breakout:** Stock Price < 15-min Low **AND** VIX is spiking (Fear is rising).
*   **The Filter:** If Stock goes UP but VIX also goes UP (Divergence), the bot stays out. It's a trap.

</details>
</details>

## 3. Risk Management & Safety

The bot is paranoid by design. It assumes every trade could be a loser.

<details>
<summary><strong>🛡️ The Safety Nets</strong></summary>

1.  **Position Sizing:** It never bets more than X% of the account (e.g., 2%) on a single trade.
2.  **Bracket Orders:** Every time it buys an option, it *instantly* places two sell orders:
    *   **Profit Target:** Sell if we make 50%.
    *   **Stop Loss:** Sell if we lose 30%.
    *   *One cancels the other automatically.*

<details>
<summary><strong>🌍 Market Regime Filters</strong></summary>

The bot checks the "weather" before going outside.

*   **"High Chaos" Mode:** If VIX > 30 or spiking violently, it blocks all standard strategies. Only specific "crash" strategies are allowed.
*   **"Sector Rotation":** Before buying a Tech stock (e.g., NVDA), it checks if the Tech Sector (XLK) is outperforming the market (SPY). If the sector is weak, it vetoes the trade.

</details>
</details>

---
*Generated for engineering review - focuses on logic flow rather than implementation details.*