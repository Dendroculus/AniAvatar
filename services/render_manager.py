import hashlib
import concurrent.futures
import asyncio
import os
import traceback
from dataclasses import dataclass
from collections import OrderedDict
from typing import Optional

from utils.progression.process_worker import (
    initialize_worker_safe,
    render_profile_in_process,
    render_leaderboard_in_process,
)

from constants.configs import ProgressionConstants as PC

@dataclass
class RenderContext:
    """Data object encapsulating all necessary fields for profile rendering."""
    avatar_bytes: bytes
    display_name: str
    title_name: str
    level: int
    exp: int
    next_exp: Optional[int]
    bg_file: Optional[str]
    theme_name: str
    font_color: str
    user_rank: Optional[int] = None
    
class RenderManager:
    """
    Service responsible for managing the process pool, caching, and 
    delegating image generation tasks.
    """
    def __init__(self):
        cpu_count = os.cpu_count() or 2
        max_renders = max(2, cpu_count - 1)
        self._render_semaphore = asyncio.Semaphore(max_renders)
        self._render_cache: OrderedDict[str, tuple[bytes, float]] = OrderedDict()
        
        self._process_pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=max_renders, 
            initializer=initialize_worker_safe, 
            initargs=(PC.RENDER_CACHE_SIZE,)
        )
        print(f"[RenderManager] Initialized with max {max_renders} concurrent renders")

    def shutdown(self):
        """Shut down the process pool."""
        try:
            self._process_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    def _get_cache_key(self, ctx: RenderContext) -> str:
        """Generate a unique cache key based on the render context."""
        avatar_hash = hashlib.sha1(ctx.avatar_bytes[:256] if ctx.avatar_bytes else b"").hexdigest()[:16]
        return f"{avatar_hash}:{ctx.display_name}:{ctx.title_name}:{ctx.level}:{ctx.exp}:{ctx.next_exp}:{ctx.theme_name}:{ctx.bg_file}:{ctx.font_color}:{ctx.user_rank}"

    def _get_from_cache(self, key: str) -> Optional[bytes]:
        """Retrieve from LRU cache."""
        if key not in self._render_cache:
            return None

        img_bytes, timestamp = self._render_cache[key]
        now = asyncio.get_event_loop().time()

        if now - timestamp > PC.RENDER_CACHE_TTL:
            del self._render_cache[key]
            return None

        self._render_cache.move_to_end(key)
        return img_bytes

    def _add_to_cache(self, key: str, img_bytes: bytes):
        """Add to LRU cache."""
        now = asyncio.get_event_loop().time()
        self._render_cache[key] = (img_bytes, now)
        self._render_cache.move_to_end(key)

        while len(self._render_cache) > PC.RENDER_CACHE_SIZE:
            self._render_cache.popitem(last=False)

    async def render_profile(self, ctx: RenderContext) -> Optional[bytes]:
        """
        Render a profile image using the process pool with caching.
        """
        cache_key = self._get_cache_key(ctx)
        cached = self._get_from_cache(cache_key)
        if cached:
            print(f"[RenderManager] Cache hit for {ctx.display_name}")
            return cached

        async with self._render_semaphore:
            loop = asyncio.get_running_loop()
            try:
                img_bytes = await asyncio.wait_for(
                    loop.run_in_executor(
                        self._process_pool,
                        render_profile_in_process,
                        ctx.avatar_bytes,
                        ctx.display_name,
                        ctx.title_name,
                        ctx.level,
                        ctx.exp,
                        ctx.next_exp,
                        ctx.bg_file,
                        ctx.theme_name,
                        ctx.font_color,
                        ctx.user_rank,
                    ),
                    timeout=20.0,
                )

                if img_bytes:
                    self._add_to_cache(cache_key, img_bytes)
                    print(f"[RenderManager] Rendered and cached profile for {ctx.display_name}")

                return img_bytes

            except asyncio.TimeoutError:
                print(f"[RenderManager] Render timeout for {ctx.display_name}")
                return None
            except Exception as e:
                print(f"[RenderManager] Render error for {ctx.display_name}: {e}")
                traceback.print_exc()
                return None
    
    async def render_leaderboard(self, rows_data: list, exp_icon_path: str, cache_key: str) -> Optional[bytes]:
        """Delegate leaderboard rendering to the process pool."""
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(
                    self._process_pool,
                    render_leaderboard_in_process,
                    rows_data,
                    exp_icon_path,
                    cache_key,
                    PC.LEADERBOARD_CACHE_TTL,
                ),
                timeout=20.0
            )
        except asyncio.TimeoutError:
            print("[RenderManager] Leaderboard render timeout")
            return None
        except Exception as e:
            print(f"[RenderManager] Leaderboard render error: {e}")
            return None