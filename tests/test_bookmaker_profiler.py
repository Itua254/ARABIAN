"""
Tests for bookmaker_profiler.py — health scoring, EMA latency, soft-ban.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock
from bookmaker_profiler import BookmakerProfile, BookmakerProfiler


class TestBookmakerProfile:
    def test_default_health_is_one(self):
        p = BookmakerProfile("betway")
        assert p.health_score == 1.0

    def test_compute_health_pure_success(self):
        p = BookmakerProfile("betway")
        p.success_rate   = 1.0
        p.rejection_rate = 0.0
        p.avg_latency    = 0.0
        score = p.compute_health()
        assert score == 1.0

    def test_high_latency_decreases_health(self):
        p = BookmakerProfile("betway")
        p.success_rate   = 1.0
        p.rejection_rate = 0.0
        p.avg_latency    = 5000.0   # 5 seconds
        score = p.compute_health()
        assert score < 0.2          # severely penalised

    def test_rejection_rate_decreases_health(self):
        p = BookmakerProfile("betway")
        p.success_rate   = 1.0
        p.rejection_rate = 0.8
        p.avg_latency    = 0.0
        score = p.compute_health()
        assert score < 0.25

    def test_round_trip_serialisation(self):
        p = BookmakerProfile("pinnacle")
        p.success_rate   = 0.75
        p.rejection_rate = 0.1
        p.avg_latency    = 320.0
        p.compute_health()
        d  = p.to_dict()
        p2 = BookmakerProfile.from_dict(d)
        assert abs(p2.health_score - p.health_score) < 1e-6
        assert p2.name == "pinnacle"


class TestBookmakerProfiler:
    def _profiler(self):
        """Returns a profiler that never touches the filesystem."""
        with patch.object(BookmakerProfiler, "load_profiles"), \
             patch.object(BookmakerProfiler, "save_profiles"):
            profiler = BookmakerProfiler.__new__(BookmakerProfiler)
            profiler.filepath = ":memory:"
            profiler.profiles = {}
            return profiler

    def test_get_profile_creates_default(self):
        profiler = self._profiler()
        p = profiler.get_profile("betway")
        assert p.name == "betway"
        assert p.health_score == 1.0

    def test_update_success_improves_success_rate(self):
        profiler = self._profiler()
        p = profiler.get_profile("betway")
        initial = p.success_rate
        profiler.update_profile("betway", "success", 200.0)
        assert profiler.get_profile("betway").success_rate >= initial

    def test_update_fail_increases_rejection(self):
        profiler = self._profiler()
        profiler.update_profile("betway", "fail", 500.0)
        p = profiler.get_profile("betway")
        assert p.rejection_rate > 0.0

    def test_ema_latency_updates(self):
        profiler = self._profiler()
        profiler.update_profile("betway", "success", 400.0)
        p = profiler.get_profile("betway")
        assert p.avg_latency > 0.0

    def test_soft_ban_triggers_on_low_success(self):
        profiler = self._profiler()
        # Drive success rate below 0.3
        for _ in range(15):
            profiler.update_profile("betway", "fail", 100.0)
        p = profiler.get_profile("betway")
        assert p.health_score <= 0.1

    def test_case_insensitive_lookup(self):
        profiler = self._profiler()
        profiler.update_profile("Betway", "success", 100.0)
        p = profiler.get_profile("BETWAY")
        assert p is not None
