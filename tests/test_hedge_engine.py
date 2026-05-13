"""
Tests for hedge_engine.py — validation, retry logic, liability cap, journal.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import json
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from hedge_engine import HedgeEngine


def _make_arb(event_id="hedge_001", stake=100.0, odds=2.0):
    return {
        "event_id": event_id,
        "match":    "A vs B",
        "profit":   5.0,
        "legs": [
            {"outcome": "Home", "bookmaker": "betway",  "odds": odds, "stake": stake},
            {"outcome": "Away", "bookmaker": "pinnacle", "odds": 3.0, "stake": 33.0},
        ]
    }


def _make_engine():
    im = MagicMock()
    engine = HedgeEngine.__new__(HedgeEngine)
    engine.identity_manager = im
    
    treasury = MagicMock()
    treasury.can_afford_hedge = AsyncMock(return_value=True)
    engine.treasury = treasury
    
    engine._journal = []
    engine._exchange = MagicMock()
    return engine


class TestHedgeEngineValidation:

    def test_rejects_lay_odds_too_low(self):
        engine = _make_engine()
        pos = {"lay_odds": 1.005, "back_stake": 100.0}
        assert engine.validate_hedge(pos) is False

    def test_rejects_lay_odds_too_high(self):
        engine = _make_engine()
        pos = {"lay_odds": 15.0, "back_stake": 100.0}
        assert engine.validate_hedge(pos) is False

    def test_rejects_liability_above_cap(self):
        engine = _make_engine()
        # (5.0 - 1) * 200 = 800 >> MAX_HEDGE_LOSS=50
        pos = {"lay_odds": 5.0, "back_stake": 200.0}
        with patch("hedge_engine.MAX_HEDGE_LOSS", 50.0):
            assert engine.validate_hedge(pos) is False

    def test_accepts_valid_position(self):
        engine = _make_engine()
        pos = {"lay_odds": 2.5, "back_stake": 10.0}
        with patch("hedge_engine.MAX_HEDGE_LOSS", 50.0):
            assert engine.validate_hedge(pos) is True

    def test_max_liability_calculation(self):
        engine = _make_engine()
        pos = {"lay_odds": 3.0, "back_stake": 50.0}
        assert engine.max_liability(pos) == 100.0   # (3-1)*50


class TestHedgeLegAsync:

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_hedge_succeeds_on_first_attempt(self):
        engine = _make_engine()
        engine._exchange.get_lay_odds = MagicMock(return_value=2.1)
        engine._exchange.place_lay    = AsyncMock(return_value={"status": "MATCHED", "matched_odds": 2.1})
        engine._save_journal          = MagicMock()

        arb = _make_arb(stake=10.0, odds=2.0)
        with patch("hedge_engine.MAX_HEDGE_LOSS", 50.0):
            ok = self._run(engine.hedge_leg(arb, exposed_leg_index=0))
        assert ok is True

    def test_hedge_fails_after_all_retries(self):
        engine = _make_engine()
        engine._exchange.get_lay_odds = MagicMock(return_value=2.1)
        engine._exchange.place_lay    = AsyncMock(return_value={"status": "FAILED", "reason": "no_liquidity"})
        engine._save_journal          = MagicMock()

        arb = _make_arb(stake=10.0, odds=2.0)
        with patch("hedge_engine.MAX_HEDGE_LOSS", 50.0):
            ok = self._run(engine.hedge_leg(arb, exposed_leg_index=0))
        assert ok is False

    def test_hedge_retries_on_partial_match(self):
        engine = _make_engine()
        engine._exchange.get_lay_odds = MagicMock(return_value=2.1)
        call_count = {"n": 0}
        async def place_lay(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"status": "PARTIAL", "matched_odds": 2.1, "matched_size": 5.0}
            return {"status": "MATCHED", "matched_odds": 2.1, "matched_size": 5.0}

        engine._exchange.place_lay = place_lay
        engine._save_journal       = MagicMock()

        arb = _make_arb(stake=10.0, odds=2.0)
        with patch("hedge_engine.MAX_HEDGE_LOSS", 50.0):
            ok = self._run(engine.hedge_leg(arb, exposed_leg_index=0))
        assert ok is True
        assert call_count["n"] == 2     # first partial, then matched

    def test_hedge_aborted_if_validation_fails_mid_retry(self):
        engine = _make_engine()
        # lay odds keeps jumping above cap after first failure
        engine._exchange.get_lay_odds = MagicMock(return_value=15.0)
        engine._exchange.place_lay    = AsyncMock(return_value={"status": "FAILED"})
        engine._save_journal          = MagicMock()

        arb = _make_arb(stake=10.0, odds=2.0)
        with patch("hedge_engine.MAX_HEDGE_LOSS", 50.0):
            ok = self._run(engine.hedge_leg(arb, exposed_leg_index=0))
        assert ok is False
