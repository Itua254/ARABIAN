"""
Tests for pnl_engine.py — trade recording, slippage, summary metrics.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import json
import tempfile
from pnl_engine import PnLEngine
from state import ExecResult


def _make_arb(profit=10.0, stake_leg1=50.0, stake_leg2=50.0):
    return {
        "event_id": "test_pnl_001",
        "match":    "A vs B",
        "profit":   profit,
        "margin_pct": 2.5,
        "legs": [
            {"outcome": "Home", "bookmaker": "betway",  "odds": 2.1, "stake": stake_leg1},
            {"outcome": "Away", "bookmaker": "pinnacle", "odds": 2.1, "stake": stake_leg2},
        ]
    }


class TestPnLEngine:

    def _engine(self):
        """Returns a PnLEngine writing to a temp file."""
        tmp = tempfile.mktemp(suffix=".json")
        return PnLEngine(log_file=tmp)

    def test_full_success_records_profit(self):
        engine = self._engine()
        arb    = _make_arb(profit=15.0)
        pnl    = engine.record_trade(arb, ExecResult.FULL_SUCCESS, latency_ms=120)
        assert pnl == 15.0

    def test_partial_leg1_records_negative(self):
        engine = self._engine()
        arb    = _make_arb(profit=10.0, stake_leg1=50.0)
        pnl    = engine.record_trade(arb, ExecResult.PARTIAL_LEG1, latency_ms=200)
        assert pnl < 0          # hedge loss is negative

    def test_partial_leg2_records_negative(self):
        engine = self._engine()
        arb    = _make_arb(profit=10.0, stake_leg2=60.0)
        pnl    = engine.record_trade(arb, ExecResult.PARTIAL_LEG2, latency_ms=200)
        assert pnl < 0

    def test_total_fail_records_zero(self):
        engine = self._engine()
        arb    = _make_arb(profit=10.0)
        pnl    = engine.record_trade(arb, ExecResult.TOTAL_FAIL, latency_ms=50)
        assert pnl == 0.0

    def test_summary_after_success(self):
        engine = self._engine()
        arb    = _make_arb(profit=5.0)
        engine.record_trade(arb, ExecResult.FULL_SUCCESS, 100)
        s = engine.get_summary()
        assert s["total_arbs"] == 1
        assert s["executed_pct"] == 100.0
        assert s["avg_pnl"]  == 5.0

    def test_journal_persisted_to_disk(self):
        import tempfile
        tmp = tempfile.mktemp(suffix=".json")
        engine = PnLEngine(log_file=tmp)
        arb    = _make_arb(profit=7.0)
        engine.record_trade(arb, ExecResult.FULL_SUCCESS, 80)
        with open(tmp) as f:
            journal = json.load(f)
        assert len(journal) == 1
        assert journal[0]["realized_profit"] == 7.0

    def test_multiple_trades_accumulate(self):
        engine = self._engine()
        arb    = _make_arb(profit=5.0)
        engine.record_trade(arb, ExecResult.FULL_SUCCESS, 100)
        engine.record_trade(arb, ExecResult.FULL_SUCCESS, 100)
        engine.record_trade(arb, ExecResult.TOTAL_FAIL,   50)
        s = engine.get_summary()
        assert s["total_arbs"]   == 3
        assert s["avg_pnl"]      == pytest.approx(10.0 / 3, abs=0.01)

    def test_executed_pct_calculation(self):
        engine = self._engine()
        arb    = _make_arb(profit=5.0)
        engine.record_trade(arb, ExecResult.FULL_SUCCESS, 100)
        engine.record_trade(arb, ExecResult.TOTAL_FAIL,   50)
        s = engine.get_summary()
        assert s["executed_pct"] == 50.0
