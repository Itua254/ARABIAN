"""
Tests for arb_detector.py — V6 Live Corners Strict Filters.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import time
from unittest.mock import patch
from arb_detector import calc_stakes, process_events

class TestCalcStakes:
    def test_two_outcome_sums_to_bankroll(self):
        stakes = calc_stakes([2.0, 2.0], 100)
        assert abs(sum(stakes) - 100) < 0.02

def _make_flat_event(odds=6.0, selection="over", line=10.5, minute=45, is_live=True, market="corners_ou", age_sec=1):
    return {
        "event_id": "test_match",
        "home": "Team A",
        "away": "Team B",
        "minute": minute,
        "is_live": is_live,
        "market_type": market,
        "line": line,
        "selection": selection,
        "odds": odds,
        "bookmaker": "1xbet" if selection == "over" else "betika",
        "timestamp": time.time() - age_sec
    }

class TestProcessEventsV6:
    def test_detects_valid_corners_arb(self):
        events = [
            _make_flat_event(odds=6.0, selection="over", line=10.5),
            _make_flat_event(odds=6.0, selection="under", line=10.5)
        ]
        with patch("arb_detector.MIN_EDGE", 0.05), patch("arb_detector.BANKROLL", 1000):
            arbs = process_events(events)
        assert len(arbs) == 1
        assert arbs[0]["margin_pct"] > 0
        
    def test_rejects_wrong_market(self):
        events = [
            _make_flat_event(odds=6.0, selection="over", market="fake_market"),
            _make_flat_event(odds=6.0, selection="under", market="fake_market")
        ]
        arbs = process_events(events)
        assert len(arbs) == 0
        events = [
            _make_flat_event(odds=6.0, selection="over", minute=86),
            _make_flat_event(odds=6.0, selection="under", minute=86)
        ]
        arbs = process_events(events)
        assert len(arbs) == 0
        

    def test_rejects_mismatched_lines(self):
        events = [
            _make_flat_event(odds=6.0, selection="over", line=10.5),
            _make_flat_event(odds=6.0, selection="under", line=11.5)
        ]
        arbs = process_events(events)
        assert len(arbs) == 0
        
