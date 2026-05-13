"""
Pinnacle Bookmaker Adapter.

Pinnacle is a sharp bookmaker — typically the limiting leg.
Paper/limited stubs are fully implemented; full execution requires
selector mapping in selectors.json under key "pinnacle".
"""
import asyncio
import random
from typing import Any, Dict, Tuple

from adapters.base_adapter import BaseBookmakerAdapter
from logger import get_logger
from config import EXECUTION_MODE, DRY_RUN

logger = get_logger("adapter.pinnacle")


class PinnacleAdapter(BaseBookmakerAdapter):

    def __init__(self):
        super().__init__("pinnacle")

    async def navigate(self, page, leg: Dict[str, Any]) -> bool:
        url = leg.get("url") or "https://www.pinnacle.com/en/soccer"
        try:
            await page.goto(url, timeout=15_000)
            await self.simulate_human(page)
            self._log(leg.get("outcome", ""), "pinnacle_navigate", {"url": url})
            return True
        except Exception as e:
            logger.warning(f"Pinnacle navigation error: {e}")
            return False

    async def revalidate(self, page, expected_odds: float) -> Tuple[bool, float]:
        selector = self.selectors.get("odds_display", "")
        if not selector:
            logger.warning("Pinnacle: no odds_display selector in selectors.json — simulating match.")
            if EXECUTION_MODE in ("paper", "limited"):
                return True, expected_odds
            return False, 0.0

        text = await self.get_text(page, selector)
        if text is None:
            return False, 0.0

        try:
            live_odds = float(text.replace(",", "."))
        except ValueError:
            return False, 0.0

        matched = abs(live_odds - expected_odds) <= 0.02
        return matched, live_odds

    async def fill_stake(self, page, stake: float) -> bool:
        selector = self.selectors.get("stake_input", "")
        if not selector:
            logger.warning("Pinnacle: no stake_input selector — simulating in paper mode.")
            if EXECUTION_MODE in ("paper", "limited"):
                await asyncio.sleep(random.uniform(0.2, 0.5))
                return True
            return False

        await asyncio.sleep(random.uniform(0.3, 0.8))
        return await self.safe_fill(page, selector, str(round(stake, 2)))

    async def place_bet(self, page, event_id: str, dry_run: bool) -> bool:
        if EXECUTION_MODE == "paper" or dry_run:
            logger.info(f"[{event_id}] [PAPER] Pinnacle: simulated bet placement.")
            return True

        if EXECUTION_MODE == "limited":
            selector = self.selectors.get("place_bet_button", "")
            if not selector:
                logger.error("Pinnacle: no place_bet_button selector — cannot execute limited mode")
                return False
            logger.info(f"[{event_id}] [LIMITED] Pinnacle: placing real bet (limited stake).")
            return await self.safe_click(page, selector)

        assert not DRY_RUN, "SAFETY: DRY_RUN is True but EXECUTION_MODE=full"
        selector = self.selectors.get("place_bet_button", "")
        if not selector:
            logger.error("Pinnacle: no place_bet_button selector — aborting full execution")
            return False
        logger.info(f"[{event_id}] [FULL] Pinnacle: placing live bet.")
        return await self.safe_click(page, selector, timeout=8_000)

    async def detect_captcha(self, page) -> bool:
        try:
            content = await page.content()
            url     = page.url
            return "captcha" in content.lower() or "robot" in url.lower()
        except Exception:
            return False
