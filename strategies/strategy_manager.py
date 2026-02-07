"""
Strategy Manager

Handles loading, configuring, and orchestrating trading strategies.
Supports dynamic plugin loading from the strategies directory.
"""

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any, Type, Set

from .base_strategy import BaseStrategy, StrategySignal

logger = logging.getLogger(__name__)

# Files that should not be treated as strategies
EXCLUDED_FILES = {'__init__.py', 'base_strategy.py', 'strategy_manager.py', 'template_strategy.py'}


class StrategyManager:
    """
    Manages trading strategy plugins.

    Responsibilities:
    - Load strategies from the strategies directory
    - Configure strategies from config.yaml
    - Enable/disable strategies at runtime
    - Orchestrate signal generation from multiple strategies
    """

    # Built-in strategies that are always available
    # Maps strategy type name -> module.ClassName
    BUILTIN_STRATEGIES = {
        'swing_trading': 'strategies.swing_trading.SwingTradingStrategy',
        'scalping': 'strategies.scalping.ScalpingStrategy',
        'vix_momentum_orb': 'strategies.vix_momentum_orb.VIXMomentumORB',
        'bull_put_spread': 'strategies.options_strategies.BullPutSpreadStrategy',
        'bear_put_spread': 'strategies.options_strategies.BearPutSpreadStrategy',
        'long_put': 'strategies.options_strategies.LongPutStrategy',
        'iron_condor': 'strategies.options_strategies.IronCondorStrategy',
    }

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize the strategy manager.

        Args:
            config: Configuration dict, typically from config.yaml.
                   Expected structure (supports multiple instances of same type):
                   {
                       'strategies': {
                           'swing_conservative': {
                               'type': 'swing_trading',  # Strategy type
                               'enabled': True,
                               'zone_proximity_pct': 0.005,
                               ...
                           },
                           'swing_aggressive': {
                               'type': 'swing_trading',  # Same type, different config
                               'enabled': True,
                               'zone_proximity_pct': 0.003,
                               ...
                           },
                           # Backward compatible: if 'type' not specified, instance name = type
                           'scalping': {
                               'enabled': True,
                               'imbalance_entry_threshold': 0.7,
                               ...
                           }
                       }
                   }
        """
        self._config = config or {}
        self._strategies: Dict[str, BaseStrategy] = {}  # instance_name -> strategy
        self._enabled: Dict[str, bool] = {}
        self._instance_types: Dict[str, str] = {}  # instance_name -> strategy_type

    def load_strategy(self, instance_name: str,
                      strategy_class: Optional[Type[BaseStrategy]] = None,
                      config: Optional[Dict[str, Any]] = None,
                      strategy_type: Optional[str] = None) -> Optional[BaseStrategy]:
        """
        Load a strategy by instance name and type.

        Supports multiple instances of the same strategy type with different configs.

        Args:
            instance_name: Unique identifier for this strategy instance
            strategy_class: Optional class to instantiate (for direct loading)
            config: Strategy-specific configuration (overrides defaults)
            strategy_type: Type of strategy to load (e.g., 'swing_trading', 'scalping').
                          If None, looks for 'type' in config, or uses instance_name.

        Returns:
            Loaded strategy instance or None if failed

        Example:
            # Load two swing trading instances with different configs
            manager.load_strategy('swing_conservative', strategy_type='swing_trading',
                                  config={'zone_proximity_pct': 0.005})
            manager.load_strategy('swing_aggressive', strategy_type='swing_trading',
                                  config={'zone_proximity_pct': 0.003})
        """
        try:
            # Get strategy-specific config
            strategy_config = config or self._get_strategy_config(instance_name)

            # Inject instance_name into config so strategies can use it for logging
            strategy_config = {**strategy_config, 'instance_name': instance_name}

            # Determine strategy type: explicit param > config 'type' field > instance_name
            resolved_type: str = strategy_type or strategy_config.get('type', instance_name)

            # If class provided, use it directly
            if strategy_class is not None:
                strategy = strategy_class(strategy_config)
            # Check if it's a built-in strategy type
            elif resolved_type in self.BUILTIN_STRATEGIES:
                strategy = self._load_builtin(resolved_type, strategy_config)
            # Try to load from strategies directory by type
            else:
                strategy = self._load_from_file(resolved_type, strategy_config)

            if strategy is None:
                logger.error(f"Failed to load strategy instance '{instance_name}' (type: {resolved_type})")
                return None

            # Validate config
            errors = strategy.validate_config()
            if errors:
                logger.warning(f"Strategy {instance_name} config warnings: {errors}")

            # Register strategy instance
            self._strategies[instance_name] = strategy
            self._enabled[instance_name] = strategy_config.get('enabled', True)
            self._instance_types[instance_name] = resolved_type

            logger.info(f"Loaded strategy instance '{instance_name}' (type: {resolved_type}): {strategy}")
            return strategy

        except Exception as e:
            logger.error(f"Error loading strategy {instance_name}: {e}")
            return None

    def _load_builtin(self, name: str, config: Dict[str, Any]) -> Optional[BaseStrategy]:
        """Load a built-in strategy."""
        if name not in self.BUILTIN_STRATEGIES:
            return None

        module_path = self.BUILTIN_STRATEGIES[name]
        module_name, class_name = module_path.rsplit('.', 1)

        try:
            module = importlib.import_module(module_name)
            strategy_class = getattr(module, class_name)
            return strategy_class(config)
        except Exception as e:
            logger.error(f"Failed to load built-in strategy {name}: {e}")
            return None

    def _load_from_file(self, name: str, config: Dict[str, Any]) -> Optional[BaseStrategy]:
        """Load a strategy from a Python file in the strategies directory."""
        # Determine strategies directory
        strategies_dir = Path(__file__).parent

        # Look for matching file
        strategy_file = strategies_dir / f"{name}.py"
        if not strategy_file.exists():
            logger.error(f"Strategy file not found: {strategy_file}")
            return None

        try:
            # Load module from file
            spec = importlib.util.spec_from_file_location(name, strategy_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find strategy class in module
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and
                    issubclass(attr, BaseStrategy) and
                    attr is not BaseStrategy):
                    return attr(config)

            logger.error(f"No BaseStrategy subclass found in {strategy_file}")
            return None

        except Exception as e:
            logger.error(f"Failed to load strategy from {strategy_file}: {e}")
            return None

    def _get_strategy_config(self, name: str) -> Dict[str, Any]:
        """Get configuration for a specific strategy."""
        strategies_config = self._config.get('strategies', {})
        return strategies_config.get(name, {})

    def load_all_configured(self) -> int:
        """
        Load all strategies configured in config.yaml.

        Returns:
            Number of strategies successfully loaded
        """
        strategies_config = self._config.get('strategies', {})
        loaded = 0

        for name, config in strategies_config.items():
            if self.load_strategy(name, config=config):
                loaded += 1

        # If no strategies configured, load default swing_trading
        if not strategies_config:
            logger.info("No strategies configured, loading default swing_trading")
            if self.load_strategy('swing_trading'):
                loaded += 1

        return loaded

    def enable_strategy(self, name: str):
        """Enable a loaded strategy."""
        if name in self._strategies:
            self._enabled[name] = True
            logger.info(f"Enabled strategy: {name}")
        else:
            logger.warning(f"Strategy not loaded: {name}")

    def disable_strategy(self, name: str):
        """Disable a loaded strategy."""
        if name in self._strategies:
            self._enabled[name] = False
            logger.info(f"Disabled strategy: {name}")

    def is_enabled(self, name: str) -> bool:
        """Check if a strategy is enabled."""
        return self._enabled.get(name, False)

    def get_strategy(self, name: str) -> Optional[BaseStrategy]:
        """Get a loaded strategy by name."""
        return self._strategies.get(name)

    def get_enabled_strategies(self) -> List[BaseStrategy]:
        """Get all enabled strategies."""
        return [
            strategy for name, strategy in self._strategies.items()
            if self._enabled.get(name, False)
        ]

    def get_all_strategies(self) -> Dict[str, BaseStrategy]:
        """Get all loaded strategies."""
        return self._strategies.copy()

    def analyze_all(self, ticker: Any, current_price: float,
                    context: Optional[Dict[str, Any]] = None) -> List[StrategySignal]:
        """
        Run all enabled strategies and collect signals.

        Args:
            ticker: ib_insync Ticker with market data
            current_price: Current stock price
            context: Optional context passed to strategies

        Returns:
            List of signals from all enabled strategies
        """
        signals = []
        context = context or {}
        symbol = context.get('symbol')

        for instance_name, strategy in self._strategies.items():
            if not self._enabled.get(instance_name, False):
                continue

            # Check if strategy is restricted to specific symbols
            allowed_symbols = strategy.get_config('symbols')
            if allowed_symbols and symbol and symbol not in allowed_symbols:
                continue

            try:
                signal = strategy.analyze(ticker, current_price, context)
                if signal is not None:
                    # Tag signal with instance name and strategy type
                    signal.metadata['strategy'] = instance_name
                    signal.metadata['strategy_type'] = self._instance_types.get(instance_name, strategy.name)
                    signals.append(signal)

            except Exception as e:
                logger.error(f"Strategy {instance_name} error: {e}")

        return signals

    def get_best_signal(self, ticker: Any, current_price: float,
                        context: Optional[Dict[str, Any]] = None) -> Optional[StrategySignal]:
        """
        Get the highest confidence signal from all enabled strategies.

        Args:
            ticker: ib_insync Ticker with market data
            current_price: Current stock price
            context: Optional context passed to strategies

        Returns:
            Best signal or None if no signals
        """
        signals = self.analyze_all(ticker, current_price, context)

        if not signals:
            return None

        # Return highest confidence signal
        return max(signals, key=lambda s: s.confidence)

    def notify_position_opened(self, position: Any, strategy_name: Optional[str] = None):
        """Notify strategies that a position was opened."""
        if strategy_name and strategy_name in self._strategies:
            self._strategies[strategy_name].on_position_opened(position)
        else:
            # Notify all strategies
            for strategy in self._strategies.values():
                strategy.on_position_opened(position)

    def notify_position_closed(self, position: Any, reason: str,
                               strategy_name: Optional[str] = None):
        """Notify strategies that a position was closed."""
        if strategy_name and strategy_name in self._strategies:
            self._strategies[strategy_name].on_position_closed(position, reason)
        else:
            for strategy in self._strategies.values():
                strategy.on_position_closed(position, reason)

    def get_strategy_type(self, instance_name: str) -> Optional[str]:
        """Get the strategy type for a loaded instance."""
        return self._instance_types.get(instance_name)

    def get_status(self) -> Dict[str, Any]:
        """Get status of all loaded strategies."""
        return {
            'loaded': len(self._strategies),
            'enabled': sum(1 for v in self._enabled.values() if v),
            'strategies': {
                name: {
                    'enabled': self._enabled.get(name, False),
                    'type': self._instance_types.get(name, strategy.name),
                    'version': strategy.version,
                    'description': strategy.description,
                }
                for name, strategy in self._strategies.items()
            }
        }

    # =========================================================================
    # Dynamic Loading / Hot Reload
    # =========================================================================

    def reload_strategy(self, instance_name: str) -> bool:
        """
        Hot-reload a strategy instance by name (re-imports the module from disk).

        Args:
            instance_name: Strategy instance identifier

        Returns:
            True if reload succeeded, False otherwise
        """
        if instance_name not in self._strategies:
            logger.warning(f"Cannot reload '{instance_name}' - not currently loaded")
            return False

        # Remember enabled state and get strategy type
        was_enabled = self._enabled.get(instance_name, True)
        strategy_config = self._get_strategy_config(instance_name)
        strategy_type = self._instance_types.get(instance_name, instance_name)

        try:
            # For built-in strategy types, reload via importlib
            if strategy_type in self.BUILTIN_STRATEGIES:
                module_path = self.BUILTIN_STRATEGIES[strategy_type]
                module_name, class_name = module_path.rsplit('.', 1)

                # Remove from sys.modules to force fresh import
                if module_name in sys.modules:
                    del sys.modules[module_name]

                module = importlib.import_module(module_name)
                strategy_class = getattr(module, class_name)
                new_strategy = strategy_class(strategy_config)
            else:
                # File-based strategy - reload from file
                new_strategy = self._load_from_file(strategy_type, strategy_config)

            if new_strategy is None:
                logger.error(f"Failed to reload strategy instance: {instance_name}")
                return False

            # Replace the old strategy
            self._strategies[instance_name] = new_strategy
            self._enabled[instance_name] = was_enabled

            logger.info(f"Reloaded strategy instance '{instance_name}': {new_strategy}")
            return True

        except Exception as e:
            logger.error(f"Error reloading strategy {instance_name}: {e}")
            return False

    def reload_all(self) -> Dict[str, bool]:
        """
        Reload all currently loaded strategies.

        Returns:
            Dict mapping strategy name to reload success (True/False)
        """
        results = {}
        for name in list(self._strategies.keys()):
            results[name] = self.reload_strategy(name)
        return results

    def discover_strategies(self) -> Set[str]:
        """
        Discover strategy files in the strategies directory that aren't loaded.

        Returns:
            Set of strategy names (filenames without .py) that could be loaded
        """
        strategies_dir = Path(__file__).parent
        available: Set[str] = set()

        for py_file in strategies_dir.glob("*.py"):
            name = py_file.stem
            if py_file.name not in EXCLUDED_FILES:
                available.add(name)

        # Also include built-in strategies
        available.update(self.BUILTIN_STRATEGIES.keys())

        return available

    def get_unloaded_strategies(self) -> Set[str]:
        """
        Get strategies that are available but not currently loaded.

        Returns:
            Set of strategy names that can be loaded
        """
        available = self.discover_strategies()
        loaded = set(self._strategies.keys())
        return available - loaded

    def load_new_strategies(self) -> int:
        """
        Auto-discover and load any new strategy files not yet loaded.

        Returns:
            Number of new strategies loaded
        """
        unloaded = self.get_unloaded_strategies()
        loaded_count = 0

        for name in unloaded:
            # Skip template
            if name == 'template':
                continue

            config = self._get_strategy_config(name)
            # Only auto-load if explicitly enabled in config
            if config.get('enabled', False):
                if self.load_strategy(name, config=config):
                    loaded_count += 1
                    logger.info(f"Auto-loaded new strategy: {name}")

        return loaded_count

    def __repr__(self) -> str:
        enabled = sum(1 for v in self._enabled.values() if v)
        return f"<StrategyManager strategies={len(self._strategies)} enabled={enabled}>"
