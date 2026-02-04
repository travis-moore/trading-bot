"""
Trading Strategies Plugin System

This package contains trading strategies that can be loaded by the StrategyManager.
Each strategy must inherit from BaseStrategy and implement the required interface.

Example usage:

    from strategies import StrategyManager, SwingTradingStrategy

    # Load via manager (recommended)
    manager = StrategyManager(config)
    manager.load_all_configured()
    signal = manager.get_best_signal(ticker, current_price)

    # Or load directly
    strategy = SwingTradingStrategy()
    signal = strategy.analyze(ticker, current_price)
"""

from .base_strategy import BaseStrategy, StrategySignal, TradeDirection
from .strategy_manager import StrategyManager
from .swing_trading import SwingTradingStrategy
from .scalping import ScalpingStrategy

__all__ = [
    'BaseStrategy',
    'StrategySignal',
    'TradeDirection',
    'StrategyManager',
    'SwingTradingStrategy',
    'ScalpingStrategy',
]
