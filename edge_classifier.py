"""
Edge Classifier — v6 Strict Mode.
Computes a priority score for the Execution Queue: priority = edge * odds * stability_score
"""
import time
from typing import Dict, Any

def classify(arb: Dict[str, Any], profiler=None) -> float:
    """
    Returns a priority score (float). Higher is better.
    """
    edge = arb.get("margin_pct", 0) / 100.0
    
    # V7 Market Volatility Weights
    market_weights = {
        "corners_ou": 1.2,
        "bookings_ou": 1.1,
        "goals_ou": 1.0,
        "fouls_ou": 0.9,
        "goalkicks_ou": 0.8
    }
    market_type = arb.get("market_type", "goals_ou")
    market_volatility = market_weights.get(market_type, 1.0)
    
    # Stability factors
    # 1. Odds age (0 to 1.0)
    age_sec = time.time() - arb.get("detected_at", time.time())
    
    # If it's too new (<300ms), it might not be stable
    if age_sec < 0.3:
        age_stability = 0.5
    else:
        # Decays as it approaches 1.0s kill switch
        age_stability = max(0.1, 1.0 - age_sec)
        
    # 2. Bookmaker health
    bm_health_avg = 1.0
    if profiler:
        healths = [profiler.get_profile(leg["bookmaker"]).health_score for leg in arb.get("legs", [])]
        if healths:
            bm_health_avg = sum(healths) / len(healths)
            
    stability_score = age_stability * bm_health_avg
    
    # V7 Priority Formula
    priority = edge * market_volatility * stability_score
    return round(priority, 4)
