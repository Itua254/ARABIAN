"""
MetricsCollector — v5 §8 Observability Layer.

Thread-safe singleton that aggregates execution metrics across cycles
and snapshots them to metrics_snapshot.json after each cycle.
"""
import json
import time
import threading
from typing import Dict, Any
from logger import get_logger, log_event

logger = get_logger("metrics")

_SNAPSHOT_PATH = "metrics_snapshot.json"


class MetricsCollector:
    """
    Singleton metrics aggregator. Import and call MetricsCollector.instance().
    All public methods are thread-safe.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    @classmethod
    def instance(cls) -> "MetricsCollector":
        return cls()

    def _init(self):
        self._mu = threading.Lock()
        self._started_at = time.time()
        self._counters: Dict[str, int] = {
            "cycles":           0,
            "arbs_detected":    0,
            "arbs_rejected":    0,   # by edge classifier
            "arbs_attempted":   0,
            "full_success":     0,
            "partial_leg1":     0,
            "partial_leg2":     0,
            "total_fail":       0,
            "hedges_triggered": 0,
            "hedges_success":   0,
            "hedges_failed":    0,
            "captchas_hit":     0,
            "accounts_burned":  0,
        }
        self._latencies: Dict[str, list] = {
            "execution_ms": [],
            "fetch_ms":     [],
            "hedge_ms":     [],
        }
        self._bookmaker_stats: Dict[str, Dict[str, int]] = {}
        self._total_pnl = 0.0

    # ── Increment helpers ────────────────────────────────────

    def inc(self, key: str, n: int = 1) -> None:
        with self._mu:
            self._counters[key] = self._counters.get(key, 0) + n

    def record_latency(self, category: str, ms: float) -> None:
        with self._mu:
            if category not in self._latencies:
                self._latencies[category] = []
            self._latencies[category].append(ms)
            # Keep last 500 samples to avoid unbounded memory growth
            if len(self._latencies[category]) > 500:
                self._latencies[category] = self._latencies[category][-500:]

    def record_pnl(self, amount: float) -> None:
        with self._mu:
            self._total_pnl += amount

    def record_bookmaker_outcome(self, bookmaker: str, success: bool) -> None:
        with self._mu:
            bm = bookmaker.lower()
            if bm not in self._bookmaker_stats:
                self._bookmaker_stats[bm] = {"success": 0, "fail": 0}
            if success:
                self._bookmaker_stats[bm]["success"] += 1
            else:
                self._bookmaker_stats[bm]["fail"] += 1

    # ── Derived stats ────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        with self._mu:
            total_attempted = max(1, self._counters["arbs_attempted"])
            uptime_sec = round(time.time() - self._started_at)

            def avg(lst):
                return round(sum(lst) / len(lst), 2) if lst else 0.0

            bm_rejection_rates = {}
            for bm, stats in self._bookmaker_stats.items():
                total = stats["success"] + stats["fail"]
                if total > 0:
                    bm_rejection_rates[bm] = round(stats["fail"] / total, 3)

            return {
                "uptime_sec":       uptime_sec,
                "cycles":           self._counters["cycles"],
                "arbs_detected":    self._counters["arbs_detected"],
                "arbs_rejected":    self._counters["arbs_rejected"],
                "arbs_attempted":   self._counters["arbs_attempted"],
                "total_pnl":        round(self._total_pnl, 2),
                "avg_pnl_per_arb":  round(self._total_pnl / total_attempted, 4),
                "executed_pct":     round(self._counters["full_success"] / total_attempted * 100, 2),
                "partial_pct":      round((self._counters["partial_leg1"] + self._counters["partial_leg2"]) / total_attempted * 100, 2),
                "fail_pct":         round(self._counters["total_fail"] / total_attempted * 100, 2),
                "hedge_trigger_pct":round(self._counters["hedges_triggered"] / total_attempted * 100, 2),
                "hedge_success_pct":round(self._counters["hedges_success"] / max(1, self._counters["hedges_triggered"]) * 100, 2),
                "captchas_hit":     self._counters["captchas_hit"],
                "accounts_burned":  self._counters["accounts_burned"],
                "avg_exec_ms":      avg(self._latencies["execution_ms"]),
                "avg_fetch_ms":     avg(self._latencies["fetch_ms"]),
                "avg_hedge_ms":     avg(self._latencies["hedge_ms"]),
                "bookmaker_rejection_rates": bm_rejection_rates,
            }

    # ── Hard-stop gate (replaces inline check in main.py) ───

    def hard_stop_check(self, min_samples: int = 10) -> bool:
        """
        Returns True if system should halt due to poor performance.
        Replaces the brittle inline check in main.py.
        """
        s = self.summary()
        if s["arbs_attempted"] < min_samples:
            return False
        if s["executed_pct"] < 50.0:
            logger.critical(f"HARD STOP: executed_pct={s['executed_pct']}% (threshold 50%)")
            return True
        if s["partial_pct"] > 35.0:
            logger.critical(f"HARD STOP: partial_pct={s['partial_pct']}% (threshold 35%)")
            return True
        if s["avg_pnl_per_arb"] < -1.0:
            logger.critical(f"HARD STOP: avg_pnl_per_arb={s['avg_pnl_per_arb']} < -1.0")
            return True
        return False

    # ── Snapshot ─────────────────────────────────────────────

    def snapshot(self) -> None:
        """Writes current metrics to metrics_snapshot.json."""
        s = self.summary()
        s["snapshot_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            with open(_SNAPSHOT_PATH, "w") as f:
                json.dump(s, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write metrics snapshot: {e}")

        log_event("metrics_snapshot", s)
