# Installation Guide

## Prerequisites

| Requirement | Details |
|-------------|---------|
| **Python** | 3.8 or higher |
| **Interactive Brokers Account** | Paper or live trading account |
| **TWS or IB Gateway** | Running locally on the same machine (or accessible via network) |
| **Market Data Subscription** | Required for live depth data (Level 2). NASDAQ TotalView ~$15/mo recommended |
| **Operating System** | Windows, macOS, or Linux |

---

## Step 1: Clone the Repository

```bash
git clone <your-repo-url> trading-bot
cd trading-bot
```

---

## Step 2: Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Dependencies

| Package | Purpose | Required |
|---------|---------|----------|
| `ib_insync>=0.9.86` | Interactive Brokers API wrapper | Yes |
| `PyYAML>=6.0` | Configuration file parsing | Yes |
| `requests` | Discord webhook HTTP calls | Yes |
| `colorama` | Colored terminal output (Windows support) | Yes |
| `pandas>=2.0.0` | Execution quality reports, data export | Recommended |
| `numpy>=1.24.0` | Numerical operations for analysis | Recommended |

> **Note**: `pandas` and `numpy` are only required for `snapshot_analyzer.py --report` (global execution quality report). The bot runs fine without them for normal trading.

---

## Step 3: Install & Configure TWS or IB Gateway

### Option A: Trader Workstation (TWS)

1. Download TWS from [Interactive Brokers](https://www.interactivebrokers.com/en/trading/tws.php)
2. Install and log in with your IB credentials
3. Configure API settings:
   - **Edit > Global Configuration > API > Settings**
   - Check **Enable ActiveX and Socket Clients**
   - Check **Download open orders on connection**
   - Set **Socket port**: `7497` (paper) or `7496` (live)
   - Uncheck **Read-Only API** (the bot needs to place orders)
   - Add `127.0.0.1` to **Trusted IPs** (or the IP where the bot runs)

### Option B: IB Gateway (Headless)

IB Gateway is lighter-weight than TWS (no GUI). Recommended for server deployments.

1. Download IB Gateway from [Interactive Brokers](https://www.interactivebrokers.com/en/trading/ibgateway-stable.php)
2. Log in and configure:
   - API port: `4001` (live) or `4002` (paper)
   - Enable API connections

### Port Reference

| Application | Account Type | Default Port |
|-------------|-------------|--------------|
| TWS | Paper | 7497 |
| TWS | Live | 7496 |
| IB Gateway | Paper | 4002 |
| IB Gateway | Live | 4001 |

---

## Step 4: Configure the Bot

Edit `config.yaml` with your settings:

```yaml
# Match your TWS/Gateway port
ib_connection:
  host: "127.0.0.1"
  port: 7497          # Change to match your setup
  client_id: 1        # Must be unique per bot instance

# Symbols to monitor
strategies:
  swing_conservative:
    symbols: ["NVDA", "AAPL", "TSLA"]
    # ... other settings
```

> See [CONFIGURATION.md](CONFIGURATION.md) for the complete configuration reference.

### Minimum Configuration Changes

At a minimum, you should verify:

1. **`ib_connection.port`** — matches your TWS/Gateway API port
2. **`strategies.*.symbols`** — symbols you want to monitor
3. **`safety.max_daily_loss`** — maximum daily loss you're comfortable with
4. **`notifications.discord_webhook`** — your Discord webhook URL (or leave empty to disable)

---

## Step 5: Set Up Discord Notifications (Optional)

1. In your Discord server: **Server Settings > Integrations > Webhooks**
2. Click **New Webhook**, name it, and select a channel
3. Copy the webhook URL
4. Paste it into `config.yaml`:

```yaml
notifications:
  discord_webhook: "https://discord.com/api/webhooks/YOUR_WEBHOOK_URL"
```

Test it after starting the bot with the `/test_notify` command.

---

## Step 6: Start the Bot

```bash
python main.py
```

### First Run

On first run, the bot will:
1. Create `trading_bot.db` (SQLite database)
2. Connect to IB TWS/Gateway
3. Subscribe to market data for configured symbols
4. Initialize market regime detection (SPY/VIX analysis)
5. Begin scanning for signals

### Verify Successful Startup

You should see output like:
```
[INFO] Connecting to IB at 127.0.0.1:7497...
[INFO] Connected to IB
[INFO] Account value: $XX,XXX.XX
[INFO] Loaded strategy: swing_conservative (swing_trading)
[INFO] Loaded strategy: swing_aggressive (swing_trading)
[INFO] Subscribing to market data for NVDA...
[INFO] Market regime: Bull Trend (VIX: 18.5)
[INFO] Starting main loop...
```

Type `/help` to see all available commands.

---

## Running Multiple Bot Instances

If you need to run multiple instances (e.g., different strategy sets):

1. Each instance must use a **different `client_id`** in `config.yaml`
2. Each instance uses its own `trading_bot.db`
3. Be careful not to exceed IB's market data line limits

```yaml
# Instance 1: config.yaml
ib_connection:
  client_id: 1

# Instance 2: config2.yaml (copy and modify)
ib_connection:
  client_id: 2
```

---

## Upgrading

```bash
# Pull latest code
git pull

# Update dependencies
pip install -r requirements.txt --upgrade
```

The database schema handles migrations automatically. On startup, missing columns are added without data loss.

---

## Uninstalling

1. Stop the bot (`/quit` or Ctrl+C)
2. Optionally back up your data:
   ```bash
   cp trading_bot.db trading_bot_backup.db
   cp -r snapshots/ snapshots_backup/
   ```
3. Remove the directory

The bot does not install system services or modify system configuration. All files are self-contained in the project directory.
