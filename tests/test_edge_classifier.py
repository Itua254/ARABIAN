"""
Tests for edge_classifier.py — V6 Priority Score Logic.
"""
import sys, os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock
from edge_classifier import classify


def _arb(margin_pct=5.0, age_sec=0.1, legs=None):
    if legs is None:
        legs = [
            {"outcome": "Over 10.5", "bookmaker": "1xbet",  "odds": 6.0, "stake": 500},
            {"outcome": "Under 10.5", "bookmaker": "melbet", "odds": 6.5, "stake": 500},
        ]
    return {
        "event_id":       "test_001",
        "margin_pct":     margin_pct,
        "detected_at":    time.time() - age_sec,
        "legs":           legs,
    }


class TestEdgeClassifier:
    
    def test_priority_score_calculation(self):
        # margin = 5.0% -> edge = 0.05
        # market = corners_ou -> market_volatility = 1.2
        # age = 0.1s (< 0.3s) -> age_stability = 0.5
        # profiler = None -> bm_health_avg = 1.0
        # Expected priority: 0.05 * 1.2 * 0.5 * 1.0 = 0.03
        
        arb = _arb(margin_pct=5.0, age_sec=0.1)
        arb["market_type"] = "corners_ou"
        score = classify(arb, profiler=None)
        assert round(score, 3) == 0.030
        
    def test_age_penalty(self):
        # age = 0.5s -> age_stability = 1.0 - 0.5 = 0.5
        arb = _arb(margin_pct=5.0, age_sec=0.5)
        arb["market_type"] = "corners_ou"
        score = classify(arb, profiler=None)
        assert round(score, 3) == 0.030
        
    def test_bookmaker_health_penalty(self):
        mock_profile = MagicMock()
        mock_profile.health_score = 0.5

        mock_profiler = MagicMock()
        mock_profiler.get_profile.return_value = mock_profile

        arb = _arb(margin_pct=5.0, age_sec=0.5) # stability = 0.5
        arb["market_type"] = "corners_ou"
        score = classify(arb, profiler=mock_profiler)
        
        # 0.05 * 1.2 * (0.5 * 0.5) = 0.015
        assert round(score, 3) == 0.015
