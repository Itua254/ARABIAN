"""
ExecutionEngine — v5 §13 Adapter Registry + Captcha Handling + Graceful Degradation.
"""
import asyncio
import random
import time
from collections import deque
from typing import Dict, Any, List

from logger import get_logger, log_event
from state import TradeState, ExecResult
from identity_manager import IdentityManager
from bookmaker_profiler import BookmakerProfiler
from metrics import MetricsCollector
from config import DRY_RUN, EXECUTION_MODE, GRACEFUL_DEGRADATION_THRESHOLD, MIN_EDGE

from adapters.betway_adapter   import BetWayAdapter
from adapters.pinnacle_adapter import PinnacleAdapter
from adapters.onexbet_adapter  import OnexBetAdapter

ADAPTER_REGISTRY = {
    "betway":   BetWayAdapter,
    "pinnacle": PinnacleAdapter,
    "onexbet":  OnexBetAdapter,
    "1xbet":    OnexBetAdapter,
}

logger  = get_logger("execution_engine")
metrics = MetricsCollector.instance()


class ExecutionEngine:

    def __init__(self, identity_manager: IdentityManager, profiler: BookmakerProfiler, treasury):
        self.identity_manager = identity_manager
        self.profiler         = profiler
        self.treasury         = treasury
        self._failure_windows: Dict[str, deque] = {}

    async def execute_arb(self, arb: Dict[str, Any], risk_ledger) -> str:
        event_id = arb["event_id"]
        logger.info(f"[{event_id}] Initiating execution: {arb['match']} (Profit: ${arb['profit']})")
        log_event("execution_start", {"event_id": event_id, "match": arb["match"]})

        legs = arb.get("legs", [])
        if len(legs) < 2:
            logger.error(f"[{event_id}] Invalid arb — fewer than 2 legs.")
            return ExecResult.TOTAL_FAIL

        ordered_legs = self._sort_legs(legs)
        edge = arb.get("margin_pct", 0) / 100.0

        # Global Symmetric Stake Scaling (V7 Math Fix)
        min_health = min(self.profiler.get_profile(l["bookmaker"]).health_score for l in ordered_legs)
        global_multiplier = min_health * random.uniform(0.92, 1.08)
        if edge > 0.08:
            global_multiplier *= 1.2

        for leg in ordered_legs:
            leg["stake"] = round(leg["stake"] * global_multiplier, 2)

        # ── Treasury Safety Lock (Move 3) ──
        # Validate that both bookies have enough balance before placing Leg 1
        b1, s1 = ordered_legs[0]["bookmaker"].lower(), ordered_legs[0]["stake"]
        b2, s2 = ordered_legs[1]["bookmaker"].lower(), ordered_legs[1]["stake"]
        
        can_trade = await self.treasury.can_afford(b1, s1, b2, s2)
        if not can_trade:
            logger.critical(f"[{event_id}] Treasury check failed! Rebalancing required. Aborting trade.")
            risk_ledger.active[event_id]["state"] = TradeState.FAILED
            log_event("treasury_abort", {"event_id": event_id})
            return ExecResult.TOTAL_FAIL

        # Leg 1
        risk_ledger.active[event_id]["state"] = TradeState.PLACING_LEG_1
        leg1_bookie = ordered_legs[0]["bookmaker"].lower()
        t0 = time.time()
        leg1_ok = await self._place_leg(event_id, ordered_legs[0], ordered_legs[1]["odds"], is_second_leg=False)
        leg1_ms = (time.time() - t0) * 1000.0

        self.profiler.update_profile(leg1_bookie, "success" if leg1_ok else "fail", leg1_ms)
        self._track_failure(leg1_bookie, leg1_ok)
        metrics.record_bookmaker_outcome(leg1_bookie, leg1_ok)
        metrics.record_latency("execution_ms", leg1_ms)

        if not leg1_ok:
            logger.error(f"[{event_id}] Leg 1 failed. Aborting.")
            risk_ledger.active[event_id]["state"] = TradeState.FAILED
            log_event("leg1_failed", {"event_id": event_id, "bookmaker": leg1_bookie})
            return ExecResult.TOTAL_FAIL

        # Leg 2
        risk_ledger.active[event_id]["state"] = TradeState.HEDGING_LEG_2
        leg2_bookie = ordered_legs[1]["bookmaker"].lower()
        t1 = time.time()
        leg2_ok = await self._place_leg(event_id, ordered_legs[1], ordered_legs[0]["odds"], is_second_leg=True)
        leg2_ms = (time.time() - t1) * 1000.0

        self.profiler.update_profile(leg2_bookie, "success" if leg2_ok else "fail", leg2_ms)
        self._track_failure(leg2_bookie, leg2_ok)
        metrics.record_bookmaker_outcome(leg2_bookie, leg2_ok)

        if not leg2_ok:
            logger.error(f"[{event_id}] Leg 2 FAILED — unhedged exposure on Leg 1!")
            risk_ledger.active[event_id]["state"] = TradeState.PARTIAL_FILL
            log_event("leg2_failed", {"event_id": event_id, "bookmaker": leg2_bookie})
            return ExecResult.PARTIAL_LEG1

        logger.info(f"[{event_id}] Arbitrage executed across all legs.")
        risk_ledger.active[event_id]["state"] = TradeState.SUCCESS
        log_event("execution_success", {"event_id": event_id})
        return ExecResult.FULL_SUCCESS

    async def _place_leg(self, event_id: str, leg: Dict[str, Any], other_leg_odds: float, is_second_leg: bool = False) -> bool:
        bookie  = leg["bookmaker"].lower()
        profile = self.profiler.get_profile(bookie)

        if profile.health_score < 0.5:
            logger.warning(f"[{event_id}] Skipping {bookie} — health {profile.health_score:.2f}")
            return False

        if self._is_degraded(bookie):
            logger.warning(f"[{event_id}] {bookie} in DEGRADED mode — skipping.")
            log_event("degraded_skip", {"event_id": event_id, "bookmaker": bookie})
            return False

        adapter_cls = ADAPTER_REGISTRY.get(bookie)
        if adapter_cls is None:
            logger.error(f"[{event_id}] No adapter for '{bookie}'")
            return False

        adapter = adapter_cls()

        stake = leg["stake"]
        if EXECUTION_MODE == "limited":
            stake = min(stake, 5.0)
            leg["stake"] = stake

        accounts    = ["acc1", "acc2", "acc3"]
        identity_id = f"{bookie}_{random.choice(accounts)}"

        if self.identity_manager.is_burned(identity_id):
            identity_id = f"{bookie}_fallback_{random.randint(4, 9)}"

        ctx = await self.identity_manager.get_context(identity_id)
        if ctx is None:
            logger.error(f"[{event_id}] Could not acquire context for {identity_id}")
            return False

        page    = await ctx.new_page()
        success = False

        try:
            if not await adapter.navigate(page, leg):
                return False

            if await adapter.detect_captcha(page):
                logger.critical(f"[{event_id}] CAPTCHA at {bookie}!")
                log_event("captcha_detected", {"event_id": event_id, "bookmaker": bookie})
                metrics.inc("captchas_hit")
                self.identity_manager.burn_account(identity_id)
                metrics.inc("accounts_burned")
                return False

            revalidated, live_odds = await adapter.revalidate(page, leg["odds"])

            # V7 Dynamic Slippage Tolerance
            if live_odds > 0 and live_odds != leg["odds"]:
                # Check if we still have an edge
                new_edge = 1.0 - ((1.0 / live_odds) + (1.0 / other_leg_odds))
                if new_edge < MIN_EDGE:
                    logger.critical(f"[{event_id}] Odds drift: {leg['odds']} → {live_odds}. New edge {new_edge:.2%} < {MIN_EDGE:.2%}. Aborting.")
                    log_event("odds_drift_abort", {"event_id": event_id, "expected": leg["odds"], "live": live_odds, "new_edge": new_edge})
                    return False
                else:
                    logger.warning(f"[{event_id}] Odds drift: {leg['odds']} → {live_odds}. New edge {new_edge:.2%} >= {MIN_EDGE:.2%}. Proceeding with slippage.")
                    log_event("odds_drift_proceed", {"event_id": event_id, "expected": leg["odds"], "live": live_odds, "new_edge": new_edge})

            if not revalidated:
                logger.error(f"[{event_id}] Revalidation failed for {bookie}.")
                return False

            if not await adapter.fill_stake(page, stake):
                return False

            success = await adapter.place_bet(page, event_id, DRY_RUN)

        except Exception as e:
            logger.error(f"[{event_id}] Exception in leg at {bookie}: {e}")
            try:
                if await adapter.detect_captcha(page):
                    self.identity_manager.burn_account(identity_id)
                    metrics.inc("accounts_burned")
            except Exception:
                pass
        finally:
            await page.close()
            await self.identity_manager.release_context(identity_id, ctx)

        return success

    def _sort_legs(self, legs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # V6: Fastest bookmaker -> slower bookmaker (latency ascending)
        # Treat 0.0 (uninitialized) as 1000ms to rank it lower than known fast ones
        return sorted(
            legs,
            key=lambda leg: self.profiler.get_profile(leg["bookmaker"]).avg_latency or 1000.0
        )

    def _track_failure(self, bookmaker: str, success: bool, window: int = 20) -> None:
        if bookmaker not in self._failure_windows:
            self._failure_windows[bookmaker] = deque(maxlen=window)
        self._failure_windows[bookmaker].append(success)

    def _is_degraded(self, bookmaker: str) -> bool:
        w = self._failure_windows.get(bookmaker)
        if not w or len(w) < 5:
            return False
        failure_rate = 1.0 - (sum(w) / len(w))
        if failure_rate > GRACEFUL_DEGRADATION_THRESHOLD:
            log_event("bookmaker_degraded", {"bookmaker": bookmaker, "failure_rate": round(failure_rate, 3)})
            return True
        return False
