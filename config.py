import os
from dotenv import load_dotenv

load_dotenv()

# ── API ───────────────────────────────────────────────────────
ODDS_API_KEY  = os.getenv("ODDS_API_KEY")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# ── Redis ─────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ── Telegram ──────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ── Arbitrage settings ────────────────────────────────────────
MIN_EDGE         = float(os.getenv("MIN_EDGE", "0.001"))      # default 0.1%, .env overrides
MAX_ODDS_AGE_SEC = int(os.getenv("MAX_ODDS_AGE_SEC", "90"))  # 90s — accounts for scraper cycle latency
BANKROLL         = float(os.getenv("BANKROLL", "1000"))
DRY_RUN          = os.getenv("DRY_RUN", "True").lower() in ("true", "1", "yes")

# ── Safety & Execution Governance ─────────────────────────────
EXECUTION_MODE         = os.getenv("EXECUTION_MODE", "paper")  # paper | limited | full
MAX_DAILY_EXPOSURE     = float(os.getenv("MAX_DAILY_EXPOSURE", "500.0"))
MAX_TRADES_PER_MIN     = int(os.getenv("MAX_TRADES_PER_MIN", "3"))
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "5"))

# ── Execution ─────────────────────────────────────────────────
# Fastest / most reliable first
EXECUTION_ORDER = os.getenv("EXECUTION_ORDER", "1xbet,melbet,betika,mozzartbet").split(",")
MAX_HEDGE_LOSS  = float(os.getenv("MAX_HEDGE_LOSS", "75.0"))  # Hard liability cap

# ── Sports to monitor ─────────────────────────────────────────
SPORTS = os.getenv(
    "SPORTS",
    "soccer_epl,soccer_spain_la_liga,soccer_germany_bundesliga,soccer_italy_serie_a,soccer_uefa_champs_league"
).split(",")

# ── Bookmakers ────────────────────────────────────────────────
TARGET_BOOKMAKERS = os.getenv(
    "TARGET_BOOKMAKERS", "1xbet,melbet,betika,mozzartbet"
).split(",")

# ── Markets ───────────────────────────────────────────────────
MARKETS = [
    "corners_ou",
    "goals_ou",
    "goalkicks_ou",
]

# ── Timing ────────────────────────────────────────────────────
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))    # seconds between cycles
DEDUP_TTL     = int(os.getenv("DEDUP_TTL", "3600"))      # 1 hr dedup window

# ── Session Pool (v5 §5) ──────────────────────────────────────
SESSION_POOL_SIZE = int(os.getenv("SESSION_POOL_SIZE", "3"))  # warm contexts per bookmaker

# ── Betfair Exchange (v5 §18 optional) ───────────────────────
BETFAIR_APP_KEY  = os.getenv("BETFAIR_APP_KEY", "")
BETFAIR_USERNAME = os.getenv("BETFAIR_USERNAME", "")
BETFAIR_PASSWORD = os.getenv("BETFAIR_PASSWORD", "")

# ── Proxy / Stealth (v5 §11) ─────────────────────────────────
# Comma-separated list: "http://user:pass@host:port,http://..."
PROXY_LIST = [p.strip() for p in os.getenv("PROXY_LIST", "").split(",") if p.strip()]

# ── Graceful Degradation (v5 §12) ────────────────────────────
# If per-bookmaker failure rate exceeds this, enter DEGRADED mode
GRACEFUL_DEGRADATION_THRESHOLD = float(os.getenv("GRACEFUL_DEGRADATION_THRESHOLD", "0.40"))

# ── Edge Classifier thresholds ────────────────────────────────
EDGE_STRONG_MIN    = float(os.getenv("EDGE_STRONG_MIN", "0.010"))   # >= 1.0% → STRONG
EDGE_MARGINAL_MIN  = float(os.getenv("EDGE_MARGINAL_MIN", "0.005")) # 0.5–1.0% → MARGINAL
EDGE_MAX_AGE_SEC   = float(os.getenv("EDGE_MAX_AGE_SEC", "1.5"))    # > 1.5s → REJECT
EDGE_MIN_BM_HEALTH = float(os.getenv("EDGE_MIN_BM_HEALTH", "0.60")) # < 0.6 → WEAK
