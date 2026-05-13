"""
eBitrate Dashboard API Server.

Reads from engine JSON artifacts and exposes them via REST endpoints.
Serves the frontend SPA from the `frontend/` directory.

Usage:
    python api_server.py          # starts on port 8050
    uvicorn api_server:app --reload --port 8050
"""
import json
import os
import time
import signal
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="eBitrate Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Paths ─────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
METRICS_PATH = BASE_DIR / "metrics_snapshot.json"
TRADE_JOURNAL_PATH = BASE_DIR / "trade_journal.json"
BOOKMAKER_PROFILES_PATH = BASE_DIR / "bookmaker_profiles.json"
HEDGE_JOURNAL_PATH = BASE_DIR / "hedge_journal.json"
BURNED_ACCOUNTS_PATH = BASE_DIR / "burned_accounts.json"
PID_PATH = BASE_DIR / "bot.pid"
ENV_PATH = BASE_DIR / ".env"
EVENTS_PATH = BASE_DIR / "events.jsonl"
SIGNALS_PATH = BASE_DIR / "active_signals.json"
TREASURY_PATH = BASE_DIR / "treasury_snapshot.json"


def _read_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def _engine_running() -> bool:
    """Check if the engine process is alive via bot.pid."""
    if not PID_PATH.exists():
        return False
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, 0)  # signal 0 = check existence
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


# ── API Endpoints ─────────────────────────────────────────────

@app.get("/api/status")
def get_status():
    metrics = _read_json(METRICS_PATH, {})
    running = _engine_running()
    return {
        "engine_running": running,
        "uptime_sec": metrics.get("uptime_sec", 0),
        "cycles": metrics.get("cycles", 0),
        "snapshot_at": metrics.get("snapshot_at", ""),
        "execution_mode": _get_config_value("EXECUTION_MODE", "paper"),
        "dry_run": _get_config_value("DRY_RUN", "True"),
    }


@app.get("/api/metrics")
def get_metrics():
    return _read_json(METRICS_PATH, {})


@app.get("/api/trades")
def get_trades(
    limit: int = Query(100, ge=1, le=1000),
    result: Optional[str] = Query(None),
):
    trades = _read_json(TRADE_JOURNAL_PATH, [])
    if result:
        trades = [t for t in trades if t.get("result") == result]
    # Most recent first
    trades = sorted(trades, key=lambda t: t.get("timestamp", 0), reverse=True)
    return {
        "total": len(trades),
        "trades": trades[:limit],
    }


@app.get("/api/trades/summary")
def get_trade_summary():
    trades = _read_json(TRADE_JOURNAL_PATH, [])
    total = len(trades)
    if total == 0:
        return {"total": 0, "full_success": 0, "partial": 0, "total_fail": 0,
                "total_pnl": 0, "avg_pnl": 0, "win_rate": 0, "avg_latency": 0}

    full_success = sum(1 for t in trades if t.get("result") == "full_success")
    partial = sum(1 for t in trades if "partial" in (t.get("result") or ""))
    total_fail = sum(1 for t in trades if t.get("result") == "total_fail")
    total_pnl = sum(t.get("realized_profit", 0) for t in trades)
    avg_pnl = total_pnl / total
    avg_latency = sum(t.get("latency_ms", 0) for t in trades) / total
    win_rate = (full_success / total) * 100

    return {
        "total": total,
        "full_success": full_success,
        "partial": partial,
        "total_fail": total_fail,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
        "win_rate": round(win_rate, 1),
        "avg_latency": round(avg_latency, 1),
    }


@app.get("/api/trades/pnl-series")
def get_pnl_series():
    """Cumulative PnL series for charting."""
    trades = _read_json(TRADE_JOURNAL_PATH, [])
    trades = sorted(trades, key=lambda t: t.get("timestamp", 0))
    cumulative = 0.0
    series = []
    for t in trades:
        cumulative += t.get("realized_profit", 0)
        series.append({
            "timestamp": t.get("timestamp", 0),
            "cumulative_pnl": round(cumulative, 2),
            "profit": round(t.get("realized_profit", 0), 2),
            "result": t.get("result", ""),
        })
    return series


@app.get("/api/bookmakers")
def get_bookmakers():
    profiles = _read_json(BOOKMAKER_PROFILES_PATH, {})
    burned = _read_json(BURNED_ACCOUNTS_PATH, [])
    return {
        "profiles": profiles,
        "burned_accounts": burned,
    }


@app.get("/api/hedges")
def get_hedges():
    return _read_json(HEDGE_JOURNAL_PATH, [])


@app.get("/api/signals")
def get_signals():
    return _read_json(SIGNALS_PATH, [])


@app.get("/api/treasury")
def get_treasury():
    """Return live treasury data from snapshot."""
    from config import BANKROLL, MAX_DAILY_EXPOSURE
    
    state = _read_json(TREASURY_PATH, {
        "bookmakers": {},
        "exchange": {"balance": 0.0, "currency": "KES"}
    })

    return {
        "bankroll": BANKROLL,
        "max_daily_exposure": MAX_DAILY_EXPOSURE,
        "bookmakers": state.get("bookmakers", {}),
        "exchange": state.get("exchange", {"balance": 0.0, "currency": "KES"}),
    }


@app.get("/api/config")
def get_config():
    """Return safe, non-secret configuration values."""
    try:
        from config import (
            MIN_EDGE, MAX_ODDS_AGE_SEC, BANKROLL, DRY_RUN,
            EXECUTION_MODE, MAX_DAILY_EXPOSURE, MAX_TRADES_PER_MIN,
            MAX_CONSECUTIVE_LOSSES, EXECUTION_ORDER, MAX_HEDGE_LOSS,
            SPORTS, TARGET_BOOKMAKERS, MARKETS, POLL_INTERVAL,
            SESSION_POOL_SIZE, GRACEFUL_DEGRADATION_THRESHOLD,
            EDGE_STRONG_MIN, EDGE_MARGINAL_MIN, EDGE_MAX_AGE_SEC,
            EDGE_MIN_BM_HEALTH,
        )
        return {
            "min_edge": MIN_EDGE,
            "max_odds_age_sec": MAX_ODDS_AGE_SEC,
            "bankroll": BANKROLL,
            "dry_run": DRY_RUN,
            "execution_mode": EXECUTION_MODE,
            "max_daily_exposure": MAX_DAILY_EXPOSURE,
            "max_trades_per_min": MAX_TRADES_PER_MIN,
            "max_consecutive_losses": MAX_CONSECUTIVE_LOSSES,
            "execution_order": EXECUTION_ORDER,
            "max_hedge_loss": MAX_HEDGE_LOSS,
            "sports": SPORTS,
            "target_bookmakers": TARGET_BOOKMAKERS,
            "markets": MARKETS,
            "poll_interval": POLL_INTERVAL,
            "session_pool_size": SESSION_POOL_SIZE,
            "graceful_degradation_threshold": GRACEFUL_DEGRADATION_THRESHOLD,
            "edge_strong_min": EDGE_STRONG_MIN,
            "edge_marginal_min": EDGE_MARGINAL_MIN,
            "edge_max_age_sec": EDGE_MAX_AGE_SEC,
            "edge_min_bm_health": EDGE_MIN_BM_HEALTH,
        }
    except Exception as e:
        return {"error": str(e)}


def _get_config_value(key: str, default: str = "") -> str:
    """Read a single value from .env without importing the full config."""
    if not ENV_PATH.exists():
        return default
    try:
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return default


# ── Static file serving ───────────────────────────────────────
FRONTEND_DIR = BASE_DIR / "frontend"


@app.get("/")
def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


# Mount static files AFTER explicit routes
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8050, reload=True)
