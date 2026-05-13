import time
import json
import os
from logger import get_logger
from state import ExecResult

logger = get_logger("pnl_engine")

class PnLEngine:
    def __init__(self, log_file="trade_journal.json"):
        self.log_file = log_file
        self.journal = []
        self.metrics = {
            "total_arbs_attempted": 0,
            "full_success": 0,
            "partial_leg1": 0,
            "partial_leg2": 0,
            "total_fail": 0,
            "total_pnl": 0.0,
            "slippage_sum": 0.0
        }
        self.load_journal()

    def load_journal(self):
        if os.path.exists(self.log_file):
            try:
                with open(self.log_file, "r") as f:
                    self.journal = json.load(f)
                    self._recalc_metrics()
            except Exception as e:
                logger.error(f"Failed to load journal: {e}")

    def save_journal(self):
        try:
            with open(self.log_file, "w") as f:
                json.dump(self.journal, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save journal: {e}")

    def _recalc_metrics(self):
        self.metrics = {k: 0 for k in self.metrics if isinstance(self.metrics[k], int) or isinstance(self.metrics[k], float)}
        for entry in self.journal:
            self.metrics["total_arbs_attempted"] += 1
            res = entry["result"]
            if res == ExecResult.FULL_SUCCESS:
                self.metrics["full_success"] += 1
            elif res == ExecResult.PARTIAL_LEG1:
                self.metrics["partial_leg1"] += 1
            elif res == ExecResult.PARTIAL_LEG2:
                self.metrics["partial_leg2"] += 1
            else:
                self.metrics["total_fail"] += 1
            
            self.metrics["total_pnl"] += entry.get("realized_profit", 0.0)
            self.metrics["slippage_sum"] += entry.get("slippage", 0.0)

    def record_trade(self, arb, result, latency_ms=0):
        self.metrics["total_arbs_attempted"] += 1
        
        expected_profit = arb.get("profit", 0)
        pnl = 0.0
        
        if result == ExecResult.FULL_SUCCESS:
            pnl = expected_profit
            self.metrics["full_success"] += 1
            
        elif result == ExecResult.PARTIAL_LEG1:
            hedge_loss = arb["legs"][0]["stake"] * 0.02 # Assumed 2% slippage on hedge
            pnl = -hedge_loss
            self.metrics["partial_leg1"] += 1
            
        elif result == ExecResult.PARTIAL_LEG2:
            hedge_loss = arb["legs"][1]["stake"] * 0.02
            pnl = -hedge_loss
            self.metrics["partial_leg2"] += 1
            
        else:
            self.metrics["total_fail"] += 1
            pnl = 0.0 # No exposure on total fail
            
        slippage = pnl - expected_profit
        
        self.metrics["total_pnl"] += pnl
        self.metrics["slippage_sum"] += slippage

        log_entry = {
            "event_id": arb.get("event_id"),
            "match": arb.get("match"),
            "result": result,
            "expected_profit": expected_profit,
            "realized_profit": round(pnl, 2),
            "slippage": round(slippage, 2),
            "latency_ms": latency_ms,
            "timestamp": time.time()
        }
        
        self.journal.append(log_entry)
        self.save_journal()
        
        logger.info({
            "event": "pnl_recorded",
            "expected_profit": expected_profit,
            "realized_profit": round(pnl, 2),
            "slippage": round(slippage, 2)
        })
        return pnl

    def get_summary(self):
        total = max(1, self.metrics["total_arbs_attempted"])
        return {
            "total_arbs": self.metrics["total_arbs_attempted"],
            "executed_pct": round((self.metrics["full_success"] / total) * 100, 2),
            "hedged_pct": round(((self.metrics["partial_leg1"] + self.metrics["partial_leg2"]) / total) * 100, 2),
            "avg_pnl": round(self.metrics["total_pnl"] / total, 2)
        }
