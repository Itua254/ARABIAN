"""
Odds Fetcher — Coordinator for V6 Live Corners Scrapers.
Replaces API polling with Playwright-based scraper aggregation.

Active scrapers (Phase 4):
  - 1xBet     (BetB2B cluster master — primary data feed)
  - Melbet    (BetB2B clone — used for bet placement spread)
  - Mozzartbet (BetConstruct backend — primary arb target)
"""
import asyncio
from typing import List, Dict

from scrapers.onexbet_scraper   import OnexBetScraper
from scrapers.melbet_scraper    import MelbetScraper
from scrapers.mozzartbet_scraper import MozzartbetScraper
from scrapers.betika_scraper    import BetikaScraper
from logger import get_logger

logger = get_logger("odds_fetcher")


async def fetch_all_odds(identity_manager, fetch_live: bool = True, fetch_prematch: bool = False) -> List[Dict]:
    """
    Runs all enabled scrapers concurrently and aggregates live events.
    Each scraper is isolated — a failure in one does not block the others.
    """
    from config import EXECUTION_ORDER
    
    all_scrapers = {
        "1xbet": OnexBetScraper(identity_manager),
        "melbet": MelbetScraper(identity_manager),
        "betika": BetikaScraper(identity_manager),
        "mozzartbet": MozzartbetScraper(identity_manager),
    }
    
    scrapers = [all_scrapers[bm] for bm in EXECUTION_ORDER if bm in all_scrapers]

    tasks   = [s.scrape_live_corners(fetch_live=fetch_live, fetch_prematch=fetch_prematch) for s in scrapers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_events: List[Dict] = []
    for scraper, result in zip(scrapers, results):
        bm = scraper.bookmaker
        if isinstance(result, Exception):
            logger.error(f"[{bm}] Scraper task raised: {result}")
        elif isinstance(result, list):
            logger.debug(f"[{bm}] returned {len(result)} events.")
            all_events.extend(result)
        else:
            logger.warning(f"[{bm}] Unexpected result type: {type(result)}")

    logger.info(f"Total live events scraped across all bookmakers: {len(all_events)}")
    return all_events
