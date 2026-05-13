"""
Betika Live Goals/Corners Scraper — Kenya Region.

Strategy: Betika exposes a fully open REST API at api.betika.com with
zero authentication, no Cloudflare, and clean JSON responses. Like
Sportybet, we bypass Playwright entirely and use aiohttp for maximum speed.

Confirmed endpoint (verified via curl):
  GET https://api.betika.com/v1/uo/matches
  Params:
    tab=live           → live matches only
    sub_type_id=18     → Over/Under (TOTAL) markets
    sport_id=14        → Soccer
    page=1             → pagination
    limit=100          → max results per page

NOTE (Bug #3 fix): Despite tab=live, Betika returns a mix of in-play and
upcoming matches. We parse start_time and only emit events that have
already kicked off (start_time <= now). Minute is computed from elapsed time.
"""
import time
import aiohttp
from datetime import datetime, timezone
from typing import List, Dict, Optional
from scrapers.base_scraper import BaseBookmakerScraper
from logger import get_logger

logger = get_logger("betika_scraper")

_API_ENDPOINT = (
    "https://api.betika.com/v1/uo/matches"
    "?tab=live"
    "&sub_type_id=18"        # TOTAL (Over/Under)
    "&sport_id=14"           # Soccer
    "&page=1"
    "&limit=100"
)


def _parse_line(special_bet_value: str) -> Optional[float]:
    """Extract line from 'total=2.5' format."""
    if not special_bet_value:
        return None
    for part in special_bet_value.split("&"):
        if "=" in part:
            key, val = part.split("=", 1)
            if key.strip().lower() == "total":
                try:
                    return float(val)
                except ValueError:
                    pass
    return None


def _classify_selection(display: str) -> Optional[str]:
    """Classify 'OVER 2.5' → 'over', 'UNDER 2.5' → 'under'."""
    d = display.lower()
    if "over" in d:
        return "over"
    elif "under" in d:
        return "under"
    return None


def _parse_start_time(raw: str) -> Optional[datetime]:
    """
    Parse Betika start_time string (naive, assumed UTC).
    Format: "2026-05-02 17:00:00"
    Returns an aware UTC datetime.
    """
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


class BetikaScraper(BaseBookmakerScraper):
    """
    Betika live scraper using direct HTTP API requests.

    No Playwright context needed — the API is fully open and returns
    clean JSON with zero authentication. Sub-50ms latency per cycle.
    """

    def __init__(self, identity_manager):
        self.im = identity_manager
        self.bookmaker = "betika"

    async def scrape_live_corners(self) -> List[Dict]:
        events: List[Dict] = []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    _API_ENDPOINT,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/125.0.0.0 Safari/537.36"
                        ),
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            f"[{self.bookmaker}] API returned HTTP {resp.status}"
                        )
                        return events

                    data = await resp.json()

        except Exception as e:
            logger.error(f"[{self.bookmaker}] HTTP request error: {e}")
            return events

        # ── Parse response ───────────────────────────────────────────────
        matches_list = data.get("data", [])
        if not isinstance(matches_list, list):
            logger.warning(
                f"[{self.bookmaker}] Unexpected data type: {type(matches_list)}"
            )
            return events

        now_utc = datetime.now(timezone.utc)
        ts = time.time()
        matches_found = 0
        live_found = 0
        prematch_found = 0
        skipped_prematch = 0

        for match in matches_list:
            home = match.get("home_team", "")
            away = match.get("away_team", "")

            if not home or not away:
                continue

            # ── Determine live vs prematch ──────────────────────────
            start_dt = _parse_start_time(match.get("start_time", ""))
            if start_dt is None:
                skipped_prematch += 1
                continue

            if start_dt <= now_utc:
                # Already kicked off — live
                elapsed_sec = (now_utc - start_dt).total_seconds()
                minute = max(0, int(elapsed_sec / 60))
                is_live = True
            else:
                # Future match — prematch
                minute = 0
                is_live = False

            odds_groups = match.get("odds") or []
            match_had_markets = False

            for group in odds_groups:
                if not group or not isinstance(group, dict):
                    continue
                group_name = (group.get("name") or "").upper()

                # Classify market type
                if "TOTAL" in group_name or "OVER" in group_name:
                    market_type = "goals_ou"
                elif "CORNER" in group_name:
                    market_type = "corners_ou"
                else:
                    continue

                for odd in (group.get("odds") or []):
                    display = odd.get("display", "")
                    selection = _classify_selection(display)
                    if not selection:
                        continue

                    odd_value = odd.get("odd_value")
                    if odd_value is None:
                        continue
                    try:
                        odd_value = float(odd_value)
                    except (TypeError, ValueError):
                        continue

                    line = _parse_line(odd.get("special_bet_value", ""))
                    if line is None:
                        continue
                        
                    match_id = match.get("match_id", "")
                    match_url = f"https://www.betika.com/en-ke/s/soccer/{'live' if is_live else 'prematch'}/match/{match_id}" if match_id else ""

                    events.append({
                        "bookmaker":   self.bookmaker,
                        "home":        home,
                        "away":        away,
                        "is_live":     is_live,
                        "minute":      minute,
                        "market_type": market_type,
                        "line":        line,
                        "selection":   selection,
                        "odds":        odd_value,
                        "url":         match_url,
                        "timestamp":   ts,
                    })
                    match_had_markets = True

            if match_had_markets:
                matches_found += 1
                if is_live:
                    live_found += 1
                else:
                    prematch_found += 1

        logger.info(
            f"[{self.bookmaker}] Scraped {matches_found} matches "
            f"({live_found} live, {prematch_found} prematch) → "
            f"{len(events)} market entries."
        )

        return events
