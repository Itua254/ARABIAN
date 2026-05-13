import json
import os
from logger import get_logger

logger = get_logger("bm_profiler")

class BookmakerProfile:
    def __init__(self, name: str):
        self.name = name
        self.success_rate = 1.0
        self.avg_latency = 0.0
        self.rejection_rate = 0.0
        self.health_score = 1.0

    def compute_health(self) -> float:
        # Scale latency so high latency decreases health gracefully
        latency_factor = 1.0 / (1.0 + (self.avg_latency / 1000.0))
        self.health_score = self.success_rate * max(0, 1.0 - self.rejection_rate) * latency_factor
        return self.health_score

    def to_dict(self):
        return {
            "name": self.name,
            "success_rate": self.success_rate,
            "avg_latency": self.avg_latency,
            "rejection_rate": self.rejection_rate,
            "health_score": self.health_score
        }

    @classmethod
    def from_dict(cls, data):
        bp = cls(data["name"])
        bp.success_rate = data.get("success_rate", 1.0)
        bp.avg_latency = data.get("avg_latency", 0.0)
        bp.rejection_rate = data.get("rejection_rate", 0.0)
        bp.health_score = data.get("health_score", 1.0)
        return bp

class BookmakerProfiler:
    def __init__(self, filepath="bookmaker_profiles.json"):
        self.filepath = filepath
        self.profiles = {}
        self.load_profiles()

    def load_profiles(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        self.profiles[k] = BookmakerProfile.from_dict(v)
            except Exception as e:
                logger.error(f"Failed to load bookmaker profiles: {e}")

    def save_profiles(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump({k: v.to_dict() for k, v in self.profiles.items()}, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save bookmaker profiles: {e}")

    def get_profile(self, name: str) -> BookmakerProfile:
        name = name.lower()
        if name not in self.profiles:
            self.profiles[name] = BookmakerProfile(name)
        return self.profiles[name]

    def update_profile(self, name: str, result: str, latency: float):
        profile = self.get_profile(name)

        if result == "success":
            profile.success_rate = (profile.success_rate * 0.9) + 0.1
            # Decay rejection rate
            profile.rejection_rate *= 0.9
        else:
            profile.rejection_rate += 0.1
            profile.success_rate *= 0.9

        # EMA for latency
        if profile.avg_latency == 0.0:
            profile.avg_latency = latency
        else:
            profile.avg_latency = (profile.avg_latency * 0.8) + (latency * 0.2)

        profile.compute_health()
        
        # Soft Ban Detection
        if profile.success_rate < 0.3:
            logger.warning(f"Soft ban triggered for {name}. Success rate too low ({profile.success_rate:.2f}).")
            # Set health score very low to trigger skips
            profile.health_score = 0.1

        self.save_profiles()
