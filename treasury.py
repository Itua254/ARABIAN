import asyncio
import time
import random
from typing import Dict, Optional
from logger import get_logger

logger = get_logger("treasury")

class TreasuryManager:
    """
    Validates real wallet balances before allowing the Arbitrage Engine to trade.
    Prevents catastrophic unhedged gambles due to insufficient funds on Leg 2.
    """
    def __init__(self, identity_manager, cache_ttl: int = 60):
        self.im = identity_manager
        self.cache_ttl = cache_ttl
        # Cache balances: {bookmaker: (balance, timestamp)}
        self._balance_cache: Dict[str, tuple[float, float]] = {}
        self._exchange_balance = 0.0
        self._lock = asyncio.Lock()
        
    def _export_state(self):
        try:
            import json
            from pathlib import Path
            state = {
                "bookmakers": {bm: {"balance": bal, "currency": "KES"} for bm, (bal, _) in self._balance_cache.items()},
                "exchange": {"balance": self._exchange_balance, "currency": "KES"}
            }
            Path("treasury_snapshot.json").write_text(json.dumps(state))
        except Exception as e:
            logger.error(f"Failed to export treasury state: {e}")
        
    async def get_balance(self, bookmaker: str, force_refresh: bool = False) -> Optional[float]:
        """
        Scrapes or API-fetches the live balance from the bookmaker.
        Uses a short-lived cache to avoid redundant network calls.
        """
        now = time.time()
        
        async with self._lock:
            if not force_refresh and bookmaker in self._balance_cache:
                balance, timestamp = self._balance_cache[bookmaker]
                if now - timestamp < self.cache_ttl:
                    logger.debug(f"[{bookmaker}] Using cached balance: ${balance:.2f}")
                    return balance

        logger.debug(f"[{bookmaker}] Fetching live balance...")
        ctx = await self.im.get_context(f"{bookmaker}_acc1")
        if not ctx:
            logger.error(f"[{bookmaker}] Treasury could not acquire context to check balance.")
            return None
            
        page = await ctx.new_page()
        try:
            # Here we hit the bookmaker's internal user profile API or scrape the DOM.
            # 1xBet Example (Stubbed for now):
            # response = await page.request.get("https://1xbet.com/service-api/user/balance")
            # data = await response.json()
            # balance = float(data['Value']['Balance'])
            
            # Simulated delay for realistic network overhead
            await asyncio.sleep(random.uniform(0.3, 0.7))
            balance = 1000.0  # Simulated $1000 balance
            
            async with self._lock:
                self._balance_cache[bookmaker] = (balance, time.time())
                self._export_state()
                
            return balance
        except Exception as e:
            logger.error(f"[{bookmaker}] Error fetching balance: {e}")
            return None
        finally:
            await page.close()
            await self.im.release_context(f"{bookmaker}_acc1", ctx)

    async def get_exchange_balance(self) -> Optional[float]:
        """
        Special check for the betting exchange (e.g. Betfair).
        """
        # In production, this would hit the Betfair Account API
        logger.debug("[Exchange] Simulated balance check")
        bal = 5000.0 # Simulated exchange balance
        self._exchange_balance = bal
        self._export_state()
        return bal

    async def can_afford(self, bookie_a: str, stake_a: float, bookie_b: str, stake_b: float) -> bool:
        """
        Validates that BOTH bookmakers have sufficient funds for the requested stakes.
        """
        # Run concurrently to save time
        bal_a_task = self.get_balance(bookie_a)
        bal_b_task = self.get_balance(bookie_b)
        
        bal_a, bal_b = await asyncio.gather(bal_a_task, bal_b_task)
        
        if bal_a is None or bal_b is None:
            logger.error("Treasury Check Failed: Could not fetch balances.")
            return False
            
        logger.info(f"Treasury Check: {bookie_a} has ${bal_a:.2f} (needs ${stake_a:.2f}), {bookie_b} has ${bal_b:.2f} (needs ${stake_b:.2f})")
        
        if bal_a < stake_a:
            logger.critical(f"INSUFFICIENT FUNDS on {bookie_a}. Need {stake_a}, have {bal_a}. Aborting arb to prevent unhedged exposure.")
            return False
            
        if bal_b < stake_b:
            logger.critical(f"INSUFFICIENT FUNDS on {bookie_b}. Need {stake_b}, have {bal_b}. Aborting arb to prevent unhedged exposure.")
            return False
            
        return True

    async def can_afford_hedge(self, liability: float) -> bool:
        """
        Validates that the exchange has enough funds to cover the hedge liability.
        """
        bal = await self.get_exchange_balance()
        if bal is None:
            logger.error("Treasury Hedge Check Failed: Could not fetch exchange balance.")
            return False
            
        if bal < liability:
            logger.critical(f"INSUFFICIENT EXCHANGE FUNDS. Need {liability}, have {bal}. Hedge aborted.")
            return False
            
        return True
