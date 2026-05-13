"""
1xBet Bookmaker Adapter.

1xBet has aggressive anti-bot measures. The navigate() method sets
a realistic Accept-Language header via extra HTTP headers to reduce
fingerprinting. Paper/limited stubs are fully implemented.
"""
import asyncio
import random
from typing import Any, Dict, Tuple

from adapters.base_adapter import BaseBookmakerAdapter
from logger import get_logger
from config import EXECUTION_MODE, DRY_RUN

logger = get_logger("adapter.onexbet")


class OnexBetAdapter(BaseBookmakerAdapter):

    def __init__(self):
        super().__init__("onexbet")

    async def navigate(self, page, leg: Dict[str, Any]) -> bool:
        url = leg.get("url") or "https://1xbet.com/en/live"
        try:
            # 1xBet benefits from extra request headers to look more organic
            await page.set_extra_http_headers({
                "Accept-Language": "en-GB,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
            })
            await page.goto(url, timeout=18_000)
            await self.simulate_human(page)
            # 1xBet sometimes loads a geo-redirect overlay; dismiss it
            dismiss_sel = self.selectors.get("dismiss_overlay", "")
            if dismiss_sel:
                try:
                    await page.wait_for_selector(dismiss_sel, timeout=3_000)
                    await page.click(dismiss_sel)
                except Exception:
                    pass
            self._log(leg.get("outcome", ""), "onexbet_navigate", {"url": url})
            return True
        except Exception as e:
            logger.warning(f"1xBet navigation error: {e}")
            return False

    async def revalidate(self, page, expected_odds: float) -> Tuple[bool, float]:
        selector = self.selectors.get("odds_display", "")
        if not selector:
            logger.warning("1xBet: no odds_display selector in selectors.json — simulating match.")
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
        if not matched:
            logger.warning(f"1xBet: odds mismatch — expected {expected_odds}, got {live_odds}")
        return matched, live_odds

    async def fill_stake(self, page, stake: float) -> bool:
        selector = self.selectors.get("stake_input", "")
        if not selector:
            if EXECUTION_MODE in ("paper", "limited"):
                await asyncio.sleep(random.uniform(0.2, 0.5))
                return True
            return False

        # 1xBet sometimes needs the input cleared first
        try:
            await page.wait_for_selector(selector, timeout=5_000)
            await page.triple_click(selector)
            await asyncio.sleep(random.uniform(0.1, 0.3))
        except Exception:
            pass

        await asyncio.sleep(random.uniform(0.2, 0.6))
        return await self.safe_fill(page, selector, str(round(stake, 2)))

    async def place_bet(self, page, event_id: str, dry_run: bool) -> bool:
        if EXECUTION_MODE == "paper" or dry_run:
            logger.info(f"[{event_id}] [PAPER] 1xBet: simulated bet placement.")
            return True

        if EXECUTION_MODE == "limited":
            selector = self.selectors.get("place_bet_button", "")
            if not selector:
                logger.error("1xBet: no place_bet_button selector — cannot execute limited mode")
                return False
            logger.info(f"[{event_id}] [LIMITED] 1xBet: placing real bet (limited stake).")
            return await self.safe_click(page, selector)

        assert not DRY_RUN, "SAFETY: DRY_RUN is True but EXECUTION_MODE=full"
        selector = self.selectors.get("place_bet_button", "")
        if not selector:
            logger.error("1xBet: no place_bet_button selector — aborting full execution")
            return False
        logger.info(f"[{event_id}] [FULL] 1xBet: placing live bet.")
        return await self.safe_click(page, selector, timeout=8_000)

    async def detect_captcha(self, page) -> bool:
        try:
            content = await page.content()
            url     = page.url
            return any(x in content.lower() for x in ["captcha", "recaptcha", "are you human"]) \
                   or "cf_chl" in url or "robot" in url.lower()
        except Exception:
            return False
