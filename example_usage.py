#!/usr/bin/env python3
"""
Example: Manual Trading with Bot Components

This shows how to use the bot components interactively
without running the full automated bot.
"""

from ib_wrapper import IBWrapper
from liquidity_analyzer import LiquidityAnalyzer
from trading_engine import TradingEngine
import time


def example_manual_analysis():
    """
    Example: Manually analyze a stock and make trading decisions
    """
    print("=" * 60)
    print("MANUAL TRADING EXAMPLE")
    print("=" * 60)
    
    # 1. Connect to IB
    print("\n1. Connecting to Interactive Brokers...")
    ib = IBWrapper(host='127.0.0.1', port=7497, client_id=1)
    
    if not ib.connect():
        print("Failed to connect. Make sure TWS/Gateway is running.")
        return
    
    print("✓ Connected")
    
    # 2. Get current stock price
    symbol = "NVDA"
    print(f"\n2. Getting current price for {symbol}...")
    price = ib.get_stock_price(symbol)
    
    if price:
        print(f"✓ Current price: ${price:.2f}")
    else:
        print("Failed to get price")
        ib.disconnect()
        return
    
    # 3. Subscribe to market depth
    print(f"\n3. Subscribing to market depth...")
    ticker = ib.subscribe_market_depth(symbol, num_rows=10)
    
    if not ticker:
        print("Failed to subscribe. Check if you have market data subscription.")
        ib.disconnect()
        return
    
    print("✓ Subscribed. Waiting for depth data...")
    time.sleep(3)  # Wait for data to populate
    
    # 4. Analyze order book
    print(f"\n4. Analyzing order book...")
    
    config = {
        'liquidity_threshold': 1000,
        'zone_proximity': 0.10,
        'imbalance_threshold': 0.6,
        'num_levels': 10
    }
    
    analyzer = LiquidityAnalyzer(config)
    analysis = analyzer.analyze_book(ticker)
    
    print(f"\nOrder Book Analysis:")
    print(f"  Bid depth: {analysis['bid_depth_total']:,} shares")
    print(f"  Ask depth: {analysis['ask_depth_total']:,} shares")
    print(f"  Imbalance: {analysis['imbalance']:.2%}")
    
    if analysis['support']:
        print(f"\n  Support zones found: {len(analysis['support'])}")
        for i, zone in enumerate(analysis['support'][:3], 1):
            print(f"    {i}. ${zone.price:.2f} ({zone.size:,} shares, strength: {zone.strength:.2%})")
    
    if analysis['resistance']:
        print(f"\n  Resistance zones found: {len(analysis['resistance'])}")
        for i, zone in enumerate(analysis['resistance'][:3], 1):
            print(f"    {i}. ${zone.price:.2f} ({zone.size:,} shares, strength: {zone.strength:.2%})")
    
    # 5. Detect pattern
    print(f"\n5. Detecting trading patterns...")
    signal = analyzer.detect_pattern(ticker, price)
    
    print(f"\nPattern Detected:")
    print(f"  Type: {signal.pattern.value}")
    print(f"  Confidence: {signal.confidence:.2%}")
    
    if signal.price_level:
        print(f"  Price level: ${signal.price_level:.2f}")
    
    if signal.imbalance:
        print(f"  Order imbalance: {signal.imbalance:.2%}")
    
    # 6. Show what trading engine would do
    print(f"\n6. Trading engine evaluation...")
    
    engine_config = {
        'max_position_size': 2000,
        'max_positions': 3,
        'position_size_pct': 0.02,
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
    direction = engine.evaluate_signal(signal)
    
    if direction:
        print(f"  Recommended action: {direction.value}")
        
        # Show what option would be selected
        print(f"\n7. Option selection (not executing)...")
        contract = engine.select_option(symbol, direction, price)
        
        if contract:
            print(f"  Selected option: {contract.localSymbol}")
            
            # Get option price
            option_price = ib.get_option_price(contract)
            if option_price:
                bid, ask, last = option_price
                mid = (bid + ask) / 2 if bid > 0 and ask > 0 else last
                print(f"  Option price: ${mid:.2f}")
                
                # Show position size
                quantity = engine.calculate_position_size(mid)
                total_cost = quantity * mid * 100
                print(f"  Position size: {quantity} contracts (${total_cost:.2f})")
                
                # Show exit levels
                profit_target = mid * (1 + engine.profit_target_pct)
                stop_loss = mid * (1 - engine.stop_loss_pct)
                print(f"  Profit target: ${profit_target:.2f} ({engine.profit_target_pct:.0%} gain)")
                print(f"  Stop loss: ${stop_loss:.2f} ({engine.stop_loss_pct:.0%} loss)")
    else:
        print(f"  No trade action recommended (signal doesn't meet criteria)")
    
    # 8. Clean up
    print(f"\n8. Cleaning up...")
    ib.cancel_market_depth(ticker.contract)
    ib.disconnect()
    
    print("\n✓ Example complete")
    print("\nTo run the automated bot: python main.py")


def example_check_positions():
    """
    Example: Check current positions
    """
    print("=" * 60)
    print("CHECK POSITIONS EXAMPLE")
    print("=" * 60)
    
    ib = IBWrapper(host='127.0.0.1', port=7497, client_id=1)
    
    if not ib.connect():
        print("Failed to connect")
        return
    
    print("\nCurrent Positions:")
    positions = ib.get_positions()
    
    if not positions:
        print("  No open positions")
    else:
        for pos in positions:
            print(f"\n  {pos.contract.symbol}")
            print(f"    Contract: {pos.contract.localSymbol}")
            print(f"    Quantity: {pos.position}")
            print(f"    Avg cost: ${pos.avgCost:.2f}")
    
    print("\nAccount Value:")
    account_value = ib.get_account_value('NetLiquidation')
    if account_value:
        print(f"  ${account_value:,.2f}")
    
    ib.disconnect()


def main():
    """Run examples"""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'positions':
        example_check_positions()
    else:
        example_manual_analysis()


if __name__ == '__main__':
    main()
