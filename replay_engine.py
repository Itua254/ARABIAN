"""
Replay Engine — v5 §10.

Reads trade_journal.json and reruns each trade through the current
validation pipeline to:
  - Identify trades that would now be rejected by updated rules
  - Flag entries with poor hedge outcomes
  - Calculate what the PnL *would have been* under current edge thresholds
  - Write replay_report.json with per-trade analysis
"""
import json
import time
import os
import sys
from typing import Dict, Any, List

# Allow running as a standalone script
sys.path.insert(0, os.path.dirname(__file__))

from logger import get_logger, log_event
from edge_classifier import classify, EdgeClass
from bookmaker_profiler import BookmakerProfiler
from state import ExecResult

logger = get_logger("replay_engine")

JOURNAL_PATH = "trade_journal.json"
REPORT_PATH  = "replay_report.json"


def load_journal(path: str = JOURNAL_PATH) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        logger.error(f"Journal not found at {path}")
        return []
    with open(path, "r") as f:
        return json.load(f)


def replay_trade(entry: Dict[str, Any], profiler: BookmakerProfiler) -> Dict[str, Any]:
    """
    Re-classifies a single journal entry under current rules.
    """
    # Reconstruct a minimal arb dict from the journal entry
    arb = {
        "event_id":       entry.get("event_id", "?"),
        "match":          entry.get("match", "?"),
        "margin_pct":     entry.get("margin_pct", 0),
        "age_sec":        entry.get("age_sec", 0),
        "bookmaker_count": entry.get("bookmaker_count", 2),
        "legs":           entry.get("legs", []),
    }

    edge = classify(arb, profiler=profiler)

    original_result  = entry.get("result", "?")
    original_profit  = entry.get("realized_profit", 0.0)
    expected_profit  = entry.get("expected_profit", 0.0)
    slippage         = entry.get("slippage", 0.0)

    would_be_skipped = edge in (EdgeClass.REJECT, EdgeClass.WEAK)

    verdict = "PASS"
    if would_be_skipped:
        verdict = f"WOULD_SKIP ({edge.value})"
    elif original_result == ExecResult.TOTAL_FAIL:
        verdict = "FAILED_EXECUTION"
    elif slippage < -2.0:
        verdict = "HIGH_SLIPPAGE"

    return {
        "event_id":        arb["event_id"],
        "match":           arb["match"],
        "original_result": original_result,
        "original_profit": original_profit,
        "expected_profit": expected_profit,
        "slippage":        slippage,
        "edge_class":      edge.value,
        "verdict":         verdict,
        "timestamp":       entry.get("timestamp"),
    }


def run_replay(journal_path: str = JOURNAL_PATH, report_path: str = REPORT_PATH) -> Dict[str, Any]:
    logger.info(f"=== Replay Engine starting — reading {journal_path} ===")
    journal = load_journal(journal_path)

    if not journal:
        logger.warning("No trades found in journal.")
        return {}

    profiler = BookmakerProfiler()
    results  = [replay_trade(entry, profiler) for entry in journal]

    # Aggregate stats
    total           = len(results)
    would_skip      = sum(1 for r in results if "WOULD_SKIP" in r["verdict"])
    high_slippage   = sum(1 for r in results if r["verdict"] == "HIGH_SLIPPAGE")
    failed_exec     = sum(1 for r in results if r["verdict"] == "FAILED_EXECUTION")
    total_orig_pnl  = sum(r["original_profit"] for r in results)
    saved_pnl       = sum(
        -r["original_profit"] for r in results
        if "WOULD_SKIP" in r["verdict"] and r["original_profit"] < 0
    )

    report = {
        "generated_at":         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "journal_path":         journal_path,
        "total_trades_replayed": total,
        "would_be_skipped":     would_skip,
        "high_slippage_trades": high_slippage,
        "failed_exec_trades":   failed_exec,
        "original_total_pnl":   round(total_orig_pnl, 2),
        "pnl_saved_by_skipping": round(saved_pnl, 2),
        "trades":               results,
    }

    try:
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        logger.info(f"Replay report written to {report_path}")
    except Exception as e:
        logger.error(f"Failed to write replay report: {e}")

    log_event("replay_complete", {
        "total": total,
        "would_skip": would_skip,
        "original_pnl": round(total_orig_pnl, 2),
        "pnl_saved": round(saved_pnl, 2),
    })

    logger.info(
        f"Replay complete: {total} trades | {would_skip} would be skipped | "
        f"Original PnL: {round(total_orig_pnl, 2)} | Recoverable PnL: {round(saved_pnl, 2)}"
    )
    return report


if __name__ == "__main__":
    run_replay()
