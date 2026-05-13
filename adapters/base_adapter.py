"""
BaseBookmakerAdapter — v5 §13 Adapter Framework.

Every bookmaker adapter must subclass this and implement the abstract methods.
The execution engine calls the public interface only; each adapter is responsible
for its own navigation, revalidation, stake entry, and bet placement flow.
"""
import asyncio
import json
import os
import random
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple

from logger import get_logger, log_event

logger = get_logger("adapter.base")

# Hot-reload selector map — loaded once, can be refreshed by touching selectors.json
_SELECTOR_CACHE: Optional[Dict[str, Any]] = None
_SELECTORS_PATH = os.path.join(os.path.dirname(__file__), "..", "selectors.json")


def get_selectors(bookmaker: str) -> Dict[str, str]:
    """Returns the CSS selector map for the given bookmaker (hot-reloadable)."""
    global _SELECTOR_CACHE
    try:
        with open(_SELECTORS_PATH, "r") as f:
            _SELECTOR_CACHE = json.load(f)
    except Exception:
        if _SELECTOR_CACHE is None:
            _SELECTOR_CACHE = {}
    return _SELECTOR_CACHE.get(bookmaker.lower(), {})


class BaseBookmakerAdapter(ABC):
    """
    Abstract base for all bookmaker execution adapters.

    Subclasses implement:
      navigate()      — load the event URL
      revalidate()    — confirm live odds still match expectation
      fill_stake()    — enter the stake amount
      place_bet()     — click the confirm/place button
      detect_captcha()— return True if a captcha wall is detected
    """

    def __init__(self, bookmaker_name: str):
        self.name = bookmaker_name.lower()
        self.selectors = get_selectors(self.name)
        self._logger = get_logger(f"adapter.{self.name}")

    # ── Abstract interface ────────────────────────────────────

    @abstractmethod
    async def navigate(self, page, leg: Dict[str, Any]) -> bool:
        """Navigate to the event page. Return False on timeout/error."""

    @abstractmethod
    async def revalidate(self, page, expected_odds: float) -> Tuple[bool, float]:
        """
        Check that live odds match expected_odds.
        Returns (match: bool, live_odds: float).
        """

    @abstractmethod
    async def fill_stake(self, page, stake: float) -> bool:
        """Enter stake in the betslip. Return False if element not found."""

    @abstractmethod
    async def place_bet(self, page, event_id: str, dry_run: bool) -> bool:
        """
        Click the confirm/place button (or simulate in dry_run mode).
        Return True on success.
        """

    @abstractmethod
    async def detect_captcha(self, page) -> bool:
        """Return True if a captcha / bot-detection wall is present."""

    # ── Shared helpers (available to all subclasses) ──────────

    async def simulate_human(self, page) -> None:
        """Random mouse movement + scroll to evade bot detection."""
        await page.mouse.move(
            random.randint(200, 1200), random.randint(200, 700)
        )
        await asyncio.sleep(random.uniform(0.15, 0.6))
        await page.mouse.wheel(0, random.randint(100, 600))
        await asyncio.sleep(random.uniform(0.2, 0.8))

    async def safe_click(self, page, selector: str, timeout: int = 5000) -> bool:
        """Clicks a selector, returning False instead of raising on miss."""
        try:
            await page.wait_for_selector(selector, timeout=timeout)
            await page.click(selector)
            return True
        except Exception as e:
            self._logger.warning(f"safe_click failed on '{selector}': {e}")
            return False

    async def safe_fill(self, page, selector: str, value: str, timeout: int = 5000) -> bool:
        """Fills a text input, returning False on miss."""
        try:
            await page.wait_for_selector(selector, timeout=timeout)
            await page.fill(selector, value)
            return True
        except Exception as e:
            self._logger.warning(f"safe_fill failed on '{selector}': {e}")
            return False

    async def get_text(self, page, selector: str, timeout: int = 5000) -> Optional[str]:
        """Returns inner text of a selector, or None on miss."""
        try:
            await page.wait_for_selector(selector, timeout=timeout)
            return (await page.inner_text(selector)).strip()
        except Exception:
            return None

    def _log(self, event_id: str, event_type: str, data: Dict[str, Any]) -> None:
        self._logger.debug(f"[{event_id}] {event_type}: {data}")
        log_event(event_type, {"bookmaker": self.name, "event_id": event_id, **data})
