#!/usr/bin/env python3
"""
Test script to verify bot components without IB connection
"""

import sys
from dataclasses import dataclass

# Mock IB objects for testing
@dataclass
class MockDOMLevel:
    price: float
    size: int
    marketMaker: str = ""

class MockTicker:
    def __init__(self):
        self.domBids = [
            MockDOMLevel(142.50, 1500),
            MockDOMLevel(142.49, 800),
            MockDOMLevel(142.48, 2200),
            MockDOMLevel(142.47, 600),
            MockDOMLevel(142.46, 400),
        ]
        self.domAsks = [
            MockDOMLevel(142.51, 900),
            MockDOMLevel(142.52, 1800),
            MockDOMLevel(142.53, 500),
            MockDOMLevel(142.54, 700),
            MockDOMLevel(142.55, 300),
        ]


def test_liquidity_analyzer():
    """Test liquidity analyzer"""
    print("Testing Liquidity Analyzer...")
    
    from liquidity_analyzer import LiquidityAnalyzer
    
    config = {
        'liquidity_threshold': 1000,
        'zone_proximity': 0.10,
        'imbalance_threshold': 0.6,
        'num_levels': 10
    }
    
    analyzer = LiquidityAnalyzer(config)
    ticker = MockTicker()
    
    # Test order book analysis
    analysis = analyzer.analyze_book(ticker)
    print(f"  ✓ Order book analyzed")
    print(f"    - Support zones: {len(analysis['support'])}")
    print(f"    - Resistance zones: {len(analysis['resistance'])}")
    print(f"    - Bid depth: {analysis['bid_depth_total']}")
    print(f"    - Ask depth: {analysis['ask_depth_total']}")
    print(f"    - Imbalance: {analysis['imbalance']:.2f}")
    
    # Test pattern detection
    signal = analyzer.detect_pattern(ticker, 142.50)
    print(f"  ✓ Pattern detected: {signal.pattern.value}")
    print(f"    - Confidence: {signal.confidence:.2f}")
    
    return True


def test_trading_engine_structure():
    """Test trading engine structure"""
    print("\nTesting Trading Engine Structure...")
    
    from trading_engine import TradingEngine, TradeRule, Pattern, TradeDirection
    
    # Test rule creation
    rule = TradeRule(
        pattern=Pattern.REJECTION_AT_SUPPORT,
        direction=TradeDirection.LONG_CALL,
        min_confidence=0.65,
        entry_condition="Test rule"
    )
    
    print(f"  ✓ Trade rule created")
    print(f"    - Pattern: {rule.pattern.value}")
    print(f"    - Direction: {rule.direction.value}")
    print(f"    - Min confidence: {rule.min_confidence}")
    
    return True


def test_config_loading():
    """Test configuration loading"""
    print("\nTesting Configuration Loading...")
    
    import yaml
    
    try:
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)
        
        print(f"  ✓ Config loaded successfully")
        print(f"    - Symbols: {', '.join(config['symbols'])}")
        print(f"    - Max positions: {config['risk_management']['max_positions']}")
        print(f"    - Scan interval: {config['operation']['scan_interval']}s")
        
        return True
    except Exception as e:
        print(f"  ✗ Config loading failed: {e}")
        return False


def main():
    """Run all tests"""
    print("=" * 60)
    print("SWING TRADING BOT - COMPONENT TESTS")
    print("=" * 60)
    
    tests = [
        ("Configuration", test_config_loading),
        ("Liquidity Analyzer", test_liquidity_analyzer),
        ("Trading Engine", test_trading_engine_structure),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n  ✗ {test_name} failed with error: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    all_passed = all(r for _, r in results)
    
    if all_passed:
        print("\n✓ All tests passed! Bot components are working correctly.")
        print("\nNext steps:")
        print("1. Start TWS or IB Gateway")
        print("2. Enable API connections")
        print("3. Subscribe to market data (if needed)")
        print("4. Run: python main.py")
    else:
        print("\n✗ Some tests failed. Check errors above.")
        sys.exit(1)


if __name__ == '__main__':
    main()
