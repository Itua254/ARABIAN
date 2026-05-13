import logging
import sys
import json
import time
from typing import Any, Dict

# Path for the structured event log (JSON Lines)
EVENTS_LOG_PATH = "events.jsonl"

# Module-level file handle for event log — opened once, appended to
_events_fh = None


def _get_events_fh():
    global _events_fh
    if _events_fh is None:
        _events_fh = open(EVENTS_LOG_PATH, "a", encoding="utf-8", buffering=1)
    return _events_fh


def log_event(event_type: str, data: Dict[str, Any]) -> None:
    """
    Writes a structured event entry to events.jsonl. v5 §8.2.
    Format: {"ts": <unix>, "type": "<event_type>", "data": {...}}
    """
    record = {
        "ts":   round(time.time(), 4),
        "type": event_type,
        "data": data,
    }
    try:
        _get_events_fh().write(json.dumps(record) + "\n")
    except Exception:
        pass  # Never let observability break the trading loop


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console — INFO and above
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # File — DEBUG and above
    file_h = logging.FileHandler("arb_bot.log", encoding="utf-8")
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(fmt)
    logger.addHandler(file_h)

    return logger
