import asyncpg
from typing import Any, Optional, Iterable
from utils.progression.profile_cards import ImageRenderer
from constants.configs import FONTS, TITLE_EMOJI_FILES, ProgressionConstants as PC

# Module-level global to hold the renderer instance within the worker process.
# This replaces the dictionary context to ensure explicit state handling
# compatible with 'spawn' multiprocessing contexts.
_renderer: Optional[ImageRenderer] = None

def initialize_worker_safe(cache_size: int):
    """
    Runs ONCE per ProcessPoolExecutor worker via the initializer argument.
    Initializes the global ImageRenderer instance for this process.
    """
    global _renderer
    _renderer = ImageRenderer(cache_size=cache_size)
    
def render_profile_in_process(
    avatar_bytes: bytes,
    display_name: str,
    title_name: str,
    level: int,
    exp: int,
    next_exp: int,
    bg_file: Optional[str],
    theme_name: str,
    font_color: str,
    user_rank: Optional[int],
) -> Optional[bytes]:
    """
    Render a profile image in a separate process.
    Uses the pre-initialized global renderer to avoid pickling the renderer instance.
    """
    if _renderer is None:
        raise RuntimeError("Worker process not initialized with ImageRenderer.")

    return _renderer.render_profile_image(
        avatar_bytes,
        display_name,
        title_name,
        level,
        exp,
        next_exp,
        FONTS,
        TITLE_EMOJI_FILES,
        bg_file=bg_file,
        theme_name=theme_name,
        font_color=font_color,
        user_rank=user_rank,
    )


def render_leaderboard_in_process(
    rows_data: Iterable[dict[str, Any]],
    exp_icon_path: str,
    cache_key: Optional[str],
    cache_ttl: int,
) -> Optional[bytes]:
    """
    Render a leaderboard image in a separate process using the global renderer.
    """
    if _renderer is None:
        raise RuntimeError("Worker process not initialized with ImageRenderer.")

    return _renderer.create_leaderboard_image(
        rows=list(rows_data),
        fonts=FONTS,
        exp_icon_path=exp_icon_path,
        cache_key=cache_key,
        cache_ttl=cache_ttl,
    )

async def pool_init(conn: asyncpg.Connection):
    """
    Apply per-connection settings (statement timeout, optional app name).
    Keeps long/blocked queries from piling up.
    """
    try:
        await conn.execute(f"SET statement_timeout TO {PC.DEFAULT_STATEMENT_TIMEOUT_MS}")
        await conn.execute("SET application_name TO 'minori-progression'")
    except Exception:
        # Best-effort; don't block pool init
        pass