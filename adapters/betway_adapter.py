"""
Betway Bookmaker Adapter.

Paper/limited mode: navigates, revalidates, fills stake — does NOT click "Place Bet".
Full mode: uncomment the place_bet click section and set DRY_RUN=False in .env.

Selector hot-swap: edit selectors.json under key "betway" — no code deploy needed.
"""
import asyncio
import random
from typing import Any, Dict, Tuple

from adapters.base_adapter import BaseBookmakerAdapter
from logger import get_logger
from config import EXECUTION_MODE, DRY_RUN

logger = get_logger("adapter.betway")


class BetWayAdapter(BaseBookmakerAdapter):

    def __init__(self):
        super().__init__("betway")

    async def navigate(self, page, leg: Dict[str, Any]) -> bool:
        url = leg.get("url") or "https://betway.com/en/sports"
        try:
            await page.goto(url, timeout=15_000)
            await self.simulate_human(page)
            self._log(leg.get("outcome", ""), "betway_navigate", {"url": url})
            return True
        except Exception as e:
            logger.warning(f"Betway navigation error: {e}")
            return False

    async def revalidate(self, page, expected_odds: float) -> Tuple[bool, float]:
        selector = self.selectors.get("odds_display", "")
        if not selector:
            logger.warning("Betway: no odds_display selector configured in selectors.json")
            return False, 0.0

        text = await self.get_text(page, selector)
        if text is None:
            return False, 0.0

        try:
            live_odds = float(text.replace(",", "."))
        except ValueError:
            logger.warning(f"Betway: could not parse odds text '{text}'")
            return False, 0.0

        matched = abs(live_odds - expected_odds) <= 0.02
        if not matched:
            logger.warning(f"Betway: odds mismatch — expected {expected_odds}, got {live_odds}")
        return matched, live_odds

    async def fill_stake(self, page, stake: float) -> bool:
        selector = self.selectors.get("stake_input", "")
        if not selector:
            logger.warning("Betway: no stake_input selector in selectors.json")
            # In paper mode we simulate success
            if EXECUTION_MODE in ("paper", "limited"):
                await asyncio.sleep(random.uniform(0.2, 0.6))
                return True
            return False

        await asyncio.sleep(random.uniform(0.3, 0.9))
        ok = await self.safe_fill(page, selector, str(round(stake, 2)))
        return ok

    async def place_bet(self, page, event_id: str, dry_run: bool) -> bool:
        if EXECUTION_MODE == "paper" or dry_run:
            logger.info(f"[{event_id}] [PAPER] Betway: simulated bet placement.")
            return True

        if EXECUTION_MODE == "limited":
            # Real click for limited amounts — selector must exist
            selector = self.selectors.get("place_bet_button", "")
            if not selector:
                logger.error("Betway: no place_bet_button selector — cannot execute limited mode")
                return False
            logger.info(f"[{event_id}] [LIMITED] Betway: placing real bet (limited stake).")
            return await self.safe_click(page, selector)

        # FULL mode — safety gate
        assert not DRY_RUN, "SAFETY: DRY_RUN is True but EXECUTION_MODE=full"
        selector = self.selectors.get("place_bet_button", "")
        if not selector:
            logger.error("Betway: no place_bet_button selector — aborting full execution")
            return False
        logger.info(f"[{event_id}] [FULL] Betway: placing live bet.")
        return await self.safe_click(page, selector, timeout=8_000)

    async def detect_captcha(self, page) -> bool:
        try:
            content = await page.content()
            url     = page.url
            return "captcha" in content.lower() or "robot" in url.lower() or "cf_chl" in url
        except Exception:
            return False
