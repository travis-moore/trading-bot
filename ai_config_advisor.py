"""
AI Configuration Advisor Package Generator.

Generates a structured markdown file containing performance data, current
configuration, and instructions — designed to be uploaded to an AI chat
for configuration tuning suggestions.

Usage:
    python ai_config_advisor.py                 # Auto-detect period
    python ai_config_advisor.py --days 7        # Last 7 days
    python ai_config_advisor.py --db path.db    # Custom DB path
"""

import os
import glob
import logging
import yaml
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from collections import defaultdict

from trade_db import TradeDatabase

logger = logging.getLogger(__name__)

# Sections of config to include in the package (exclude secrets/infra)
CONFIG_SECTIONS_TO_INCLUDE = [
    'risk_management', 'trading_rules', 'option_selection',
    'order_management', 'market_regime', 'sector_rotation',
    'liquidity_analysis', 'strategies',
]

AI_RESPONSE_MARKER = '---PASTE AI RESPONSE BELOW THIS LINE---'


class AIConfigAdvisor:
    """Generates AI-consumable config advisor packages."""

    def __init__(
        self,
        db_path: str = "trading_bot.db",
        config_path: str = "config.yaml",
        market_regime: Optional[str] = None,
        packages_dir: str = "ai_packages",
    ):
        self.db = TradeDatabase(db_path)
        self.config_path = config_path
        self.market_regime = market_regime or "N/A (standalone mode)"
        self.packages_dir = packages_dir
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Load config.yaml."""
        try:
            with open(self.config_path, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}

    def generate_package(self, days: Optional[int] = None) -> str:
        """Generate the AI advisor package. Returns output filepath."""
        os.makedirs(self.packages_dir, exist_ok=True)

        start_date, end_date = self._determine_period(days)
        today = datetime.now().strftime('%Y-%m-%d')
        filepath = os.path.join(self.packages_dir, f"ai_package_{today}.md")

        # Build all sections
        sections = []
        sections.append(f"# AI Configuration Advisor Package\n")
        sections.append(f"Generated: {today} | Period: {start_date} to {end_date}\n")

        sections.append(self._build_section_system_context())
        sections.append(self._build_section_previous_cycle(start_date))
        sections.append(self._build_section_current_data(start_date, end_date))
        sections.append(self._build_section_current_config())
        sections.append(self._build_section_ai_instructions())
        sections.append(self._build_section_ai_response())

        content = "\n".join(sections)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        logger.info(f"AI advisor package generated: {filepath}")
        return filepath

    # =========================================================================
    # Period Detection
    # =========================================================================

    def _determine_period(self, days: Optional[int] = None):
        """Determine the analysis period (start_date, end_date)."""
        end_date = datetime.now().strftime('%Y-%m-%d')

        if days is not None:
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            return start_date, end_date

        # Auto-detect from last package
        previous = self._find_previous_package()
        if previous:
            basename = os.path.basename(previous)
            date_str = basename.replace('ai_package_', '').replace('.md', '')
            try:
                datetime.strptime(date_str, '%Y-%m-%d')
                return date_str, end_date
            except ValueError:
                pass

        # Default: 14 days
        start_date = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d')
        return start_date, end_date

    def _find_previous_package(self) -> Optional[str]:
        """Find the most recent previous package file."""
        pattern = os.path.join(self.packages_dir, "ai_package_*.md")
        files = sorted(glob.glob(pattern))
        # Exclude today's file if it exists (we're generating a new one)
        today = datetime.now().strftime('%Y-%m-%d')
        files = [f for f in files if today not in os.path.basename(f)]
        return files[-1] if files else None

    # =========================================================================
    # Previous Package Parsing
    # =========================================================================

    def _parse_previous_package(self, filepath: str) -> dict:
        """Parse a previous package to extract metrics, AI response, and config."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return {'metrics_summary': '', 'ai_response': '', 'config_yaml': '', 'period_line': ''}

        result = {
            'metrics_summary': '',
            'ai_response': '',
            'config_yaml': '',
            'period_line': '',
        }

        # Extract period line
        for line in content.split('\n'):
            if line.startswith('Generated:'):
                result['period_line'] = line
                break

        # Extract overall performance section
        try:
            if '### Overall Performance' in content:
                start = content.index('### Overall Performance')
                # Find next ### header
                rest = content[start + len('### Overall Performance'):]
                next_header = rest.find('\n### ')
                if next_header > 0:
                    result['metrics_summary'] = content[start:start + len('### Overall Performance') + next_header].strip()
                else:
                    result['metrics_summary'] = content[start:start + 500].strip()
        except (ValueError, IndexError):
            pass

        # Extract AI response
        if AI_RESPONSE_MARKER in content:
            response_start = content.index(AI_RESPONSE_MARKER) + len(AI_RESPONSE_MARKER)
            result['ai_response'] = content[response_start:].strip()

        # Extract config YAML block
        try:
            if '## 4. CURRENT CONFIGURATION' in content:
                config_section_start = content.index('## 4. CURRENT CONFIGURATION')
                # Find the yaml code block
                yaml_start = content.find('```yaml', config_section_start)
                yaml_end = content.find('```', yaml_start + 7)
                if yaml_start > 0 and yaml_end > yaml_start:
                    result['config_yaml'] = content[yaml_start + 7:yaml_end].strip()
        except (ValueError, IndexError):
            pass

        return result

    def _compute_config_diff(self, previous_yaml_str: str) -> str:
        """Compare previous config snapshot with current config."""
        if not previous_yaml_str:
            return "No previous configuration available for comparison."

        try:
            prev_config = yaml.safe_load(previous_yaml_str) or {}
        except Exception:
            return "Could not parse previous configuration."

        # Flatten both configs
        current_filtered = self._get_filtered_config()
        prev_flat = self._flatten_dict(prev_config)
        curr_flat = self._flatten_dict(current_filtered)

        changes = []
        all_keys = sorted(set(list(prev_flat.keys()) + list(curr_flat.keys())))

        for key in all_keys:
            prev_val = prev_flat.get(key)
            curr_val = curr_flat.get(key)
            if prev_val != curr_val:
                if prev_val is None:
                    changes.append(f"  NEW: {key} = {curr_val}")
                elif curr_val is None:
                    changes.append(f"  REMOVED: {key} (was: {prev_val})")
                else:
                    changes.append(f"  {key}: {prev_val} -> {curr_val}")

        if not changes:
            return "No configuration changes since last package."

        return "\n".join(changes)

    def _flatten_dict(self, d: dict, prefix: str = '') -> dict:
        """Flatten a nested dict to dot-notation keys."""
        items = {}
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                items.update(self._flatten_dict(v, key))
            else:
                items[key] = v
        return items

    # =========================================================================
    # Section Builders
    # =========================================================================

    def _build_section_system_context(self) -> str:
        """Section 1: Bot description and parameter reference."""
        return """## 1. SYSTEM CONTEXT

This is an automated options trading bot using Interactive Brokers (IBKR). It trades stock options (calls, puts, spreads, iron condors) based on order book liquidity analysis, support/resistance detection, and market regime filtering.

### How the Bot Works
- Monitors Level 2 order books for multiple symbols to detect support/resistance zones
- Generates signals when price interacts with detected zones (rejection, breakout)
- Filters signals through market regime (bull_trend, bear_trend, range_bound, high_chaos) and sector relative strength
- Each strategy instance has its own budget, symbols, position limits, and tunable parameters
- Uses bracket orders (stop loss + take profit) with optional trailing stops
- Multiple strategy types can run simultaneously with different configurations

### Tunable Parameter Reference

#### Global Risk Management
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `risk_management.profit_target_pct` | Take profit at this % gain | 0.10-1.00 | Higher = more profit per trade but fewer exits |
| `risk_management.stop_loss_pct` | Stop loss at this % loss | 0.10-0.50 | Tighter = less loss per trade but more stop-outs |
| `risk_management.trailing_stop_enabled` | Enable trailing stops | bool | Lets winners run further |
| `risk_management.trailing_stop_activation_pct` | Profit % to start trailing | 0.05-0.30 | Lower = activates sooner |
| `risk_management.trailing_stop_distance_pct` | Trail distance from peak | 0.02-0.15 | Tighter = locks in more profit but more whipsaws |
| `risk_management.max_hold_days` | Auto-close after N days | 1-60 | Prevents capital lock-up; lower for scalping |

#### Global Trading Rules (Pattern Confidence Thresholds)
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `trading_rules.rejection_support_confidence` | Min confidence for support bounce signal | 0.50-0.90 | Lower = more signals |
| `trading_rules.breakout_up_confidence` | Min confidence for upward breakout signal | 0.50-0.90 | Lower = more signals |
| `trading_rules.rejection_resistance_confidence` | Min confidence for resistance rejection signal | 0.50-0.90 | Lower = more signals |
| `trading_rules.breakout_down_confidence` | Min confidence for downward breakout signal | 0.50-0.90 | Lower = more signals |

#### Global Option Selection
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `option_selection.min_dte` | Minimum days to expiration | 1-45 | Lower = cheaper but more theta decay |
| `option_selection.max_dte` | Maximum days to expiration | 14-90 | Higher = more expensive but less theta |
| `option_selection.call_strike_pct` | Call strike as multiple of price (1.02 = 2% OTM) | 1.00-1.10 | Higher = cheaper but less likely ITM |
| `option_selection.put_strike_pct` | Put strike as multiple of price (0.98 = 2% OTM) | 0.90-1.00 | Lower = cheaper but less likely ITM |

#### Per-Strategy Parameters (common to all types)
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `enabled` | Whether strategy is active | bool | |
| `max_positions` | Max concurrent positions for this strategy | 1-10 | |
| `allowed_regimes` | Market regimes where strategy can trade | list | Options: bull_trend, bear_trend, range_bound, high_chaos |
| `min_sector_rs` | Min sector relative strength slope | -1.0 to 1.0 | 0.0 = only outperforming sectors |
| `daily_loss_limit` | Stop strategy for day after this $ loss | 50-1000 | Per-strategy safety |
| `entry_price_bias` | Entry price: -1=BID, 0=MID, 1=ASK | -1.0 to 1.0 | Negative = better fills, less likely to fill |
| `contract_cost_basis` | Max $ per contract (price*100) | 50-500 | Caps individual contract cost |

#### Swing Trading Specific
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `zone_proximity_pct` | Price must be within this % of level | 0.001-0.02 | Wider = more signals, less precise |
| `min_confidence` | Min confidence to generate signal | 0.50-0.90 | Primary quality filter |
| `zscore_threshold` | Z-score for filtering significant levels | 1.5-5.0 | Higher = fewer but stronger levels |
| `level_confirmation_minutes` | Minutes a level must persist | 1-15 | Higher = more confirmed levels |
| `exclusion_zone_pct` | Ignore levels within this % of price | 0.001-0.01 | Prevents trading at current price |
| `historical_bounce_enabled` | Use historical price levels | bool | Adds "Power Level" detection |
| `swing_window` | Bars on each side for swing detection | 3-10 | Higher = fewer but more significant swings |
| `bounce_proximity_pct` | Clustering tolerance for swing points | 0.0005-0.003 | |
| `min_bounces` | Min tests to form a level | 2-5 | Higher = stronger levels only |
| `decay_type` | How older bounces lose strength | linear/exponential | |
| `power_level_proximity_pct` | Alignment tolerance (historical+depth) | 0.003-0.01 | |
| `power_level_confidence_boost` | Confidence boost for power levels | 0.05-0.30 | |
| `performance_feedback_enabled` | Auto-adjust confidence from results | bool | |
| `performance_lookback_days` | Days of history for feedback | 3-30 | |
| `min_trades_for_feedback` | Min trades before feedback activates | 3-20 | |

#### Scalping Specific
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `imbalance_entry_threshold` | Order book imbalance to trigger entry | 0.5-0.9 | Higher = stronger signal required |
| `max_ticks_without_progress` | Exit if no favorable movement after N ticks | 1-10 | Lower = faster exit |

#### VIX Momentum ORB Specific
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `orb_minutes` | Minutes after open for opening range | 5-30 | |
| `trading_window_minutes` | Minutes after ORB to accept signals | 15-60 | |
| `target_profit` | Dollar profit target per trade | 100-1000 | |
| `vix_slope_minutes` | Minutes of VIX history for slope | 3-15 | |
| `spread_threshold_pct` | Skip if spread exceeds this % | 0.01-0.10 | |

#### Spread & Multi-Leg Specific
| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `short_put_delta` / `long_put_delta` | Delta for spread legs | 5-50 | |
| `short_call_delta` / `long_call_delta` | Delta for condor call legs | 5-50 | |
| `exit_at_pct_profit` | Close at this % of max credit | 0.25-0.75 | |
| `exit_at_dte` | Close when this many DTE remain | 7-30 | Iron condor time exit |
| `absorption_confidence` | Min confidence for breakdown signals | 0.60-0.90 | |
| `put_delta` | Delta for long put purchases | 30-70 | Higher = more ATM, more expensive |

### Do Not Change (User Decisions)
These parameters should NOT be suggested for changes — they reflect user capital allocation, infrastructure, and risk tolerance:
- `ib_connection.*` (host, port, client_id)
- `strategies.*.budget` (user's capital allocation per strategy)
- `strategies.*.symbols` (user's market preference)
- `notifications.discord_webhook`
- `safety.max_daily_loss` (user's global risk limit)
- `safety.emergency_stop`, `safety.require_manual_approval`
- `operation.*` (scan_interval, log_level, etc.)
"""

    def _build_section_previous_cycle(self, current_start: str) -> str:
        """Section 2: Previous cycle data and AI suggestions."""
        previous_file = self._find_previous_package()

        if not previous_file:
            return "## 2. PREVIOUS CYCLE\n\nFirst package — no previous cycle data.\n"

        previous = self._parse_previous_package(previous_file)

        lines = ["## 2. PREVIOUS CYCLE\n"]
        lines.append(f"Previous package: `{os.path.basename(previous_file)}`")
        if previous['period_line']:
            lines.append(f"{previous['period_line']}\n")

        # Previous metrics
        lines.append("### Previous Period Performance\n")
        if previous['metrics_summary']:
            lines.append(previous['metrics_summary'])
        else:
            lines.append("No metrics summary found in previous package.")
        lines.append("")

        # AI response from previous cycle
        lines.append("### AI Suggestions from Previous Cycle\n")
        if previous['ai_response']:
            lines.append(previous['ai_response'])
        else:
            lines.append("No AI response was pasted into the previous package.")
        lines.append("")

        # Config diff
        lines.append("### Config Changes Since Last Package\n")
        lines.append("```")
        lines.append(self._compute_config_diff(previous['config_yaml']))
        lines.append("```\n")

        return "\n".join(lines)

    def _build_section_current_data(self, start_date: str, end_date: str) -> str:
        """Section 3: All current period performance data."""
        lines = [f"## 3. CURRENT PERIOD DATA ({start_date} to {end_date})\n"]

        # Overall performance
        lines.append(self._build_overall_performance(start_date, end_date))

        # Per-strategy performance
        lines.append(self._build_per_strategy_performance(start_date, end_date))

        # Per-symbol breakdown
        lines.append(self._build_per_symbol_performance(start_date, end_date))

        # Exit reason distribution
        lines.append(self._build_exit_reason_distribution(start_date, end_date))

        # Signal utilization
        lines.append(self._build_signal_utilization(start_date, end_date))

        # Trade frequency
        lines.append(self._build_trade_frequency(start_date, end_date))

        # Budget status
        lines.append(self._build_budget_status())

        # Worst and best trades
        lines.append(self._build_notable_trades(start_date, end_date))

        # Daily P&L
        lines.append(self._build_daily_pnl(start_date, end_date))

        # Market regime
        lines.append(f"### Market Regime\n\nCurrent: **{self.market_regime}**\n")

        return "\n".join(lines)

    def _build_section_current_config(self) -> str:
        """Section 4: Current configuration (filtered)."""
        filtered = self._get_filtered_config()

        lines = ["## 4. CURRENT CONFIGURATION\n"]
        lines.append("```yaml")
        lines.append(yaml.dump(filtered, default_flow_style=False, sort_keys=False).strip())
        lines.append("```\n")

        return "\n".join(lines)

    def _build_section_ai_instructions(self) -> str:
        """Section 5: Instructions for the AI."""
        return """## 5. AI INSTRUCTIONS

You are analyzing performance data from an automated options trading bot. Your task is to suggest configuration changes that would improve performance.

### What to Produce

Provide **1-3 ranked** configuration suggestions. For each:

**Suggestion N: [Brief title]**
- **Confidence**: High / Medium / Low
- **Parameter(s)**: `section.parameter_name`
- **Current value**: X
- **Suggested value**: Y
- **Reasoning**: 2-3 sentences referencing specific data from Section 3 (e.g., "stop_loss_filled accounts for 38% of exits with avg loss of -$23.50, suggesting stops may be too tight")
- **Expected impact**: What metric should improve (e.g., "win rate should increase by ~5%")
- **Risk**: What could go wrong if this change is counterproductive

### Constraints

1. **Prefer fewer high-confidence changes** over many speculative ones. It's better to make 1-2 clear improvements than 5 uncertain ones, so we can attribute results.
2. **Do NOT suggest changes** to parameters in the "Do Not Change" list (Section 1). Budget amounts, symbols, safety limits, and connection settings are user decisions.
3. **Reference specific data** when justifying suggestions. Cite exit reason percentages, win rates, signal utilization, or specific losing trade patterns.
4. **Consider parameter interactions**. Widening `zone_proximity_pct` increases signals, which may require raising `min_confidence` to filter quality. Changing `stop_loss_pct` affects win rate AND average loss.
5. **Budget model**: `available = budget - drawdown - committed`. Wins reduce drawdown (recover budget), losses increase drawdown. Profits above the cap don't increase available budget. Do not suggest budget changes.
6. **If performance is satisfactory**, say so. Not every cycle needs changes. Stability has value.
7. **Consider market conditions**. Poor performance during unfavorable regimes may not indicate a config problem.

### After Your Suggestions

End with a brief summary: "Priority change: [X]. Monitor: [Y metric] over the next period."
"""

    def _build_section_ai_response(self) -> str:
        """Section 6: Placeholder for user to paste AI suggestions."""
        return f"""## 6. AI RESPONSE

<!-- After receiving suggestions from the AI, paste the full response below the marker line. -->
<!-- This section will be included in the next package's "Previous Cycle" for continuity. -->

{AI_RESPONSE_MARKER}

"""

    # =========================================================================
    # Data Subsection Builders
    # =========================================================================

    def _build_overall_performance(self, start_date: str, end_date: str) -> str:
        """Build overall performance metrics table."""
        metrics = self.db.get_performance_metrics(start_date=start_date, end_date=end_date)
        loss_streak = self.db.get_consecutive_losses()

        if not metrics or metrics.get('total_trades', 0) == 0:
            return "### Overall Performance\n\nNo trades in this period.\n"

        lines = ["### Overall Performance\n"]
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total Trades | {metrics['total_trades']} |")
        lines.append(f"| Winners / Losers | {metrics['winners']} / {metrics['losers']} |")
        lines.append(f"| Win Rate | {metrics['win_rate']:.1f}% |")
        lines.append(f"| Total P&L | ${metrics['total_pnl']:+.2f} |")
        lines.append(f"| Avg P&L per Trade | ${metrics['avg_pnl']:+.2f} |")
        lines.append(f"| Profit Factor | {metrics['profit_factor']:.2f} |")
        lines.append(f"| Avg Hold Time | {metrics['avg_hold_hours']:.1f} hours |")
        lines.append(f"| Avg Winner | ${metrics.get('avg_winner', 0):+.2f} |")
        lines.append(f"| Avg Loser | ${metrics.get('avg_loser', 0):+.2f} |")
        lines.append(f"| Largest Winner | ${metrics.get('largest_winner', 0):+.2f} |")
        lines.append(f"| Largest Loser | ${metrics.get('largest_loser', 0):+.2f} |")
        lines.append(f"| Gross Profit | ${metrics.get('gross_profit', 0):+.2f} |")
        lines.append(f"| Gross Loss | ${metrics.get('gross_loss', 0):+.2f} |")
        lines.append(f"| Current Loss Streak | {loss_streak} |")
        lines.append("")

        return "\n".join(lines)

    def _build_per_strategy_performance(self, start_date: str, end_date: str) -> str:
        """Build per-strategy performance table."""
        strategies = self.config.get('strategies', {})
        if not strategies:
            return "### Per-Strategy Performance\n\nNo strategies configured.\n"

        rows = []
        for name in strategies:
            metrics = self.db.get_performance_metrics(
                strategy=name, start_date=start_date, end_date=end_date
            )
            if metrics and metrics.get('total_trades', 0) > 0:
                rows.append({
                    'name': name,
                    'trades': metrics['total_trades'],
                    'wl': f"{metrics['winners']}/{metrics['losers']}",
                    'win_rate': f"{metrics['win_rate']:.1f}%",
                    'total_pnl': f"${metrics['total_pnl']:+.2f}",
                    'avg_pnl': f"${metrics['avg_pnl']:+.2f}",
                    'profit_factor': f"{metrics['profit_factor']:.2f}",
                    'avg_hold': f"{metrics['avg_hold_hours']:.1f}h",
                })

        if not rows:
            return "### Per-Strategy Performance\n\nNo strategy trades in this period.\n"

        lines = ["### Per-Strategy Performance\n"]
        lines.append("| Strategy | Trades | W/L | Win Rate | Total P&L | Avg P&L | Profit Factor | Avg Hold |")
        lines.append("|----------|--------|-----|----------|-----------|---------|---------------|----------|")
        for r in rows:
            lines.append(f"| {r['name']} | {r['trades']} | {r['wl']} | {r['win_rate']} | {r['total_pnl']} | {r['avg_pnl']} | {r['profit_factor']} | {r['avg_hold']} |")
        lines.append("")

        return "\n".join(lines)

    def _build_per_symbol_performance(self, start_date: str, end_date: str) -> str:
        """Build per-symbol performance table."""
        breakdown = self.db.get_symbol_breakdown(start_date=start_date, end_date=end_date)

        if not breakdown:
            return "### Per-Symbol Performance\n\nNo symbol data in this period.\n"

        lines = ["### Per-Symbol Performance\n"]
        lines.append("| Symbol | Trades | Win Rate | Total P&L | Avg P&L |")
        lines.append("|--------|--------|----------|-----------|---------|")
        for row in breakdown:
            lines.append(
                f"| {row['symbol']} | {row['trade_count']} | {row['win_rate']:.1f}% "
                f"| ${row['total_pnl']:+.2f} | ${row['avg_pnl']:+.2f} |"
            )
        lines.append("")

        return "\n".join(lines)

    def _build_exit_reason_distribution(self, start_date: str, end_date: str) -> str:
        """Build exit reason distribution table."""
        dist = self.db.get_exit_reason_distribution(
            start_date=start_date, end_date=end_date
        )

        if not dist:
            return "### Exit Reason Distribution\n\nNo exit data in this period.\n"

        total = sum(d['count'] for d in dist)
        lines = ["### Exit Reason Distribution\n"]
        lines.append("| Exit Reason | Count | % of Total | Avg P&L | Total P&L |")
        lines.append("|-------------|-------|------------|---------|-----------|")
        for d in dist:
            pct = d['count'] / total * 100 if total > 0 else 0
            lines.append(
                f"| {d['exit_reason']} | {d['count']} | {pct:.1f}% "
                f"| ${d['avg_pnl']:+.2f} | ${d['total_pnl']:+.2f} |"
            )
        lines.append("")

        return "\n".join(lines)

    def _build_signal_utilization(self, start_date: str, end_date: str) -> str:
        """Build signal utilization table."""
        util = self.db.get_signal_utilization(
            start_date=start_date, end_date=end_date
        )

        if not util:
            return "### Signal Utilization\n\nNo signal data in this period.\n"

        lines = ["### Signal Utilization\n"]
        lines.append("| Strategy | Total Signals | Executed | Rejected | Failed Entry | Utilization % |")
        lines.append("|----------|--------------|----------|----------|--------------|---------------|")
        for u in util:
            lines.append(
                f"| {u['strategy']} | {u['total_signals']} | {u['executed']} "
                f"| {u['rejected']} | {u['failed_entry']} | {u['utilization_pct']:.1f}% |"
            )
        lines.append("")

        return "\n".join(lines)

    def _build_trade_frequency(self, start_date: str, end_date: str) -> str:
        """Build trade frequency analysis from query_trades results."""
        trades = self.db.query_trades(
            start_date=start_date, end_date=end_date, limit=5000
        )

        if not trades:
            return "### Trade Frequency Analysis\n\nNo trades in this period.\n"

        # Compute hourly distribution from entry times
        hourly_counts = defaultdict(int)
        daily_trades = defaultdict(list)

        for t in trades:
            entry_time = t['entry_time'] if isinstance(t['entry_time'], str) else str(t['entry_time'])
            try:
                dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                continue
            hour_str = f"{dt.hour:02d}"
            hourly_counts[hour_str] += 1
            date_str = dt.strftime('%Y-%m-%d')
            daily_trades[date_str].append(t)

        lines = ["### Trade Frequency Analysis\n"]

        # Overall frequency
        num_days = len(daily_trades) if daily_trades else 1
        total_trades = len(trades)
        lines.append(f"- **Trades per day** (avg): {total_trades / num_days:.1f}")
        lines.append(f"- **Active trading days**: {num_days}")
        lines.append(f"- **Total trades**: {total_trades}")
        lines.append("")

        # Hourly distribution
        lines.append("**Hourly Distribution (by entry time):**\n")
        lines.append("| Hour | Trades |")
        lines.append("|------|--------|")
        for hour in sorted(hourly_counts.keys()):
            lines.append(f"| {hour}:00 | {hourly_counts[hour]} |")
        lines.append("")

        # Sweet spot: frequency vs win rate
        freq_buckets = defaultdict(lambda: {'trades': [], 'days': 0})
        for date_str, day_trades in daily_trades.items():
            count = len(day_trades)
            freq_buckets[count]['trades'].extend(day_trades)
            freq_buckets[count]['days'] += 1

        if freq_buckets:
            lines.append("**Frequency vs Win Rate (Sweet Spot):**\n")
            lines.append("| Trades/Day | Days | Total Trades | Win Rate | Avg P&L |")
            lines.append("|------------|------|--------------|----------|---------|")
            for freq in sorted(freq_buckets.keys()):
                bucket = freq_buckets[freq]
                bucket_trades = bucket['trades']
                wins = sum(1 for t in bucket_trades if (t['pnl'] or 0) > 0)
                total = len(bucket_trades)
                win_rate = wins / total * 100 if total > 0 else 0
                avg_pnl = sum(t['pnl'] or 0 for t in bucket_trades) / total if total > 0 else 0
                lines.append(
                    f"| {freq} | {bucket['days']} | {total} "
                    f"| {win_rate:.1f}% | ${avg_pnl:+.2f} |"
                )
            lines.append("")

        return "\n".join(lines)

    def _build_budget_status(self) -> str:
        """Build budget status table."""
        budgets = self.db.get_all_budgets()

        if not budgets:
            return "### Budget Status\n\nNo budget data available.\n"

        lines = ["### Budget Status\n"]
        lines.append("| Strategy | Budget | Drawdown | Committed | Available | % Available |")
        lines.append("|----------|--------|----------|-----------|-----------|-------------|")
        for name, b in budgets.items():
            pct = b['available'] / b['budget'] * 100 if b['budget'] > 0 else 0
            lines.append(
                f"| {name} | ${b['budget']:.0f} | ${b['drawdown']:.2f} "
                f"| ${b['committed']:.2f} | ${b['available']:.2f} | {pct:.1f}% |"
            )
        lines.append("")

        return "\n".join(lines)

    def _build_notable_trades(self, start_date: str, end_date: str) -> str:
        """Build worst 10 and best 10 trades tables."""
        worst = self.db.query_trades(
            start_date=start_date, end_date=end_date,
            order_by='pnl', descending=False, limit=10
        )
        best = self.db.query_trades(
            start_date=start_date, end_date=end_date,
            order_by='pnl', descending=True, limit=10
        )

        lines = []

        # Worst trades
        lines.append("### Worst 10 Trades\n")
        if worst:
            lines.append(self._format_trade_table(worst))
        else:
            lines.append("No trades in this period.\n")

        # Best trades
        lines.append("### Best 10 Trades\n")
        if best:
            lines.append(self._format_trade_table(best))
        else:
            lines.append("No trades in this period.\n")

        return "\n".join(lines)

    def _format_trade_table(self, trades: list) -> str:
        """Format trade rows as a markdown table."""
        lines = []
        lines.append("| # | Date | Symbol | Strategy | Direction | Entry | Exit | P&L | P&L % | Exit Reason | Hold (h) |")
        lines.append("|---|------|--------|----------|-----------|-------|------|-----|-------|-------------|----------|")
        for i, t in enumerate(trades, 1):
            # Calculate hold time
            hold_hours = ''
            try:
                entry_dt = datetime.fromisoformat(str(t['entry_time']).replace('Z', '+00:00'))
                exit_dt = datetime.fromisoformat(str(t['exit_time']).replace('Z', '+00:00'))
                hold_hours = f"{(exit_dt - entry_dt).total_seconds() / 3600:.1f}"
            except (ValueError, TypeError, AttributeError):
                hold_hours = 'N/A'

            exit_date = ''
            try:
                exit_date = str(t['exit_time'])[:10]
            except (TypeError, AttributeError):
                exit_date = 'N/A'

            pnl = t['pnl'] or 0
            pnl_pct = t['pnl_pct'] or 0
            entry_price = t['entry_price'] or 0
            exit_price = t['exit_price'] or 0

            lines.append(
                f"| {i} | {exit_date} | {t['symbol']} | {t['strategy']} "
                f"| {t['direction']} | ${entry_price:.2f} | ${exit_price:.2f} "
                f"| ${pnl:+.2f} | {pnl_pct:+.1f}% | {t['exit_reason']} | {hold_hours} |"
            )
        lines.append("")
        return "\n".join(lines)

    def _build_daily_pnl(self, start_date: str, end_date: str) -> str:
        """Build daily P&L trend table."""
        daily = self.db.get_daily_pnl(start_date=start_date, end_date=end_date)

        if not daily:
            return "### Daily P&L Trend\n\nNo daily data in this period.\n"

        lines = ["### Daily P&L Trend\n"]
        lines.append("| Date | Trades | W/L | Daily P&L | Cumulative |")
        lines.append("|------|--------|-----|-----------|------------|")
        for d in daily:
            lines.append(
                f"| {d['date']} | {d['trade_count']} "
                f"| {d['wins']}/{d['losses']} "
                f"| ${d['daily_pnl']:+.2f} | ${d['cumulative_pnl']:+.2f} |"
            )
        lines.append("")

        return "\n".join(lines)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _get_filtered_config(self) -> dict:
        """Return config with only tunable sections (no secrets/infra)."""
        return {k: v for k, v in self.config.items() if k in CONFIG_SECTIONS_TO_INCLUDE}


# =============================================================================
# Standalone CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate AI Configuration Advisor Package"
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Period in days (default: auto-detect from last package, or 14 days)"
    )
    parser.add_argument(
        "--db", type=str, default="trading_bot.db",
        help="Path to trading_bot.db"
    )
    parser.add_argument(
        "--config", type=str, default="config.yaml",
        help="Path to config.yaml"
    )

    args = parser.parse_args()

    advisor = AIConfigAdvisor(
        db_path=args.db,
        config_path=args.config,
    )
    filepath = advisor.generate_package(days=args.days)
    print(f"\nAI Config Advisor package generated: {filepath}")
