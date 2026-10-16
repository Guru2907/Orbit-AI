"""
In-process sliding-window rate limiter for /login and /chat.

State lives in this process's memory. That is enough for the current single-process
deployment, but every worker or instance keeps its own counts: with N uvicorn workers
or N instances the effective limit is N times the configured one, and a restart resets
everything. Anything bigger needs a shared store (e.g. Redis) behind the same interface.
"""

import math
import threading
import time
from collections import deque

# Bounds memory if someone sprays many different IPs or emails.
DEFAULT_MAX_KEYS = 10_000


def parse_rate_limit(value, name):
    """Parses "<requests>/<seconds>", e.g. "20/60". Raises with the variable's name on bad input."""
    count, _, seconds = value.partition("/")
    try:
        limit, window = int(count.strip()), int(seconds.strip())
    except ValueError:
        limit = window = 0
    if limit < 1 or window < 1:
        raise RuntimeError(f'{name} must look like "<requests>/<seconds>" with both at least 1, e.g. "20/60"')
    return limit, window


class RateLimiter:
    """Allows at most `limit` hits per key in any `window_seconds`-long window."""

    def __init__(self, limit, window_seconds, clock=time.monotonic, max_keys=DEFAULT_MAX_KEYS):
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self.max_keys = max_keys
        self._hits = {}
        self._lock = threading.Lock()  # sync endpoints run in a thread pool

    def _recent(self, key, now):
        """Drops hits that left the window and returns what remains (None if the key has no hits)."""
        hits = self._hits.get(key)
        if hits is None:
            return None
        while hits and hits[0] <= now - self.window_seconds:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def _retry_after(self, hits, now):
        if hits is None or len(hits) < self.limit:
            return None
        return max(1, math.ceil(hits[0] + self.window_seconds - now))

    def _make_room(self, now):
        for key in list(self._hits):
            self._recent(key, now)
        # Still full: forget the keys that were added earliest. This weakens limits during a
        # key-spraying attack, but keeps memory bounded.
        while len(self._hits) >= self.max_keys:
            del self._hits[next(iter(self._hits))]

    def _add(self, key, hits, now):
        if hits is None:
            if len(self._hits) >= self.max_keys:
                self._make_room(now)
            hits = self._hits[key] = deque()
        hits.append(now)

    def retry_after(self, key):
        """Seconds until `key` may make another request, or None if it may now. Records nothing."""
        with self._lock:
            now = self.clock()
            return self._retry_after(self._recent(key, now), now)

    def record(self, key):
        """Records a hit without checking the limit (used to count failed logins)."""
        with self._lock:
            now = self.clock()
            self._add(key, self._recent(key, now), now)

    def hit(self, key):
        """Checks and records in one step. Returns seconds to wait if limited (nothing is recorded), else None."""
        with self._lock:
            now = self.clock()
            hits = self._recent(key, now)
            wait = self._retry_after(hits, now)
            if wait is None:
                self._add(key, hits, now)
            return wait

    def reset(self):
        with self._lock:
            self._hits.clear()
