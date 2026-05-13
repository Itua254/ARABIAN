import redis
from config import REDIS_URL
from logger import get_logger

logger = get_logger("redis_client")

# Initialize connection pool
try:
    redis_conn = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    redis_conn.ping()
    logger.info("Redis connected successfully.")
except Exception as e:
    logger.error(f"Failed to connect to Redis at {REDIS_URL}: {e}")
    redis_conn = None

def acquire_lock(event_id: str, ttl_sec: int = 60) -> bool:
    """
    Acquires an idempotency lock for the given event ID.
    Returns True if the lock was acquired, False if it was already locked.
    """
    if not redis_conn:
        logger.warning("Redis is not connected. Skipping lock acquisition.")
        return True # Fallback for now if redis is down, though not ideal

    try:
        lock_key = f"arb:{event_id}"
        # setnx with expiration is supported directly in redis-py via `nx=True, ex=ttl`
        acquired = redis_conn.set(lock_key, 1, nx=True, ex=ttl_sec)
        return bool(acquired)
    except Exception as e:
        logger.error({"error": "redis_lock_failed", "event_id": event_id, "details": str(e)})
        return True  # Fail-open: Redis outage must not silently block all arbs
