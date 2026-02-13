import json
import glob
import sys
from typing import Dict, Any

class SnapshotAnalyzer:
    def __init__(self, snapshots_dir: str = "snapshots"):
        self.snapshots_dir = snapshots_dir

    def load_snapshot(self, filepath: str) -> Dict[str, Any]:
        with open(filepath, 'r') as f:
            return json.load(f)

    def analyze_trade_slippage(self, trade_id: str):
        """
        Analyzes slippage for a specific trade ID by comparing signal and execution snapshots.
        """
        # Find files for this trade ID
        pattern = f"{self.snapshots_dir}/*_{trade_id}.json"
        files = glob.glob(pattern)
        
        signal_snap = None
        exec_snap = None
        
        for f in files:
            data = self.load_snapshot(f)
            if data.get('phase') == 'signal_phase':
                signal_snap = data
            elif data.get('phase') == 'execution_phase':
                exec_snap = data
        
        if not signal_snap or not exec_snap:
            print(f"Incomplete snapshots for trade {trade_id}")
            return

        # Calculate Slippage
        # Determine side (default to BUY for backward compatibility)
        side = exec_snap.get('side', 'BUY')
        fill_price = exec_snap.get('fill_price')
        
        # Determine expected price based on side
        # BUY: We pay the Ask. Slippage = Fill - Ask (Positive is bad)
        # SELL: We sell at Bid. Slippage = Bid - Fill (Positive is bad)
        if side == 'BUY':
            expected_price = signal_snap.get('best_ask')
            slippage = (fill_price - expected_price) if (fill_price and expected_price) else 0
        else:
            expected_price = signal_snap.get('best_bid')
            slippage = (expected_price - fill_price) if (fill_price and expected_price) else 0
        
        if expected_price and fill_price:
            slippage_pct = (slippage / expected_price) * 100
            
            print(f"--- Trade Analysis: {trade_id} ---")
            print(f"Asset: {signal_snap.get('asset_ticker', 'Unknown')}")
            print(f"Side: {side}")
            print(f"Signal Time: {signal_snap.get('timestamp', 'Unknown')}")
            print(f"Expected Price ({'Ask' if side == 'BUY' else 'Bid'}): ${expected_price:.2f}")
            print(f"Actual Fill Price:  ${fill_price:.2f}")
            print(f"Slippage:           ${slippage:.2f} ({slippage_pct:+.2f}%)")

            if exec_snap.get('execution_latency_ms'):
                print(f"Latency:            {exec_snap['execution_latency_ms']:.0f} ms")
            if signal_snap.get('spread_bps'):
                print(f"Spread (Signal):    {signal_snap['spread_bps']:.1f} bps")
            if signal_snap.get('market_regime'):
                print(f"Market Regime:      {signal_snap['market_regime']}")
            
            # Check Depth
            trade_size = exec_snap.get('trade_size', 0)
            
            # If BUYing, we eat Asks. If SELLing, we eat Bids.
            book_side = 'asks' if side == 'BUY' else 'bids'
            levels = signal_snap.get('order_book_depth', {}).get(book_side, [])
            
            if levels:
                top_level_qty = levels[0].get('size', 0)
                print(f"Trade Size: {trade_size}")
                print(f"Top Level Liquidity: {top_level_qty}")
                if trade_size > top_level_qty:
                    print("WARNING: Trade size exceeded top level liquidity (likely caused slippage)")
                    
                    # Visualize the wall
                    print("\n--- Order Book Wall Visualization ---")
                    
                    # Calculate max quantity for scaling
                    max_qty = max((level.get('size', 0) for level in levels), default=1)
                    
                    remaining = trade_size
                    for level in levels:
                        qty = level.get('size', 0)
                        price = level.get('price', 0)
                        eaten = min(remaining, qty)
                        
                        # Scaled bar chart (max 20 chars)
                        bar_len = int((qty / max_qty) * 20)
                        bar = '█' * bar_len
                        
                        print(f"${price:.2f}: {qty:>4} {bar:<20} {'(FILLED)' if eaten > 0 else ''}")
                        remaining -= eaten
                        if remaining <= 0:
                            break
                else:
                    print("Liquidity Condition: Sufficient at top level")
        else:
            print("Missing price data for calculation.")

    def generate_global_report(self):
        """
        Scans all snapshots and generates a summary of execution quality.
        """
        try:
            import pandas as pd
        except ImportError:
            print("Error: pandas is required for global reporting. Please install it: pip install pandas")
            return

        all_files = glob.glob(f"{self.snapshots_dir}/*.json")
        trades = {}

        # Group files by Trade ID
        for f in all_files:
            try:
                data = self.load_snapshot(f)
                tid = data.get('trade_id')
                if tid:
                    if tid not in trades: trades[tid] = {}
                    trades[tid][data.get('phase')] = data
            except Exception:
                continue

        report_data = []

        for tid, phases in trades.items():
            if 'signal_phase' in phases and 'execution_phase' in phases:
                sig = phases['signal_phase']
                exe = phases['execution_phase']
                
                # Logic handles both Buy/Sell
                side = sig.get('side', 'BUY').upper()
                fill_price = exe.get('fill_price')
                
                if fill_price is None:
                    continue

                # Calculate slippage (Positive = Bad)
                if side == 'BUY':
                    expected = sig.get('best_ask', 0)
                    slippage = fill_price - expected if expected else 0
                else:
                    expected = sig.get('best_bid', 0)
                    slippage = expected - fill_price if expected else 0
                
                report_data.append({
                    'trade_id': tid,
                    'asset': sig.get('asset_ticker', 'Unknown'),
                    'slippage_usd': slippage,
                    'latency_ms': exe.get('execution_latency_ms', 0),
                    'regime': sig.get('market_regime', 'unknown'),
                    'spread_bps': sig.get('spread_bps', 0)
                })

        if not report_data:
            print("No complete trade snapshots found.")
            return

        df = pd.DataFrame(report_data)
        
        print("\n=== GLOBAL EXECUTION QUALITY REPORT ===")
        print(f"Total Trades Analyzed: {len(df)}")
        print(f"Avg Slippage: ${df['slippage_usd'].mean():.4f}")
        print(f"Avg Latency:   {df['latency_ms'].mean():.1f} ms")
        
        print("\n--- Slippage by Market Regime ---")
        if 'regime' in df.columns:
            print(df.groupby('regime')['slippage_usd'].mean())
        
        # This helps you see if your latency is actually causing the slippage
        if len(df) > 1 and df['latency_ms'].std() > 0 and df['slippage_usd'].std() > 0:
            correlation = df['latency_ms'].corr(df['slippage_usd'])
            print(f"\nLatency/Slippage Correlation: {correlation:.2f}")

if __name__ == "__main__":
    analyzer = SnapshotAnalyzer()
    if len(sys.argv) > 1:
        if sys.argv[1] == "--report":
            analyzer.generate_global_report()
        else:
            analyzer.analyze_trade_slippage(sys.argv[1])
    else:
        print("Usage:")
        print("  python snapshot_analyzer.py <trade_id>   # Analyze specific trade")
        print("  python snapshot_analyzer.py --report     # Generate global report")