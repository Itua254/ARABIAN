"""
Identity Manager — v5 §5 Session Pool + Burned Account Persistence.

Upgrades:
  - SessionPool: asyncio.Queue of warm browser contexts per bookmaker
  - Burned account registry persisted to burned_accounts.json
  - Proxy rotation from PROXY_LIST config
"""
import asyncio
import json
import os
import random
from typing import Dict, Any, Optional, List

from playwright.async_api import async_playwright, Browser, BrowserContext
from playwright_stealth import stealth
from logger import get_logger, log_event
from config import SESSION_POOL_SIZE, PROXY_LIST

logger = get_logger("identity_manager")

BURNED_PATH = "burned_accounts.json"


class SessionPool:
    """
    Pre-warmed pool of browser contexts for a specific identity.
    v5 §5.2 — eliminates cold-browser latency on first trade.
    """

    def __init__(self, browser: Browser, identity_id: str, proxy: Optional[Dict] = None):
        self._browser   = browser
        self._id        = identity_id
        self._proxy     = proxy
        self._queue: asyncio.Queue[BrowserContext] = asyncio.Queue()

    async def preload(self, n: int = SESSION_POOL_SIZE) -> None:
        """Warm N contexts before execution starts. v5 §5.2."""
        logger.info(f"[{self._id}] Pre-warming {n} browser contexts...")
        tasks = [self._create_context() for _ in range(n)]
        contexts = await asyncio.gather(*tasks, return_exceptions=True)
        for ctx in contexts:
            if isinstance(ctx, BrowserContext):
                await self._queue.put(ctx)
        logger.info(f"[{self._id}] Session pool ready ({self._queue.qsize()} contexts).")

    async def get(self) -> BrowserContext:
        """Pop a context from the pool. Creates a new one if pool is empty."""
        if self._queue.empty():
            logger.debug(f"[{self._id}] Pool empty — creating new context on-demand.")
            return await self._create_context()
        return await self._queue.get()

    async def release(self, ctx: BrowserContext) -> None:
        """Return a healthy context back to the pool."""
        await self._queue.put(ctx)

    async def _create_context(self) -> BrowserContext:
        args: Dict[str, Any] = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1920, "height": 1080},
            "locale":   "en-GB",
            "timezone_id": "Europe/London",
        }
        if self._proxy:
            args["proxy"] = self._proxy

        ctx = await self._browser.new_context(**args)
        from playwright_stealth import Stealth
        await Stealth().apply_stealth_async(ctx)

        # Core anti-detect script
        await ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            "window.chrome = {runtime: {}};"
        )

        # Load saved cookies if they exist
        state_file = f"state_{self._id}.json"
        if os.path.exists(state_file):
            try:
                with open(state_file) as f:
                    cookies = json.load(f)
                await ctx.add_cookies(cookies)
                logger.debug(f"[{self._id}] Loaded cookies from {state_file}")
            except Exception as e:
                logger.warning(f"[{self._id}] Failed to load cookies: {e}")

        return ctx


class IdentityManager:
    """
    Manages browser identities with:
      - Per-identity session pools (warm contexts)
      - Proxy rotation
      - Burned account persistence across restarts
    """

    def __init__(self):
        self.playwright     = None
        self.browser: Optional[Browser] = None
        self._pools:   Dict[str, SessionPool]     = {}
        self._contexts: Dict[str, BrowserContext] = {}  # fallback single contexts
        self._burned:   set                       = set()
        self._load_burned()

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self) -> None:
        logger.info("Starting Playwright Identity Manager with session pooling...")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

    async def preload_pool(self, identity_id: str) -> None:
        """Pre-warm a session pool for a given identity. Call on startup."""
        if self.is_burned(identity_id):
            logger.warning(f"[{identity_id}] Skipping preload — account is burned.")
            return
        proxy = self._pick_proxy()
        pool = SessionPool(self.browser, identity_id, proxy)
        await pool.preload()
        self._pools[identity_id] = pool

    async def close(self) -> None:
        logger.info("Closing Identity Manager...")
        for identity_id, ctx in self._contexts.items():
            await self._save_state(identity_id, ctx)
            await ctx.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    # ── Context access ────────────────────────────────────────

    async def get_context(self, identity_id: str) -> Optional[BrowserContext]:
        """
        Returns a context from the pool (preferred) or creates one.
        Returns None if the account is burned.
        """
        if self.is_burned(identity_id):
            logger.warning(f"[{identity_id}] Context request denied — account is burned.")
            return None

        if identity_id in self._pools:
            return await self._pools[identity_id].get()

        # Fallback: legacy single-context path
        return await self.get_or_create_context(identity_id)

    async def release_context(self, identity_id: str, ctx: BrowserContext) -> None:
        """Returns a context to its pool."""
        if identity_id in self._pools:
            await self._pools[identity_id].release(ctx)

    async def get_or_create_context(
        self, identity_id: str, proxy: Optional[Dict[str, str]] = None
    ) -> BrowserContext:
        """Legacy single-context creation (used as fallback)."""
        if identity_id in self._contexts:
            return self._contexts[identity_id]

        logger.info(f"Creating new context for {identity_id}")
        resolved_proxy = proxy or self._pick_proxy()

        args: Dict[str, Any] = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1920, "height": 1080},
        }
        if resolved_proxy:
            args["proxy"] = {"server": resolved_proxy}

        ctx = await self.browser.new_context(**args)
        from playwright_stealth import Stealth
        await Stealth().apply_stealth_async(ctx)

        await ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        state_file = f"state_{identity_id}.json"
        if os.path.exists(state_file):
            try:
                with open(state_file) as f:
                    await ctx.add_cookies(json.load(f))
            except Exception as e:
                logger.warning(f"Failed to load state for {identity_id}: {e}")

        self._contexts[identity_id] = ctx
        return ctx

    # ── Burned accounts ───────────────────────────────────────

    def burn_account(self, identity_id: str) -> None:
        """
        Permanently disables an identity. Persisted across restarts.
        Called when a captcha or security block is detected.
        """
        self._burned.add(identity_id)
        self._save_burned()
        log_event("account_burned", {"identity_id": identity_id})
        logger.critical(f"Account BURNED and persisted: {identity_id}")

    def is_burned(self, identity_id: str) -> bool:
        return identity_id in self._burned

    def burned_list(self) -> List[str]:
        return list(self._burned)

    def _load_burned(self) -> None:
        if os.path.exists(BURNED_PATH):
            try:
                with open(BURNED_PATH) as f:
                    self._burned = set(json.load(f))
                logger.info(f"Loaded {len(self._burned)} burned accounts from {BURNED_PATH}")
            except Exception as e:
                logger.warning(f"Could not load burned accounts: {e}")
                self._burned = set()

    def _save_burned(self) -> None:
        try:
            with open(BURNED_PATH, "w") as f:
                json.dump(list(self._burned), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to persist burned accounts: {e}")

    # ── Proxy rotation ────────────────────────────────────────

    def _pick_proxy(self) -> Optional[str]:
        """Returns a random proxy from PROXY_LIST, or None if unconfigured."""
        if PROXY_LIST:
            return random.choice(PROXY_LIST)
        return None

    # ── State persistence ─────────────────────────────────────

    async def _save_state(self, identity_id: str, ctx: BrowserContext) -> None:
        try:
            cookies = await ctx.cookies()
            with open(f"state_{identity_id}.json", "w") as f:
                json.dump(cookies, f)
            logger.debug(f"Saved cookies for {identity_id}")
        except Exception as e:
            logger.error(f"Failed to save state for {identity_id}: {e}")
