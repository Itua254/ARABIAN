"""
Arb Detector — v7 Strict Mode (Live Goals/Corners Over/Under).

Team-name normalization:
  1. Canonical alias table for known variants (Sportybet/Mozzart vs 1xBet names).
  2. Levenshtein-ratio fuzzy fallback for unknown teams (threshold 0.82).
  3. Alphabetical sort of team pair → stable synthetic event_id.

Same-bookmaker guard:
  Over and Under legs MUST come from DIFFERENT bookmakers, otherwise we
  are just hedging within one book (no edge).

Same-feed guard (Bug #6 fix):
  1xBet and Melbet share the same BetB2B pricing engine. Arbs between
  them are not real cross-bookmaker opportunities.
"""
from typing import List, Dict
import time
import re
from difflib import SequenceMatcher
from config import MIN_EDGE, BANKROLL, MAX_ODDS_AGE_SEC, MARKETS
from logger import get_logger

logger = get_logger("arb_detector")

# ── Same-feed bookmaker groups (Bug #6 fix) ────────────────────────────────
# Bookmakers within the same group share a backend — arbs between them are fake.
_SAME_FEED_GROUPS: List[set] = [
    {"1xbet", "melbet"},   # BetB2B cluster
]

def _same_feed(bm_a: str, bm_b: str) -> bool:
    """Returns True if bm_a and bm_b share the same pricing feed."""
    for group in _SAME_FEED_GROUPS:
        if bm_a in group and bm_b in group:
            return True
    return False


# ── Canonical alias table ──────────────────────────────────────────────────
_ALIASES: Dict[str, List[str]] = {
    "manchesterunited":  ["manutd", "manunited", "manchesterutd", "man united", "man utd"],
    "manchestercity":    ["mancity", "man city"],
    "arsenalfc":         ["arsenal"],
    "chelseafc":         ["chelsea"],
    "liverpoolfc":       ["liverpool"],
    "tottenhamhotspur":  ["tottenham", "spurs", "tottenhamfc"],
    "realmadrid":        ["real madrid", "r madrid", "realmadridcf"],
    "barcelonafc":       ["barcelona", "fcbarcelona", "barca"],
    "atleticomadrid":    ["atletico", "atleti", "atleticodemadrid"],
    "bayernmunich":      ["fcbayern", "bayernmunchen", "fcbayernmunchen", "fcbayermunich"],
    "borussiadortmund":  ["dortmund", "bvb"],
    "psgfc":             ["psg", "parissg", "parissaintgermain", "paris"],
    "acmilan":           ["milan", "acmilanfc"],
    "internazionale":    ["inter", "intermilan", "fcinter"],
    "juventusfc":        ["juventus", "juve"],
    "asroma":            ["roma"],
    "napolicfc":         ["napoli"],
    "ajaxfc":            ["ajax"],
    "portofc":           ["porto", "fcporto"],
    "benficafc":         ["benfica", "slbenfica"],
    "sevillafc":         ["sevilla"],
    "villarrealcf":      ["villarreal"],
    "rafagor":           ["rafa gor", "gormahia", "gor mahia"],
    "afcleopards":       ["leopards", "afc leopards", "ingwecf"],
    "tuskerfc":          ["tusker", "kbl"],
    "kazionsports":      ["kazio"],
    "sofapaka":          ["sofapaka fc"],
    "citystarske":       ["city stars"],
    "bandarifc":         ["bandari"],
    "kariobangi":        ["kariobangi sharks", "sharks"],
    "wazalendo":         ["kenya wazalendo"],
    "kawangware":        ["kawangware united"],
    "kisumu":            ["kisumu allstars"],
    # EPL common short forms (Betika uses short names)
    "newcastleunited":   ["newcastle", "nufc"],
    "brighton":          ["brighton", "brighton hove"],
    "wolverhampton":     ["wolves", "wolverhampton wanderers"],
    "brentfordfc":       ["brentford"],
    "nottinghamforest":  ["nottingham", "forest", "nffc"],
    "astonvilla":        ["aston villa", "villa"],
    "westhamunited":     ["west ham", "westham", "whufc"],
    "crystalpalace":     ["palace", "crystal palace"],
    "ipswich":           ["ipswich town"],
    "leicestercity":     ["leicester"],
    "soutampton":        ["southampton", "saints"],
    "evertonfc":         ["everton"],
    "fulhamfc":          ["fulham"],
    "bournemouth":       ["afc bournemouth"],
}

# Build reverse lookup: alias_token → canonical_token
_ALIAS_LOOKUP: Dict[str, str] = {}
for _canonical, _variants in _ALIASES.items():
    for _v in _variants:
        _ALIAS_LOOKUP[re.sub(r'[^a-z0-9]', '', _v.lower())] = _canonical
    _ALIAS_LOOKUP[_canonical] = _canonical  # self-map

_FUZZY_THRESHOLD = 0.82


def _strip(name: str) -> str:
    """Lowercase, strip common suffixes and non-alphanumerics."""
    n = name.lower()
    n = re.sub(
        r'\b(fc|cf|sc|ac|utd|united|city|rovers|wanderers|hotspur|'
        r'sporting|athletic|atletico|calcio|club|de|sd|sv|bsc|1903|'
        r'2000|1909|1906|1899)\b',
        '', n
    )
    return re.sub(r'[^a-z0-9]', '', n)


def normalize_team_name(name: str) -> str:
    if not name: return ""
    name = name.lower().strip()
    
    # Remove common suffixes and descriptors
    for suffix in ["fc", "cf", "ud", "afc", "sc", "ssc", "city", "united", "town", "rovers", "wanderers", "youth", "women", "u23", "u21", "u19"]:
        name = re.sub(r"\b" + suffix + r"\b", "", name)
    
    # Strip all non-alphanumeric
    name = re.sub(r"[^a-z0-9]", "", name)
    
    # Alias lookup
    if name in _ALIAS_LOOKUP:
        return _ALIAS_LOOKUP[name]
    
    best_ratio, best_key = 0.0, None
    for canonical in _ALIASES:
        r = SequenceMatcher(None, name, canonical).ratio()
        if r > best_ratio:
            best_ratio, best_key = r, canonical

    if best_ratio >= _FUZZY_THRESHOLD and best_key:
        logger.debug(
            f"[normalizer] fuzzy '{name}' → '{best_key}' (ratio={best_ratio:.2f})"
        )
        return best_key

    return name


def calc_stakes(odds: List[float], bankroll: float) -> List[float]:
    """Calculates proportional stakes to guarantee equal profit across all outcomes."""
    inv_sum = sum(1/o for o in odds)
    return [round((bankroll / o) / inv_sum, 2) for o in odds]


# Prematch odds are stable for much longer than live odds
_PREMATCH_MAX_AGE_SEC = 600  # 10 minutes — prematch odds barely move


def detect_arbs(events: List[Dict]) -> List[Dict]:
    """
    Detects arbitrage opportunities from flattened scraper event data.
    Enforces Hard Filters:
      - Live events with minute > 85 are skipped (odds unreliable)
      - exact line match
      - market_type in VALID_MARKETS
      - Edge >= MIN_EDGE
      - Cross-bookmaker (not same feed)
    Supports both live and prematch events.
    """
    arbs = []

    grouped = {}

    for e in events:
        # Skip late-game live events (>85 min) — odds are unreliable
        if e.get("is_live") and e.get("minute", 0) > 85:
            continue

        market_type = e.get("market_type")
        if market_type not in MARKETS:
            continue

        age = time.time() - e.get("timestamp", 0)
        max_age = MAX_ODDS_AGE_SEC if e.get("is_live") else _PREMATCH_MAX_AGE_SEC
        if age > max_age:
            continue

        home_norm = normalize_team_name(e.get("home", ""))
        away_norm = normalize_team_name(e.get("away", ""))

        teams = sorted([home_norm, away_norm])
        synthetic_event_id = "_".join(teams)
        e["event_id"] = synthetic_event_id
        
        # logger.debug(f"[detector] Processing: {synthetic_event_id} | Line: {e.get('line')} | BM: {e.get('bookmaker')}")

        key = (synthetic_event_id, e.get("line"), market_type)
        sel = e.get("selection", "").lower()
        if sel not in ["over", "under"]:
            continue
            
        if key not in grouped:
            grouped[key] = {"over": [], "under": []}

        grouped[key][sel].append(e)

    for (event_id, line, market_type), selections in grouped.items():
        if not selections["over"] or not selections["under"]:
            continue

        best_over  = max(selections["over"],  key=lambda x: x["odds"])
        best_under = max(selections["under"], key=lambda x: x["odds"])

        # Same-bookmaker guard
        if best_over["bookmaker"] == best_under["bookmaker"]:
            continue

        # Bug #6 fix: same-feed guard (1xbet ↔ melbet are the same engine)
        if _same_feed(best_over["bookmaker"], best_under["bookmaker"]):
            logger.debug(
                f"[detector] Skipping same-feed arb: "
                f"{best_over['bookmaker']} ↔ {best_under['bookmaker']}"
            )
            continue

        inv_sum = (1.0 / best_over["odds"]) + (1.0 / best_under["odds"])
        if inv_sum >= 1.0:
            continue

        margin_pct = (1.0 - inv_sum) * 100.0
        if margin_pct < (MIN_EDGE * 100.0):
            continue

        stakes  = calc_stakes([best_over["odds"], best_under["odds"]], BANKROLL)
        profit  = round((stakes[0] * best_over["odds"]) - BANKROLL, 2)
        detected_at = min(best_over["timestamp"], best_under["timestamp"])

        arbs.append({
            "event_id":       event_id,
            "match":          f"{best_over['home']} vs {best_over['away']}",
            "sport":          "Soccer",           # Bug #4 fix: add sport field
            "market_type":    market_type,
            "line":           line,
            "margin_pct":     round(margin_pct, 2),
            "profit":         profit,
            "bankroll":       BANKROLL,
            "detected_at":    detected_at,
            "age_sec":        round(time.time() - detected_at, 2),
            "bookmaker_count": len({best_over["bookmaker"], best_under["bookmaker"]}),
            "legs": [
                {
                    "outcome":   f"Over {line}",
                    "bookmaker": best_over["bookmaker"],
                    "odds":      best_over["odds"],
                    "stake":     stakes[0],
                    "selection": "over",
                    "minute":    best_over.get("minute", 0),
                },
                {
                    "outcome":   f"Under {line}",
                    "bookmaker": best_under["bookmaker"],
                    "odds":      best_under["odds"],
                    "stake":     stakes[1],
                    "selection": "under",
                    "minute":    best_under.get("minute", 0),
                }
            ],
        })

    return arbs


# Alias to avoid breaking other files
process_events = detect_arbs
