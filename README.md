# Swing Trading Bot

Automated options trading bot based on order book liquidity analysis using Interactive Brokers.

## Features

- **Order Book Analysis**: Real-time analysis of market depth to identify liquidity zones
- **Pattern Detection**: Detects support/resistance tests, breakouts, and rejections
- **Rule-Based Trading**: Configurable entry/exit rules based on pattern confidence
- **Risk Management**: Position sizing, stop losses, profit targets, and position limits
- **Paper Trading**: Built-in support for paper trading to test strategies

## Architecture

```
main.py                 # Main orchestrator
├── ib_wrapper.py       # IB API interface
├── liquidity_analyzer.py  # Order book analysis
└── trading_engine.py   # Trading logic & execution
```

## Requirements

- Python 3.8+
- Interactive Brokers account (paper or live)
- TWS or IB Gateway running
- Market data subscription (for live depth data)

## Installation

1. **Install dependencies**:
```bash
pip install -r requirements.txt
```

2. **Configure TWS/Gateway**:
   - Enable API connections in TWS/Gateway settings
   - Set API port (7497 for paper, 7496 for live)
   - Enable "Download open orders on connection"

3. **Edit configuration**:
```bash
# Edit config.yaml with your settings
nano config.yaml
```

## Configuration

Key settings in `config.yaml`:

### Connection
```yaml
ib_connection:
  host: "127.0.0.1"
  port: 7497  # 7497=paper, 7496=live
  client_id: 1
```

### Symbols to Monitor
```yaml
symbols:
  - "NVDA"
  - "AAPL"
  - "TSLA"
```

### Risk Management
```yaml
risk_management:
  max_position_size: 2000    # Max $ per position
  max_positions: 3           # Max concurrent positions
  position_size_pct: 0.02    # 2% of account per trade
  profit_target_pct: 0.50    # Take profit at 50%
  stop_loss_pct: 0.30        # Stop loss at 30%
```

### Trading Rules
```yaml
trading_rules:
  rejection_support_confidence: 0.65
  breakout_up_confidence: 0.70
  rejection_resistance_confidence: 0.65
  breakout_down_confidence: 0.70
```

## Usage

### Start the Bot

```bash
python main.py
```

### Monitor Logs

The bot logs to both console and `trading_bot.log`:

```bash
tail -f trading_bot.log
```

### Stop the Bot

Press `Ctrl+C` for graceful shutdown.

## Trading Logic

### Entry Signals

The bot enters trades when these patterns are detected:

1. **Rejection at Support** → Buy calls
   - Price bounces off strong support level
   - High order book confidence
   
2. **Breakout Up** → Buy calls
   - Strong buy-side order imbalance (>60%)
   - Heavy accumulation detected

3. **Rejection at Resistance** → Buy puts
   - Price rejected at strong resistance
   - High order book confidence

4. **Breakout Down** → Buy puts
   - Strong sell-side order imbalance (>60%)
   - Heavy distribution detected

### Exit Rules

Positions are exited when:

- **Profit target reached** (default: 50% gain)
- **Stop loss hit** (default: 30% loss)
- **Time limit reached** (default: 30 days)

### Option Selection

- **Expiration**: 14-45 days out
- **Calls**: 2% out-of-the-money
- **Puts**: 2% out-of-the-money

## Testing Strategy

### Phase 1: Paper Trading
1. Set `enable_paper_trading: true` in config
2. Run bot with small position sizes
3. Monitor performance for 1-2 weeks
4. Adjust parameters based on results

### Phase 2: Strategy Refinement
1. Review trade logs and patterns
2. Adjust confidence thresholds
3. Modify position sizing
4. Fine-tune exit rules

### Phase 3: Live Trading
1. Start with minimal capital
2. Use `require_manual_approval: true`
3. Gradually increase automation
4. Monitor daily performance

## Safety Features

```yaml
safety:
  require_manual_approval: false  # Approve each trade manually
  max_daily_loss: 500            # Stop trading after $500 loss
  trading_hours_only: true       # Only trade 9:30-16:00 ET
  emergency_stop: false          # Emergency kill switch
```

### Emergency Stop

To immediately stop all trading:

1. Set `emergency_stop: true` in config
2. Or press Ctrl+C for graceful shutdown
3. Bot will not enter new trades but will monitor existing positions

## Monitoring & Logs

### Status Output (every 10 scans)
```
============================================================
BOT STATUS
============================================================
Uptime: 2:34:15
Scans completed: 154
Signals detected: 23
Trades entered: 5
Trades exited: 2
Open positions: 3/3
Active contracts: NVDA250221C150, AAPL250221C195, TSLA250221C275
Account value: $42,156.78
============================================================
```

### Log Levels
- `DEBUG`: All detection details
- `INFO`: Signal detections and trades
- `WARNING`: Issues and skipped trades
- `ERROR`: Failures and exceptions

## Development

### Adding New Patterns

Edit `liquidity_analyzer.py`:

```python
class Pattern(Enum):
    YOUR_NEW_PATTERN = "your_pattern"

# Add detection logic in detect_pattern()
```

### Adding New Rules

Edit `config.yaml`:

```yaml
trading_rules:
  your_pattern_confidence: 0.70
```

Edit `trading_engine.py`:

```python
# Add to _setup_rules()
TradeRule(
    pattern=Pattern.YOUR_NEW_PATTERN,
    direction=TradeDirection.LONG_CALL,
    min_confidence=0.70,
    entry_condition="Your condition description"
)
```

### Custom Position Sizing

Edit `calculate_position_size()` in `trading_engine.py` to implement your own logic.

## Troubleshooting

### "Failed to connect to IB"
- Check TWS/Gateway is running
- Verify API port in config matches TWS
- Enable API connections in TWS settings

### "No market depth data"
- Market depth requires subscription (NASDAQ TotalView ~$15/mo)
- For testing, use free Cboe/IEX data (limited depth)
- Check subscriptions in Account Management

### "Could not get option price"
- Option may be illiquid
- Try different strikes or expirations
- Adjust `min_dte` and `max_dte` in config

### "Maximum positions reached"
- Increase `max_positions` in config
- Or wait for existing positions to exit
- Check position exit rules

## Disclaimer

This software is for educational purposes only. Trading options involves significant risk of loss. Use at your own risk. Always test thoroughly with paper trading before using real money.

## License

MIT License - See LICENSE file for details

## Support

For issues or questions, check the logs first. Common problems are usually configuration-related.
