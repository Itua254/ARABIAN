import asyncio
import random
import time
from typing import Dict, List, Optional

from logger import get_logger, log_event
from config import TARGET_BOOKMAKERS, DRY_RUN
from adapters.onexbet_adapter import OnexBetAdapter

logger = get_logger("smoke_screen")

class PunterModule:
    """
    The "Smoke Screen" Module.
    Occasionally places slightly negative EV "square" bets on heavy favorites
    to disguise the account from VIP/Risk teams and prevent limits.
    """
    def __init__(self, identity_manager):
        self.im = identity_manager
        
    async def try_place_smoke_bet(self, events: List[Dict]) -> bool:
        """
        Attempts to find a heavy favorite and place a $2 "dumb" bet.
        """
        if not events:
            return False
            
        logger.info("Evaluating smoke screen bet placement...")
        
        # We look for a Match Winner or similar low-odds bet
        # In a full implementation, we'd specifically request `G=1` from the API.
        # Here we just look through existing events for something with low odds.
        candidates = []
        for e in events:
            if 1.20 <= e["odds"] <= 1.60 and e["bookmaker"] in TARGET_BOOKMAKERS:
                candidates.append(e)
                
        if not candidates:
            logger.info("No suitable smoke screen candidates found.")
            return False
            
        target_event = random.choice(candidates)
        bookie = target_event["bookmaker"].lower()
        
        # For simplicity in this demo, we only invoke the OnexBet/Melbet adapter
        if bookie not in ("1xbet", "melbet"):
            return False
            
        logger.warning(f"🚬 SMOKE SCREEN ACTIVATED: Placing $2 decoy bet on {target_event['home']} vs {target_event['away']} @ {target_event['odds']} ({bookie})")
        
        # Prepare mock leg for adapter
        leg = {
            "bookmaker": bookie,
            "odds": target_event["odds"],
            "stake": 2.0,
            "url": "https://1xbet.com/en/live" if bookie == "1xbet" else "https://melbet.com/en/live"
        }
        
        adapter = OnexBetAdapter()
        identity_id = f"{bookie}_acc1"
        ctx = await self.im.get_context(identity_id)
        if not ctx:
            logger.error(f"Could not acquire context for {bookie} smoke screen.")
            return False
            
        page = await ctx.new_page()
        success = False
        try:
            if not await adapter.navigate(page, leg):
                return False
                
            # Simulate human hesitation after navigation
            await asyncio.sleep(random.uniform(2.0, 4.0))
            for _ in range(3):
                await page.mouse.move(random.randint(100, 800), random.randint(100, 800), steps=5)
                await asyncio.sleep(random.uniform(0.5, 1.5))
                
            revalidated, _ = await adapter.revalidate(page, leg["odds"])
            if not revalidated:
                return False
                
            # Simulate human hesitation before typing stake
            await page.mouse.move(random.randint(300, 600), random.randint(300, 600), steps=10)
            await asyncio.sleep(random.uniform(1.0, 2.0))
                
            if not await adapter.fill_stake(page, leg["stake"]):
                return False
                
            # Simulate human hesitation before clicking place bet
            await asyncio.sleep(random.uniform(1.5, 3.0))
            await page.mouse.move(random.randint(400, 500), random.randint(400, 500), steps=5)
                
            success = await adapter.place_bet(page, f"SMOKE_{int(time.time())}", DRY_RUN)
        except Exception as e:
            logger.error(f"Smoke screen execution failed: {e}")
        finally:
            await page.close()
            await self.im.release_context(identity_id, ctx)
            
        if success:
            log_event("smoke_screen_success", {"bookmaker": bookie, "odds": target_event["odds"]})
            logger.info("Smoke screen bet successfully placed.")
            return True
            
        return False
