"""
services/memory_service.py

Stores conversation history per session.
  - Production:  Redis (USE_REDIS=true in .env)
  - Development: in-memory dict (resets on restart)

History format:
  [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
"""

import json
import asyncio
from typing import Optional
from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

# In-memory fallback store
_mem_store: dict[str, list[dict]] = {}

try:
    if settings.USE_REDIS:
        import redis.asyncio as aioredis
        _redis: Optional[aioredis.Redis] = None
    else:
        _redis = None
except ImportError:
    _redis = None
    logger.warning("redis not installed — using in-memory memory")


async def _get_redis():
    global _redis
    if _redis is None and settings.USE_REDIS:
        import redis.asyncio as aioredis
        _redis = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


class MemoryService:
    """Per-session conversation history manager."""

    KEY_PREFIX = "airi:mem:"
    TTL = 3600  # 1 hour session expiry

    async def get_history(self, session_id: str) -> list[dict]:
        if not session_id:
            return []
        try:
            r = await _get_redis()
            if r:
                raw = await r.get(f"{self.KEY_PREFIX}{session_id}")
                return json.loads(raw) if raw else []
            else:
                return list(_mem_store.get(session_id, []))
        except Exception as e:
            logger.error(f"Memory read error: {e}")
            return []

    async def append(self, session_id: str, user_text: str, assistant_json: str) -> None:
        if not session_id:
            return
        try:
            history = await self.get_history(session_id)
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": assistant_json})

            # Trim to max turns
            max_items = settings.MEMORY_MAX_TURNS * 2
            history = history[-max_items:]

            r = await _get_redis()
            if r:
                await r.set(f"{self.KEY_PREFIX}{session_id}", json.dumps(history), ex=self.TTL)
            else:
                _mem_store[session_id] = history

        except Exception as e:
            logger.error(f"Memory write error: {e}")

    async def clear(self, session_id: str) -> None:
        try:
            r = await _get_redis()
            if r:
                await r.delete(f"{self.KEY_PREFIX}{session_id}")
            else:
                _mem_store.pop(session_id, None)
        except Exception as e:
            logger.error(f"Memory clear error: {e}")


# Singleton
memory_service = MemoryService()
