# Ebitrate Arbitrage Bot — How To Run

## Prerequisites

Before starting, make sure:

1. **Redis is running** (used for dedup — prevents duplicate alerts)
   ```bash
   redis-cli ping
   # Should respond: PONG
   # If not running, start it:
   sudo systemctl start redis
   ```

2. **Your `.env` file is configured** (already done — do NOT change unless needed)
   - Location: `/home/tunchi/Desktop/ebitrate/arb_bot/.env`
   - Key settings you might want to adjust:

   | Variable         | Current Value | What It Does                            |
   |------------------|---------------|-----------------------------------------|
   | `MIN_EDGE`       | `0.005`       | Minimum margin to alert (0.5%)          |
   | `BANKROLL`       | `1000`        | Bankroll used for stake calculations    |
   | `POLL_INTERVAL`  | `30`          | Seconds between scan cycles             |
   | `MAX_ODDS_AGE_SEC` | `90`        | Max age of odds data before discarding  |
   | `EXECUTION_MODE` | `limited`     | `paper` / `limited` / `full`            |

---

## Starting the Bot

### Option 1: Simple Start (Recommended)

Open a terminal and run:

```bash
cd /home/tunchi/Desktop/ebitrate/arb_bot
./run.sh paper
```

This will:
- Activate the virtual environment
- Install any missing dependencies
- Check Redis is running
- Start the bot in **paper mode** (alerts only, no real bets)
- Auto-restart if the bot crashes

### Option 2: Background Start (Keeps Running After You Close Terminal)

```bash
cd /home/tunchi/Desktop/ebitrate/arb_bot
nohup ./run.sh paper > bot_startup.log 2>&1 &
```

### Option 3: Direct Python (For Debugging)

```bash
cd /home/tunchi/Desktop/ebitrate/arb_bot
source venv/bin/activate
python3 main.py paper
```

---

## Execution Modes

| Mode      | Command            | What Happens                                    |
|-----------|--------------------|-------------------------------------------------|
| `paper`   | `./run.sh paper`   | Scans & alerts only. No real money. **Safest.**  |
| `limited` | `./run.sh limited` | Places real bets with capped stakes.             |
| `full`    | `./run.sh full`    | Full execution. Real bets. **Use with caution.** |

---

## Monitoring the Bot

### Watch Live Logs
```bash
tail -f /home/tunchi/Desktop/ebitrate/arb_bot/arb_bot.log
```

### Access the Live Dashboard
The bot now includes a real-time web dashboard. Once started, you can access it at:
**http://localhost:8050**

The dashboard provides:
- Live Arbitrage Signals
- Real-time PnL & Win Rate
- Treasury/Wallet Balances
- System Health & Latency Metrics

### Check If the Bot Is Running
```bash
pgrep -af main.py
```

### See Recent Detections
```bash
grep "Detected" /home/tunchi/Desktop/ebitrate/arb_bot/arb_bot.log | tail -10
```

### See Recent Telegram Alerts
```bash
grep "Telegram alert sent" /home/tunchi/Desktop/ebitrate/arb_bot/arb_bot.log | tail -10
```

### Check Which Scrapers Are Working
```bash
grep "Scraped" /home/tunchi/Desktop/ebitrate/arb_bot/arb_bot.log | tail -10
```

---

## Stopping the Bot

### If Running in Foreground
Press `Ctrl+C`. This will gracefully shut down both the Engine and the API Server.

### If Running in Background
To stop everything (Engine + API Server):
```bash
pkill -f "run.sh"
pkill -f "main.py"
pkill -f "api_server.py"
```

> **IMPORTANT:** Always make sure only ONE instance is running. Multiple instances
> will send duplicate alerts. Check with: `pgrep -af main.py`

---

## Troubleshooting

### Bot Starts But Detects 0 Arbs
This is **normal** — real arbitrage opportunities are rare. The bot scans every
30 seconds and will alert you the moment one appears. Be patient.

### "Redis not responding"
```bash
sudo systemctl start redis
```

### Scraper Errors (1xbet/Melbet "Could not acquire context")
The browser-based scrapers (1xbet, melbet, mozzartbet) need Playwright browsers.
If browser scrapers fail, the bot will wait for the next cycle.

### Bot Keeps Crashing
Check the log for the error:
```bash
tail -50 /home/tunchi/Desktop/ebitrate/arb_bot/arb_bot.log
```

### Alerts Going to DMs Instead of Channel
Make sure `.env` has the correct channel ID:
```
TELEGRAM_CHAT_ID=-1003923758566
```
Then restart the bot.

---

## File Locations

| File | Purpose |
|------|---------|
| `/home/tunchi/Desktop/ebitrate/arb_bot/.env` | All configuration |
| `/home/tunchi/Desktop/ebitrate/arb_bot/run.sh` | Startup script |
| `/home/tunchi/Desktop/ebitrate/arb_bot/main.py` | Main engine loop |
| `/home/tunchi/Desktop/ebitrate/arb_bot/arb_bot.log` | All logs |
| `/home/tunchi/Desktop/ebitrate/arb_bot/arb_detector.py` | Arbitrage detection logic |
| `/home/tunchi/Desktop/ebitrate/arb_bot/notifier.py` | Telegram alert sender |

---

## Quick Start Cheat Sheet

```bash
# Start
cd /home/tunchi/Desktop/ebitrate/arb_bot && nohup ./run.sh paper > bot_startup.log 2>&1 &

# Check status
pgrep -af main.py

# Watch logs
tail -f /home/tunchi/Desktop/ebitrate/arb_bot/arb_bot.log

# Stop
pkill -f "python.*main.py"
```
