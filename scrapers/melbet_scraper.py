import time
import asyncio
from typing import List, Dict
from scrapers.base_scraper import BaseBookmakerScraper
from logger import get_logger

logger = get_logger("melbet_scraper")

class MelbetScraper(BaseBookmakerScraper):
    def __init__(self, identity_manager):
        self.im = identity_manager
        self.bookmaker = "melbet"
        
    async def scrape_live_corners(self) -> List[Dict]:
        events = []
        ctx = await self.im.get_context(f"{self.bookmaker}_scraper")
        if not ctx:
            logger.error(f"[{self.bookmaker}] Could not acquire context for scraping.")
            return events
            
        page = await ctx.new_page()
        try:
            try:
                # We load the page once to solve captchas/cloudflare
                await page.goto("https://melbet.ke/en/live/football", wait_until="commit", timeout=15000)
                await page.goto("https://melbet.ke/en/line/football", wait_until="commit", timeout=15000)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"[{self.bookmaker}] page.goto exception (continuing): {e}")
            
            # Melbet uses the exact same backend as 1xBet
            urls = [
                ("LiveFeed", "https://melbet.ke/service-api/LiveFeed/Get1x2_VZip?sports=1&count=50&lng=en&mode=4&getEmpty=true&noFilterBlockEvent=true"),
                ("LineFeed", "https://melbet.ke/service-api/LineFeed/Get1x2_VZip?sports=1&count=50&lng=en&mode=4")
            ]
            
            for feed_type, url in urls:
                data = None
                for attempt in range(3):
                    try:
                        response = await page.request.get(url, timeout=10000)
                        temp_data = await response.json()
                        if temp_data and temp_data.get("Success") and temp_data.get("Value"):
                            data = temp_data
                            break
                        else:
                            logger.debug(f"[{self.bookmaker}] {feed_type} empty, retrying...")
                    except Exception as e:
                        logger.warning(f"[{self.bookmaker}] {feed_type} request failed (attempt {attempt+1}): {e}")
                    await asyncio.sleep(1.5 ** attempt) # Exponential backoff
                
                if not data:
                    logger.warning(f"[{self.bookmaker}] {feed_type} requests exhausted or empty")
                    continue
                    
                is_live = (feed_type == "LiveFeed")
                    
                for match in data.get("Value", []):
                    home = match.get("O1", "")
                    away = match.get("O2", "")
                    
                    sc = match.get("SC", {})
                    sls = sc.get("SLS", "0 minutes")
                    try:
                        minute = int(sls.split()[0])
                    except Exception:
                        minute = 0
                        
                    if not is_live:
                        minute = 0
                    
                    odds_array = match.get("E", [])
                    lines = {}
                    for odd in odds_array:
                        g = odd.get("G")
                        t = odd.get("T")
                        p = odd.get("P")
                        c = odd.get("C")
                        
                        if g == 17 and p is not None:
                            if p not in lines:
                                lines[p] = {"over": None, "under": None}
                            if t == 9:
                                lines[p]["over"] = c
                            elif t == 10:
                                lines[p]["under"] = c
                    
                    match_id = match.get("I", "")
                    match_url = f"https://melbet.ke/en/live/football/-/-/{match_id}" if match_id else ""
                    
                    timestamp = time.time()
                    for line, odds_pair in lines.items():
                        if odds_pair["over"] and odds_pair["under"]:
                            events.append({
                                "bookmaker": self.bookmaker,
                                "home": home,
                                "away": away,
                                "is_live": is_live,
                                "minute": minute,
                                "market_type": "goals_ou",
                                "selection": "over",
                                "line": float(line),
                                "odds": float(odds_pair["over"]),
                                "url": match_url,
                                "timestamp": timestamp
                            })
                            events.append({
                                "bookmaker": self.bookmaker,
                                "home": home,
                                "away": away,
                                "is_live": is_live,
                                "minute": minute,
                                "market_type": "goals_ou",
                                "selection": "under",
                                "line": float(line),
                                "odds": float(odds_pair["under"]),
                                "url": match_url,
                                "timestamp": timestamp
                            })
                            
        except Exception as e:
            logger.error(f"[{self.bookmaker}] API Scraper error: {e}")
        finally:
            await page.close()
            await self.im.release_context(f"{self.bookmaker}_scraper", ctx)
            
        return events
