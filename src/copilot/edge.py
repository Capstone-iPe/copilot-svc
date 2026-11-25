"""Per-merchant rate limit and policy-search cache on Render Key Value.

REDIS_URL empty means both are off, so local runs and replay stay unchanged.
A store error fails open: the turn proceeds and the search hits the corpus.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from functools import lru_cache

log = logging.getLogger("copilot")


@lru_cache(maxsize=1)
def _client():
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return None
    import redis

    return redis.Redis.from_url(url, decode_responses=True, socket_timeout=1, socket_connect_timeout=1)


def allow(merchant_id: str, *, client=None, limit: int | None = None) -> bool:
    """True when this merchant may send another message or file in the current minute."""
    store = _client() if client is None else client
    if store is None:
        return True
    cap = limit if limit is not None else int(os.getenv("COPILOT_RATE_LIMIT", "30"))
    key = f"rl:{merchant_id}:{datetime.now(UTC).strftime('%Y%m%d%H%M')}"
    try:
        count = int(store.incr(key))
        if count == 1:
            store.expire(key, 90)
        return count <= cap
    except Exception:
        log.warning("rate limit store unavailable")
        return True


def cached_search(query: str, k: int, fetch, *, client=None, ttl: int | None = None):
    """Return corpus hits, reusing a recent identical search when the store is up."""
    store = _client() if client is None else client
    key = "search:" + hashlib.sha256(f"{k}\n{query.strip().casefold()}".encode()).hexdigest()
    if store is not None:
        try:
            raw = store.get(key)
            if raw:
                hits = json.loads(raw)
                if isinstance(hits, list):
                    return hits
        except Exception:
            log.warning("search cache read failed")
    hits = fetch(query, k)
    if store is not None and isinstance(hits, list) and hits:
        try:
            seconds = ttl if ttl is not None else int(os.getenv("COPILOT_SEARCH_CACHE_TTL", "300"))
            store.set(key, json.dumps(hits), ex=seconds)
        except Exception:
            log.warning("search cache write failed")
    return hits


class CachedCorpus:
    """Remote corpus whose search results can be reused for a few minutes."""

    def __init__(self, inner) -> None:
        self.inner = inner

    def search(self, query: str, k: int = 4) -> list[dict]:
        return cached_search(query, k, self.inner.search)

    def __getattr__(self, name: str):
        return getattr(self.inner, name)
