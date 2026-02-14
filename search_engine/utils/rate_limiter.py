import asyncio
import time

class TokenBucketRateLimiter:
    """
    Implements the Token Bucket algorithm for rate limiting.
    Safe for use in asyncio contexts.
    """
    def __init__(self, rate: float, burst: int):
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """
        Wait until a token is available, then consume it.
        """
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_update
                self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
                self._last_update = now
                
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                
                wait_time = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait_time)