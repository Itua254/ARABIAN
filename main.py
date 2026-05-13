"""
Arbitrage Engine — Phase 3+ / V5 Production Main Loop.

Integrates:
  - Edge Classifier gate before execution queue
  - MetricsCollector observability layer
  - Session pool preloading on startup
  - Metrics snapshot after every cycle
  - Hard-stop via MetricsCollector (replaces inline PnL check)
"""
import asyncio
import heapq
import random
import os
import sys
import time
from typing import Dict, Any

from odds_fetcher      import fetch_all_odds
from arb_detector      import process_events
from notifier          import send_telegram_alert
from config            import (
    POLL_INTERVAL, DEDUP_TTL, MAX_DAILY_EXPOSURE,
    MAX_TRADES_PER_MIN, MAX_CONSECUTIVE_LOSSES, EXECUTION_ORDER,
    TELEGRAM_CHAT_ID,
)
from logger            import get_logger, log_event
from state             import TradeState, RiskLedger, ExecResult, Trade
from redis_client      import acquire_lock
from identity_manager  import IdentityManager
from execution_engine  import ExecutionEngine
from hedge_engine      import HedgeEngine
from pnl_engine        import PnLEngine
from bookmaker_profiler import BookmakerProfiler
from edge_classifier   import classify
from metrics           import MetricsCollector

logger  = get_logger("main")
metrics = MetricsCollector.instance()

from treasury import TreasuryManager

# ── Global singletons ─────────────────────────────────────────
risk_ledger       = RiskLedger()
identity_manager  = IdentityManager()
bookmaker_profiler = BookmakerProfiler()
treasury          = TreasuryManager(identity_manager)
execution_engine  = ExecutionEngine(identity_manager, bookmaker_profiler, treasury)
hedge_engine      = HedgeEngine(identity_manager, treasury)
pnl_engine        = PnLEngine()

# ── Rate / exposure state ─────────────────────────────────────
current_exposure: float    = 0.0
trades_timestamps: list    = []
loss_count: int            = 0


def can_execute(stake: float) -> bool:
    return (current_exposure + stake) <= MAX_DAILY_EXPOSURE


def throttle() -> bool:
    global trades_timestamps
    now = time.time()
    trades_timestamps = [t for t in trades_timestamps if now - t < 60]
    return len(trades_timestamps) < MAX_TRADES_PER_MIN


async def execution_delay(arb: Dict[str, Any]) -> bool:
    """Check arb latency kill-switch (v6 §5)"""
    age = time.time() - arb.get("detected_at", time.time())
    if age > 1.0:
        return False
    return True


async def run_cycle() -> None:
    global current_exposure, trades_timestamps, loss_count

    # ── Circuit breaker ───────────────────────────────────────
    if loss_count >= MAX_CONSECUTIVE_LOSSES:
        logger.critical("CIRCUIT BREAKER: max consecutive losses. Shutting down.")
        log_event("circuit_breaker", {"consecutive_losses": loss_count})
        sys.exit(1)

    metrics.inc("cycles")
    logger.info("── Polling cycle start ──────────────────────────────")

    # 1. Fetch (V6 Scraper Coordinator)
    fetch_start = time.time()
    try:
        events = await fetch_all_odds(identity_manager)
    except Exception as e:
        logger.error({"event": "fetch_failed", "error": str(e)})
        return
    metrics.record_latency("fetch_ms", (time.time() - fetch_start) * 1000)

    if not events:
        logger.info("No events fetched.")
        return

    # 2. Detect
    try:
        arbs = process_events(events)
        logger.info(f"Detected {len(arbs)} raw arbs.")
        metrics.inc("arbs_detected", len(arbs))
        
        # Dump to active_signals.json for the frontend
        try:
            import json
            from pathlib import Path
            Path("active_signals.json").write_text(json.dumps(arbs))
        except Exception as e:
            logger.error(f"Failed to write active_signals.json: {e}")
            
    except Exception as e:
        logger.error({"event": "detect_failed", "error": str(e)})
        return

    # ── IMMEDIATE Telegram alert for every detected arb ──────────────
    # Fires right here, before edge classification, Redis dedup, or
    # execution. The user sees every signal the moment it's found.
    for arb in arbs:
        try:
            await send_telegram_alert(arb)
        except Exception as tg_err:
            logger.warning(f"Telegram alert failed: {tg_err}")

    # ── Smoke Screen Trigger (Move 2) ──
    if not arbs and random.random() < 0.05:  # 5% chance when no arbs
        logger.info("Triggering Smoke Screen Module...")
        from smoke_screen import PunterModule
        punter = PunterModule(identity_manager)
        await punter.try_place_smoke_bet(events)

    # 3. Priority Queue (v6 §6)
    classified = []
    for arb in arbs:
        priority = classify(arb, profiler=bookmaker_profiler)
        if priority <= 0:
            metrics.inc("arbs_rejected")
            continue
        classified.append((-priority, arb))  # negated for max-heap

    logger.info(f"{len(classified)} arbs queued for execution.")

    # 4. Priority queue — highest edge first
    heapq.heapify(classified)

    # 5. Execute
    while classified:
        _, arb = heapq.heappop(classified)
        event_id = arb["event_id"]

        # Redis idempotency lock
        if not acquire_lock(event_id, ttl_sec=DEDUP_TTL):
            logger.debug(f"[{event_id}] Duplicate — skipping.")
            continue

        total_stake = sum(leg["stake"] for leg in arb.get("legs", []))

        if not can_execute(total_stake):
            logger.warning(f"[{event_id}] Max daily exposure reached.")
            continue

        if not throttle():
            logger.warning(f"[{event_id}] Rate limit hit — sleeping.")
            await asyncio.sleep(random.uniform(5, 15))
            continue

        # Build Trade object (v5 §3.4)
        trade = Trade(event_id=event_id, arb=arb)
        trade.transition(TradeState.VALIDATED)

        risk_ledger.register(event_id, {"arb": arb, "state": trade.state})
        metrics.inc("arbs_attempted")

        logger.info({
            "event":      "arb_queued",
            "event_id":   event_id,
            "match":      arb["match"],
            "margin_pct": arb["margin_pct"],
            "profit":     arb["profit"],
            "edge":       arb.get("edge_class"),
        })

        trade.transition(TradeState.EXECUTING)
        risk_ledger.active[event_id]["state"] = trade.state

        # Telegram already sent immediately on detection above.

        # Age check
        if not await execution_delay(arb):
            logger.warning(f"[{event_id}] Arb decayed before execution — skipping.")
            risk_ledger.clear(event_id)
            continue

        # Execute
        execution_start = time.time()
        result = ExecResult.TOTAL_FAIL
        try:
            result = await execution_engine.execute_arb(arb, risk_ledger)
        except Exception as e:
            logger.error({"event": "exec_exception", "event_id": event_id, "error": str(e)})
            loss_count += 1

        execution_latency = time.time() - arb.get("detected_at", execution_start)
        log_event("execution_complete", {
            "event_id": event_id,
            "result":   result,
            "latency_sec": round(execution_latency, 3),
        })

        # Handle result
        if result == ExecResult.FULL_SUCCESS:
            trade.transition(TradeState.SUCCESS)
            loss_count = 0
            current_exposure += total_stake
            trades_timestamps.append(time.time())
            metrics.inc("full_success")

        elif result in (ExecResult.PARTIAL_LEG1, ExecResult.PARTIAL_LEG2):
            trade.transition(TradeState.HEDGING)
            exposed_idx = 0 if result == ExecResult.PARTIAL_LEG1 else 1
            metrics.inc("hedges_triggered")

            logger.warning(f"[{event_id}] Partial fill — triggering hedge on leg {exposed_idx + 1}.")
            try:
                hedge_ok = await hedge_engine.hedge_leg(arb, exposed_leg_index=exposed_idx)
            except Exception as e:
                logger.error(f"[{event_id}] Hedge exception: {e}")
                hedge_ok = False

            if hedge_ok:
                metrics.inc("hedges_success")
                logger.info(f"[{event_id}] Hedge succeeded.")
            else:
                metrics.inc("hedges_failed")
                logger.error(f"[{event_id}] Hedge failed — unhedged exposure remains!")
                loss_count += 1

            current_exposure += arb["legs"][exposed_idx]["stake"]
            trades_timestamps.append(time.time())

        else:  # TOTAL_FAIL
            trade.transition(TradeState.FAILED)
            loss_count += 1
            metrics.inc("total_fail")

        # PnL journal
        latency_ms = execution_latency * 1000
        realized   = pnl_engine.record_trade(arb, result, latency_ms)
        metrics.record_pnl(realized)

        # State → FINAL
        trade.transition(TradeState.FINAL)
        risk_ledger.clear(event_id)

    # 6. End-of-cycle observability snapshot
    metrics.snapshot()

    # 7. Hard-stop check (delegated to MetricsCollector)
    if metrics.hard_stop_check(min_samples=10):
        logger.critical("HARD STOP triggered by MetricsCollector. Exiting.")
        log_event("hard_stop", metrics.summary())
        sys.exit(1)


import socket

async def check_connection(host="8.8.8.8", port=53, timeout=3) -> bool:
    """Check if there is an active internet connection."""
    try:
        loop = asyncio.get_running_loop()
        # socket.create_connection is blocking, so run in executor
        await loop.run_in_executor(None, socket.create_connection, (host, port), timeout)
        return True
    except OSError:
        return False


async def main() -> None:
    logger.info("═══════════════════════════════════════════")
    logger.info("  Arbitrage Engine — V5 Production Build   ")
    logger.info("═══════════════════════════════════════════")
    
    from notifier import send_telegram_text
    await send_telegram_text("🚀 <b>Arbitrage Engine Started</b>\nSystem is online and preloading browser sessions...")

    # Write PID for monitoring
    try:
        with open("bot.pid", "w") as f:
            f.write(str(os.getpid()))
        logger.info(f"PID {os.getpid()} written to bot.pid")
    except Exception as e:
        logger.error(f"Failed to write bot.pid: {e}")

    # Start identity manager
    await identity_manager.start()

    # Preload session pools for all target bookmakers (v5 §5)
    from config import EXECUTION_ORDER as bookmakers
    pool_tasks = [identity_manager.preload_pool(f"{bm}_acc1") for bm in bookmakers]
    await asyncio.gather(*pool_tasks, return_exceptions=True)
    logger.info("Session pools preloaded.")

    try:
        while True:
            # ── Check internet connection ─────────────────────────
            if not await check_connection():
                logger.warning("Internet connection LOST. Bot paused, waiting for connection...")
                while not await check_connection():
                    await asyncio.sleep(5)
                logger.warning("Internet connection RESTORED. Restarting bot to refresh browser contexts.")
                await send_telegram_text("⚠️ <b>Connection Restored</b>\nThe bot regained internet access and is automatically restarting to recover.")
                sys.exit(2)  # Exit with 2 so run.sh automatically restarts the engine

            cycle_start = time.time()
            try:
                await run_cycle()
            except SystemExit:
                raise
            except Exception as e:
                logger.error({"event": "unhandled_cycle_error", "error": str(e)})

            elapsed    = time.time() - cycle_start
            sleep_time = max(0, POLL_INTERVAL - elapsed)
            logger.info(f"Cycle done in {elapsed:.1f}s. Next in {sleep_time:.1f}s.")
            await asyncio.sleep(sleep_time)

    finally:
        await identity_manager.close()
        metrics.snapshot()
        logger.info("Engine shut down cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
    except SystemExit as e:
        logger.critical(f"System exit: {e}")
        sys.exit(int(str(e)) if str(e).isdigit() else 1)
