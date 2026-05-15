"""
Base Scraper — Abstract Base Class for V6 Live Corners Arbitrage.
"""
from abc import ABC, abstractmethod
from typing import List, Dict

class BaseBookmakerScraper(ABC):
    """
    Contract for Live Corners scrapers.
    Each scraper must return events formatted as:
    {
        "event_id": str,
        "home": str,
        "away": str,
        "minute": int,
        "is_live": bool,
        "market_type": "corners_ou",
        "line": float,           # e.g. 10.5
        "selection": str,        # "over" or "under"
        "odds": float,
        "bookmaker": str,
        "timestamp": float
    }
    """
    
    @abstractmethod
    async def scrape_live_corners(self, fetch_live: bool = True, fetch_prematch: bool = False) -> List[Dict]:
        """
        Scrapes live matches and extracts Corners Over/Under markets.
        Must execute < 15s to maintain freshness.
        """
        pass
