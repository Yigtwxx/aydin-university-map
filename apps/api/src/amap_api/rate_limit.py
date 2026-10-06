"""Per-client token bucket (in memory, per instance; best effort on serverless)."""

import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class TokenBucket:
    capacity: float
    refill_per_s: float
    _tokens: dict[str, tuple[float, float]] = field(default_factory=dict)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        tokens, last = self._tokens.get(key, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.refill_per_s)
        if tokens < 1.0:
            self._tokens[key] = (tokens, now)
            return False
        self._tokens[key] = (tokens - 1.0, now)
        if len(self._tokens) > 10_000:  # forget idle clients
            self._tokens.clear()
        return True
