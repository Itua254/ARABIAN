import aiohttp
import time
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from logger import get_logger

logger = get_logger("notifier")


async def send_telegram_alert(arb: dict) -> bool:
    """
    Sends a formatted HTML alert to Telegram for an arbitrage opportunity.
    Called immediately on detection — no rate limiting, no execution gating.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not set. Skipping alert.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # ── Bug #4 fix: use market_type, not the missing 'sport' key ────────
    market_label = {
        "goals_ou":    "⚽ Goals O/U",
        "corners_ou":  "🚩 Corners O/U",
        "goalkicks_ou":"🥅 Goalkicks O/U",
    }.get(arb.get("market_type", ""), "📊 Market")

    # Live vs prematch badge
    is_live = arb.get("legs", [{}])[0].get("minute", 0) > 0 if arb.get("legs") else False
    status_badge = "🔴 LIVE" if is_live else "📅 PRE-MATCH"

    msg  = f"🚨 <b>ARB FOUND — {arb.get('margin_pct', 0):.2f}% Edge</b> 🚨\n\n"
    msg += f"{status_badge} | {market_label} | Line: <b>{arb.get('line', '?')}</b>\n"
    msg += f"🏟 <b>Match:</b> {arb.get('match', 'Unknown')}\n"
    msg += f"💰 <b>Profit:</b> KSH {arb.get('profit', 0)} "
    msg += f"(on KSH {arb.get('bankroll', 0)} bankroll)\n"
    if is_live:
        msg += f"⏱ <b>Match Minute:</b> {arb.get('legs', [{}])[0].get('minute', '?')}\n"
    msg += "\n"

    for leg in arb.get("legs", []):
        bm_name = leg.get('bookmaker', '?').upper()
        leg_url = leg.get('url', '')
        bm_display = f"<a href='{leg_url}'>{bm_name}</a>" if leg_url else bm_name
        
        msg += (
            f"🔹 <b>{leg.get('outcome', '?')}:</b> "
            f"@ <b>{leg.get('odds', '?')}</b> — "
            f"{bm_display} "
            f"(Stake: KSH {leg.get('stake', '?')})\n"
        )

    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       msg,
        "parse_mode": "HTML",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    logger.info(f"✅ Telegram alert sent for {arb.get('event_id')}")
                    return True
                else:
                    text = await resp.text()
                    logger.error(f"Telegram API Error {resp.status}: {text}")
                    return False
    except Exception as e:
        logger.error(f"Telegram exception: {e}")
        return False


async def send_telegram_photo(photo_path: str, caption: str) -> bool:
    """Sends a photo to Telegram with a caption."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not set. Skipping photo alert.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"

    try:
        async with aiohttp.ClientSession() as session:
            with open(photo_path, "rb") as f:
                form = aiohttp.FormData()
                form.add_field("chat_id", TELEGRAM_CHAT_ID)
                form.add_field("caption", caption)
                form.add_field("parse_mode", "HTML")
                form.add_field("photo", f, filename=photo_path)

                async with session.post(url, data=form) as resp:
                    if resp.status == 200:
                        logger.info("Telegram photo sent successfully.")
                        return True
                    else:
                        text = await resp.text()
                        logger.error(f"Telegram API Error {resp.status}: {text}")
                        return False
    except Exception as e:
        logger.error(f"Telegram photo exception: {e}")
        return False


async def send_telegram_text(message: str) -> bool:
    """Sends a plain text message to Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
            }, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                return resp.status == 200
    except Exception:
        return False
