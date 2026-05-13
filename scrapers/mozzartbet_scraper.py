"""
Mozzart Bet Live Goals/Corners Scraper — Kenya Region.

Strategy: Mozzart's REST API endpoints return 404 — they are a Vue.js SPA
that loads match data dynamically via their internal JavaScript/WebSocket
pipeline. We render the SPA in a Playwright context and extract match data
directly from the rendered DOM via page.evaluate().

The live page at https://www.mozzartbet.co.ke/en#/live-betting renders
match cards with odds in the DOM after the Vue app hydrates. We inject a
JavaScript function that walks the DOM and extracts structured data.

Alternatively, the Mozzart app stores match state in the Vue instance's
$store (Vuex). We can tap into that directly via:
  document.querySelector('#spa').__vue_app__
or by finding the mbet.server_data global for static config.
"""
import os
import time
import random
import asyncio
from typing import List, Dict, Optional
from scrapers.base_scraper import BaseBookmakerScraper
from logger import get_logger

logger = get_logger("mozzartbet_scraper")

_LIVE_PAGE = "https://www.mozzartbet.co.ke/en#/live/sport/all"

# Market classification keywords
_GOALS_KW   = ("total goals", "over/under", "goals ou", "goals over", "total")
_CORNERS_KW = ("corner",)


class MozzartbetScraper(BaseBookmakerScraper):
    """
    Mozzart Bet live scraper.

    Opens the live page in a warm Playwright context, waits for the Vue.js
    SPA to render match data, then extracts structured odds from the DOM.
    """

    def __init__(self, identity_manager):
        self.im = identity_manager
        self.bookmaker = "mozzartbet"

    async def scrape_live_corners(self) -> List[Dict]:
        events: List[Dict] = []
        ctx = await self.im.get_context(f"{self.bookmaker}_scraper")
        if not ctx:
            logger.error(f"[{self.bookmaker}] Could not acquire context.")
            return events

        page = await ctx.new_page()
        try:
            # ── Step 1: Navigate and wait for SPA to render ──────────────────
            try:
                await page.goto(
                    _LIVE_PAGE,
                    wait_until="domcontentloaded",
                    timeout=20000,
                )
            except Exception as e:
                logger.warning(
                    f"[{self.bookmaker}] page.goto exception (continuing): {e}"
                )

            # Simulate human behavior: random mouse movements while waiting for hydration
            for _ in range(4):
                x = random.randint(100, 800)
                y = random.randint(100, 800)
                try:
                    await page.mouse.move(x, y, steps=10)
                except Exception:
                    pass
                await asyncio.sleep(random.uniform(1.5, 2.5))

            # ── Step 2: Extract match data from the Vuex store ───────────────
            raw_matches = await page.evaluate('''() => {
                try {
                    // ── Try Vue 2 first (Mozzart uses Vue 2 + Vuex) ──
                    const el = document.querySelector('#spa');
                    let store = null;

                    // Vue 2: instance lives at el.__vue__
                    if (el && el.__vue__) {
                        store = el.__vue__.$store;
                    }
                    // Vue 3 fallback
                    if (!store && el && el.__vue_app__) {
                        store = el.__vue_app__.config.globalProperties.$store;
                    }

                    if (!store) {
                        // Last resort: walk all elements for __vue__
                        const all = document.querySelectorAll('[id]');
                        for (const node of all) {
                            if (node.__vue__ && node.__vue__.$store) {
                                store = node.__vue__.$store;
                                break;
                            }
                        }
                    }

                    if (!store) return {source: 'no_store', matches: [], keys: []};

                    const state = store.state;
                    const matches = [];
                    const stateKeys = Object.keys(state);

                    // Walk through ALL store modules looking for live match data
                    function findMatches(obj, depth) {
                        if (depth > 3 || !obj || typeof obj !== 'object') return;
                        
                        // Check if this object has match-like arrays
                        for (const [key, val] of Object.entries(obj)) {
                            if (!Array.isArray(val) || val.length === 0) continue;
                            const first = val[0];
                            if (!first || typeof first !== 'object') continue;
                            
                            // Check for match-like properties
                            const hasTeams = first.home || first.homeTeam || 
                                           first.participants || first.homeTeamName ||
                                           first.competitor1 || first.team1;
                            const hasOdds = first.markets || first.odds || 
                                          first.oddsGroups || first.betGroups;
                            
                            if (hasTeams) {
                                for (const m of val) {
                                    const home = m.home?.name || m.homeTeam?.name || 
                                               m.homeTeamName || m.competitor1?.name ||
                                               m.team1?.name || (m.participants?.[0]?.name) || '';
                                    const away = m.away?.name || m.awayTeam?.name ||
                                               m.awayTeamName || m.competitor2?.name ||
                                               m.team2?.name || (m.participants?.[1]?.name) || '';
                                    if (!home || !away) continue;
                                    matches.push({
                                        home, away,
                                        minute: m.minute || m.matchTime || 
                                               m.timer?.minutes || m.time || 0,
                                        markets: m.markets || m.odds || 
                                                m.oddsGroups || m.betGroups || []
                                    });
                                }
                                return key;
                            }
                        }
                        
                        // Recurse into sub-objects (store modules)
                        for (const [key, val] of Object.entries(obj)) {
                            if (val && typeof val === 'object' && !Array.isArray(val)) {
                                const found = findMatches(val, depth + 1);
                                if (found) return key + '.' + found;
                            }
                        }
                        return null;
                    }

                    const foundKey = findMatches(state, 0);
                    return {
                        source: foundKey || 'store_empty', 
                        matches: matches, 
                        keys: stateKeys
                    };
                } catch (e) {
                    return {source: 'error', error: e.toString(), matches: []};
                }
            }''')

            source = raw_matches.get("source", "unknown")
            match_list = raw_matches.get("matches", [])

            if not match_list:
                logger.info(
                    f"[{self.bookmaker}] Vuex extraction returned 0 matches "
                    f"(source={source}, keys={raw_matches.get('keys', [])}). "
                    f"Falling back to DOM scrape."
                )
                # Fallback: scrape from rendered DOM
                match_list = await self._dom_scrape(page)

            # ── Step 3: Parse extracted data into standard format ────────────
            ts = time.time()
            for match in match_list:
                home   = match.get("home", "")
                away   = match.get("away", "")
                minute = int(match.get("minute", 0) or 0)

                for market in match.get("markets", []):
                    market_name = str(
                        market.get("name")
                        or market.get("marketName")
                        or market.get("groupName")
                        or ""
                    ).lower()

                    # Classify
                    if any(k in market_name for k in _CORNERS_KW):
                        market_type = "corners_ou"
                    elif any(k in market_name for k in _GOALS_KW):
                        market_type = "goals_ou"
                    else:
                        continue

                    outcomes = (
                        market.get("outcomes")
                        or market.get("odds")
                        or market.get("tips")
                        or []
                    )

                    for outcome in outcomes:
                        tip = str(
                            outcome.get("name")
                            or outcome.get("tip")
                            or outcome.get("outcomeName")
                            or ""
                        ).lower()
                        quota = (
                            outcome.get("odds")
                            or outcome.get("quota")
                            or outcome.get("value")
                        )
                        handicap = (
                            outcome.get("handicap")
                            or outcome.get("line")
                            or market.get("handicap")
                            or market.get("line")
                            or market.get("specifier")
                        )

                        if quota is None or handicap is None:
                            continue
                        try:
                            quota    = float(quota)
                            handicap = float(handicap)
                        except (TypeError, ValueError):
                            continue

                        if "over" in tip:
                            selection = "over"
                        elif "under" in tip:
                            selection = "under"
                        else:
                            continue

                        events.append({
                            "bookmaker":   self.bookmaker,
                            "home":        home,
                            "away":        away,
                            "is_live":     True,
                            "minute":      minute,
                            "market_type": market_type,
                            "line":        handicap,
                            "selection":   selection,
                            "odds":        quota,
                            "timestamp":   ts,
                        })

            matches = len({(e["home"], e["away"]) for e in events})
            logger.info(
                f"[{self.bookmaker}] Scraped {matches} matches → "
                f"{len(events)} market entries (source={source})."
            )

        except Exception as e:
            logger.error(f"[{self.bookmaker}] Scraper error: {e}")
        finally:
            await page.close()
            await self.im.release_context(f"{self.bookmaker}_scraper", ctx)

        return events

    async def _dom_scrape(self, page) -> List[Dict]:
        """Fallback: extract match data from the rendered HTML DOM."""
        try:
            # Dynamically wait for match rows to appear
            try:
                await page.wait_for_selector('.live-match, .match-row, [class*="match"], [class*="event-row"]', timeout=5000)
            except Exception as e:
                logger.debug(f"[{self.bookmaker}] wait_for_selector timed out in fallback: {e}")
                
            return await page.evaluate('''() => {
                const matches = [];
                // Mozzart renders match rows; look for common DOM patterns
                const rows = document.querySelectorAll(
                    '.live-match, .match-row, [class*="match"], [class*="event-row"]'
                );
                for (const row of rows) {
                    // Try to extract team names
                    const teamEls = row.querySelectorAll(
                        '.team-name, .participant, [class*="team"], [class*="competitor"]'
                    );
                    if (teamEls.length < 2) continue;

                    const home = teamEls[0]?.textContent?.trim() || '';
                    const away = teamEls[1]?.textContent?.trim() || '';
                    if (!home || !away) continue;

                    // Extract odds
                    const oddEls = row.querySelectorAll(
                        '.odd-value, .quota, [class*="odd"], [class*="quota"]'
                    );
                    const markets = [];
                    for (const el of oddEls) {
                        const text = el.textContent?.trim();
                        if (text && !isNaN(parseFloat(text))) {
                            markets.push({
                                name: 'unknown',
                                odds: parseFloat(text)
                            });
                        }
                    }

                    matches.push({home, away, minute: 0, markets: []});
                }
                return matches;
            }''')
        except Exception as e:
            logger.error(f"[{self.bookmaker}] DOM scrape error: {e}")
            return []
