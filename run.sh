#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# run.sh — One-command production startup for the Arb Engine
# Usage: ./run.sh [paper|limited|full]
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-paper}"
VENV="$SCRIPT_DIR/venv"
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"
RESTART_DELAY=5   # seconds between auto-restarts

echo "════════════════════════════════════════════"
echo "  Ebitrate Arbitrage Engine — Startup"
echo "  Mode: $MODE"
echo "════════════════════════════════════════════"

# ── 1. Virtual environment ─────────────────────────────────
if [ ! -d "$VENV" ]; then
    echo "[setup] Creating virtual environment..."
    python3 -m venv "$VENV"
fi

echo "[setup] Installing dependencies..."
$PIP install --quiet --upgrade pip
$PIP install --quiet -r requirements.txt

# ── 2. Playwright browsers ──────────────────────────────────
echo "[setup] Ensuring Playwright Chromium is installed..."
$PYTHON -m playwright install chromium 2>&1 | tail -3

# ── 3. Redis — start if not running (Bug #2 fix) ────────────
echo "[check] Verifying Redis connectivity..."
if ! redis-cli ping > /dev/null 2>&1; then
    echo "[WARN]  Redis not responding. Starting local Redis..."
    if command -v redis-server &>/dev/null; then
        redis-server --daemonize yes --port 6379 --loglevel warning
        sleep 1
        if redis-cli ping > /dev/null 2>&1; then
            echo "[OK]    Redis started."
        else
            echo "[WARN]  Could not start Redis — dedup disabled, continuing anyway."
        fi
    else
        echo "[WARN]  redis-server not found. Continuing without Redis (dedup disabled)."
    fi
else
    echo "[OK]    Redis is running."
fi

# ── 4. Environment validation ───────────────────────────────
if [ ! -f ".env" ]; then
    echo "[ERROR] .env file not found. Copy .env.example and fill in your keys."
    exit 1
fi

if grep -q "^ODDS_API_KEY=$" .env 2>/dev/null || ! grep -q "ODDS_API_KEY" .env; then
    echo "[WARN]  ODDS_API_KEY is not set in .env — odds fetching will fail."
fi

# ── 5. Set execution mode ───────────────────────────────────
export EXECUTION_MODE="$MODE"
case "$MODE" in
    full)
        echo "[WARN]  FULL execution mode. Real bets WILL be placed!"
        export DRY_RUN=False
        ;;
    limited)
        echo "[INFO]  LIMITED mode. Stakes capped."
        export DRY_RUN=False
        ;;
    paper|*)
        echo "[INFO]  PAPER mode. No real bets placed."
        export DRY_RUN=True
        ;;
esac

# ── 6. Launch API Server in background ───────────────────────
echo "[start] Launching API Server on port 8050..."
$PYTHON api_server.py > api_server.log 2>&1 &
API_PID=$!

# Cleanup on exit
trap "echo '[stop] Shutting down...'; kill $API_PID 2>/dev/null || true; rm -f bot.pid; exit" INT TERM EXIT

# ── 7. Launch Engine with auto-restart (Bug #1 fix) ───────────
echo ""
echo "[start] Launching arbitrage engine with auto-restart..."
echo "[start] Dashboard available at: http://localhost:8050"
echo "[start] Press Ctrl+C to stop everything."
echo ""

CRASH_COUNT=0
while true; do
    $PYTHON main.py
    EXIT_CODE=$?

    # Exit code 1 from sys.exit(1) means circuit breaker or hard stop — don't restart
    if [ $EXIT_CODE -eq 1 ]; then
        echo ""
        echo "[STOP]  Engine exited with code 1 (circuit breaker / hard stop). Not restarting."
        echo "[STOP]  Check arb_bot.log for the cause."
        exit 1
    fi

    CRASH_COUNT=$((CRASH_COUNT + 1))
    echo ""
    echo "[RESTART] Engine stopped (exit=$EXIT_CODE, crash #$CRASH_COUNT). Restarting in ${RESTART_DELAY}s..."
    sleep $RESTART_DELAY
done
