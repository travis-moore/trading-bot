#!/usr/bin/env python3
"""
Debug script to verify option chain strikes are coming from IB
"""

from ib_wrapper import IBWrapper

# Connect
print("Connecting to IB...")
ib = IBWrapper(host='127.0.0.1', port=4002, client_id=999)
if not ib.connect():
    print("Failed to connect")
    exit(1)

print("✓ Connected\n")

# Test AAPL
symbol = "AAPL"
print(f"Getting option chain for {symbol}...")

chain, expiries = ib.get_option_chain(symbol, expiry_days_min=7, expiry_days_max=45)

if not chain:
    print("❌ No chain returned")
    ib.disconnect()
    exit(1)

if not expiries:
    print("❌ No expiries returned")
    ib.disconnect()
    exit(1)

print(f"✓ Got chain for {symbol}")
print(f"  Exchange: {chain.exchange}")
print(f"  Expirations found: {len(expiries)}")
print(f"  First expiry: {expiries[0]}")

# Check if strikes attribute exists
if not hasattr(chain, 'strikes'):
    print("\n❌ ERROR: chain object has no 'strikes' attribute!")
    print(f"   Chain attributes: {dir(chain)}")
else:
    print(f"\n✓ chain.strikes exists")
    
    if not chain.strikes:
        print("  ⚠️  WARNING: chain.strikes is empty!")
    else:
        strikes = sorted(chain.strikes)
        print(f"  Total strikes: {len(strikes)}")
        print(f"  First 10 strikes: {strikes[:10]}")
        print(f"  Last 10 strikes: {strikes[-10:]}")
        
        # Check strike increments
        if len(strikes) >= 2:
            increments = [strikes[i+1] - strikes[i] for i in range(min(20, len(strikes)-1))]
            unique_increments = sorted(set(increments))
            print(f"  Strike increments: {unique_increments}")

# Get current price
print(f"\nGetting current {symbol} price...")
price = ib.get_stock_price(symbol)
print(f"  Current price: ${price:.2f}")

# Calculate target strike
if price and hasattr(chain, 'strikes') and chain.strikes:
    target = price * 1.02
    strikes = sorted(chain.strikes)
    nearest = min(strikes, key=lambda x: abs(x - target))
    
    print(f"\n📊 Strike Selection:")
    print(f"  Current price: ${price:.2f}")
    print(f"  Target (2% OTM): ${target:.2f}")
    print(f"  Nearest strike: ${nearest}")
    print(f"  Difference: ${abs(nearest - target):.2f}")

# Disconnect
print("\nDisconnecting...")
ib.disconnect()
print("✓ Done")
