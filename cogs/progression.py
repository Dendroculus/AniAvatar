import discord
from discord.ext import commands
import asyncpg
import os
import random
import asyncio
import traceback
import io
import hashlib
import time
import concurrent.futures
from typing import Optional, Iterable, Any
from collections import OrderedDict
from discord import MessageReference
import redis.asyncio as redis
from cogs.utils.progUtils import (
    ImageRenderer,
    get_title,
    get_title_emoji,
    TITLE_COLORS,
)
from cogs.utils.constants import BG_PATH, EMOJI_PATH, FONTS, TITLE_EMOJI_FILES
from cogs.trading import format_coins
from cogs.utils.emojis import CustomEmojis, MinoriEmojis, TitleEmojis, ShopEmojis

_PROCESS_CONTEXT: dict[str, Any] = {}

def _initialize_worker_safe(cache_size: int):
    """
    Runs ONCE per ProcessPoolExecutor worker. Initializes and caches the 
    ImageRenderer instance in the process-local _PROCESS_CONTEXT dictionary.
    
    Avoids using the 'global' keyword by leveraging the process-local scope 
    of the top-level dictionary.
    """
    _PROCESS_CONTEXT["renderer"] = ImageRenderer(cache_size=cache_size)
    

"""
progression.py

Purpose:
- Manage user progression (EXP and levels), profile themes, and an on-demand image-based
  profile/leaderboard rendering pipeline.
- Provide coin management APIs used by other cogs (get_coins, add_coins, remove_coins,
  reserve_coins) along with safe persistence in PostgreSQL (asyncpg).

Design notes and important operational guidance:
- Concurrency:
    multiple coroutines (within a single process).
  - Image rendering is offloaded to threads and controlled by a semaphore (`_render_semaphore`)
    to limit concurrency and avoid saturating CPU or memory with large Pillow tasks.
- Caching:
  - Rendered profile images are cached in-memory in `_render_cache` (LRU-like OrderedDict).
    Cache entries have TTL (RENDER_CACHE_TTL) to reduce memory usage and keep visuals fresh.
    Cache keys include a short hash of avatar bytes and textual attributes to avoid accidental
    collisions when images or display names change.
  - Leaderboard images can be cached in Redis by the main bot process to avoid re-rendering.
- Fail-safe behavior:
  - Many operations are defensive: failures in rendering or avatar fetch degrade gracefully
    (returning placeholder data or None), and are logged. This prioritizes bot availability.
- Integration:
  - This cog expects a `Progression` role for awarding coins/exp and integrates with
    other subsystems (e.g., trading.format_coins) for display formatting.
- Notes for maintainers:
  - Avoid heavy synchronous work on the event loop; rendering is already offloaded but any
    additional expensive operations should follow the same pattern (to_thread + timeout).
  - The DB schema creation is idempotent; migrating columns must be performed with care.
  - For multi-instance deployments, rely on DB constraints/transactions rather than in-process
    locks for cross-process safety; the current locks only protect within this process.
"""

PROFILE_PNG = "profile.png"
ATTACHMENT_PROFILE = f"attachment://{PROFILE_PNG}"
SQL_INSERT_OR_IGNORE_USER_COINS_ZERO = (
    "INSERT INTO user_coins (user_id, guild_id, coins) VALUES ($1, $2, 0) ON CONFLICT DO NOTHING"
)
COINS_EMOJI = f"{ShopEmojis['Coins']}"

# Statement timeout (ms) applied per-connection to avoid runaway queries.
DEFAULT_STATEMENT_TIMEOUT_MS = int(os.getenv("PG_STATEMENT_TIMEOUT_MS", "2000"))

def _render_profile_in_process(
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
    Render a profile image in a separate process to bypass the GIL.
    A fresh ImageRenderer is created per worker process to keep state isolated.
    """
    renderer = _PROCESS_CONTEXT["renderer"] # Renderer is guaranteed to exist by the initializer
    
    return renderer.render_profile_image(
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


def _render_leaderboard_in_process(
    rows_data: Iterable[dict[str, Any]],
    exp_icon_path: str,
    cache_key: Optional[str],
    cache_ttl: int,
) -> Optional[bytes]:
    """
    Render a leaderboard image in a separate process. A renderer instance is created
    inside the worker so Pillow runs outside the main event loop, leveraging multiple cores.
    """
    renderer = _PROCESS_CONTEXT["renderer"]
    
    return renderer.create_leaderboard_image(
        rows=list(rows_data),
        fonts=FONTS,
        exp_icon_path=exp_icon_path,
        cache_key=cache_key,
        cache_ttl=cache_ttl,
    )

async def _pool_init(conn: asyncpg.Connection):
    """
    Apply per-connection settings (statement timeout, optional app name).
    Keeps long/blocked queries from piling up.
    """
    try:
        await conn.execute(f"SET statement_timeout TO {DEFAULT_STATEMENT_TIMEOUT_MS}")
        await conn.execute("SET application_name TO 'minori-progression'")
    except Exception:
        # Best-effort; don't block pool init
        pass


class MainThemeSelect(discord.ui.Select):
    """
    Select menu listing top-level theme folders for profile backgrounds.

    Responsibilities:
    - Present available theme folders (derived from BG_PATH) as Select options.
    - Validate that the invoking user owns the selection (protects other users' selections).
    - On selection, transition the interaction to a SubThemeView to pick a specific background.
    """
    def __init__(self, user_id, cog):
        self.user_id = user_id
        self.cog = cog
        self.folders = [folder for folder in os.listdir(BG_PATH) if os.path.isdir(os.path.join(BG_PATH, folder))]
        options = [
            discord.SelectOption(label=folder.capitalize(), description=f"Choose {folder.capitalize()} theme")
            for folder in self.folders
        ]
        super().__init__(placeholder="Select a theme...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⚠️ You can only select a background for yourself.", ephemeral=True)
            return
        idx = self.values[0].lower()
        selected_theme = next(f for f in self.folders if f.lower() == idx)
        self.disabled = True
        for item in self.view.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True
        await interaction.response.edit_message(
            content=f"You have selected **{selected_theme.capitalize()}**! Now pick a background:",
            view=SubThemeView(self.user_id, selected_theme, self.cog)
        )


class MainThemeView(discord.ui.View):
    """
    Wrapper view that adds a MainThemeSelect for a specific user.

    This view is ephemeral per-invocation and used by the profiletheme command.
    """
    def __init__(self, user_id, cog):
        super().__init__()
        self.cog = cog
        self.add_item(MainThemeSelect(user_id, cog))


class SubThemeSelect(discord.ui.Select):
    """
    Select menu showing concrete background image files within a chosen theme folder.

    Behavior:
    - Maps "Theme N" labels to actual filenames and persists the user's theme choice
      via Progression.set_user_theme.
    - Verifies ownership (only the invoking user may confirm a background).
    - After saving, renders and sends an updated profile image preview to the user.
    """
    def __init__(self, user_id, theme, cog):
        self.theme = theme
        self.cog = cog
        theme_path = os.path.join(BG_PATH, theme)

        files = [f for f in os.listdir(theme_path) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
        self.file_map = {f"Theme {i+1}": file for i, file in enumerate(files)}

        options = [
            discord.SelectOption(label=name, description=f"Select {name}")
            for name in self.file_map.keys()
        ]

        super().__init__(placeholder="Select a background...", min_values=1, max_values=1, options=options)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "⚠️ You can only select a background for yourself.", ephemeral=True
            )
            return

        selected_label = self.values[0]
        bg_file = self.file_map[selected_label]
        theme_name = self.theme
        font_color = "white"

        current_theme_name, current_bg_file, current_font_color = await self.cog.get_user_theme(self.user_id)
        if (
            current_theme_name == theme_name
            and (current_bg_file or "").lower() == bg_file.lower()
            and current_font_color == font_color
        ):
            await interaction.response.send_message(
                f"{MinoriEmojis['MinoriSmile']} You already use this profile theme and background.", ephemeral=True
            )
            return

        await self.cog.set_user_theme(self.user_id, theme_name, bg_file, font_color)

        for item in self.view.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True

        embed = discord.Embed(
            title="Your profile card theme has been updated!",
            description=f"Your selection has been saved!\n You have selected `{theme_name.capitalize()} {selected_label}`."
        )
        embed.set_image(url=ATTACHMENT_PROFILE)
        try:
            await interaction.response.edit_message(embed=embed, view=self.view)
        except discord.errors.InteractionResponded:
            await interaction.followup.send(embed=embed)
        await interaction.message.edit(content="")

        member = interaction.user
        exp, level = await self.cog.get_user(member.id, interaction.guild.id)
        title_name = get_title(level)
        next_exp = None if level >= self.cog.MAX_LEVEL else 50 * level + 20 * level**2

        avatar_bytes = await member.display_avatar.with_size(128).read()

        img_bytes = await self.cog._render_profile_cached(
            avatar_bytes,
            member.display_name,
            title_name,
            level,
            exp,
            next_exp,
            bg_file=bg_file,
            theme_name=theme_name,
            font_color=font_color
        )

        if img_bytes:
            file = discord.File(io.BytesIO(img_bytes), filename=PROFILE_PNG)
            await interaction.followup.send(
                content=f"{member.mention}, here's your updated profile! {MinoriEmojis['MinoriSmile']}",
                file=file
            )


class SubThemeView(discord.ui.View):
    """
    Simple wrapper view that holds a SubThemeSelect for the chosen theme.
    """
    def __init__(self, user_id, theme, cog):
        super().__init__()
        self.cog = cog
        self.add_item(SubThemeSelect(user_id, theme, cog))


class Progression(commands.Cog):
    """
    Progression cog: handles levels, EXP, coins, and profile/leaderboard rendering.

    Key features:
    - PostgreSQL-backed storage for users, profile themes, and coins.
    - Profile image rendering using ImageRenderer with a thread-offload and semaphore
      to limit concurrent CPU work.
    - Leaderboard image generation based on top users in a guild.
    - Per-message cooldown for give EXP on activity, to limit spam-based leveling.
    """
    MAX_LEVEL = 999
    MAX_BOX_WIDTH = 50
    MAX_NAME_WIDTH = 20
    MAX_EXP_WIDTH = 12
    RENDER_CACHE_SIZE = 200
    RENDER_CACHE_TTL = 300
    LEADERBOARD_CACHE_TTL = 120 # 2 minutes

    def __init__(self, bot):
        self.bot = bot
        self.pool: asyncpg.Pool | None = None
        self._leaderboard_cache = {}

        cpu_count = os.cpu_count() or 2
        max_renders = max(2, cpu_count - 1)
        self._render_semaphore = asyncio.Semaphore(max_renders)

        self._render_cache: OrderedDict[str, tuple[bytes, float]] = OrderedDict()

        self.redis_url = os.getenv("REDIS_URL")
        self.redis: redis.Redis | None = None
        if self.redis_url:
            try:
                self.redis = redis.from_url(
                    self.redis_url,
                    decode_responses=False,
                    socket_timeout=3,
                    socket_connect_timeout=3,
                )
            except Exception as e:
                print(f"[Progression] Failed to connect to Redis: {e}")
                self.redis = None
        self._fallback_cooldowns: dict[str, float] = {}

        self.renderer = ImageRenderer(cache_size=self.RENDER_CACHE_SIZE)
        
        self._process_pool = concurrent.futures.ProcessPoolExecutor(max_workers=max_renders, initializer=_initialize_worker_safe, initargs=(self.RENDER_CACHE_SIZE,))

        print(f"[Progression] Initialized with max {max_renders} concurrent renders")

    async def _ensure_pool(self):
        if self.pool is None:
            dsn = os.getenv("DATABASE_URL")
            if not dsn:
                raise RuntimeError("DATABASE_URL is not set")
            # command_timeout applies to pool operations; per-connection statement_timeout set in _pool_init.
            self.pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=1,
                max_size=10,
                timeout=5.0,
                command_timeout=5.0,
                init=_pool_init,
            )

    async def _create_indexes(self, conn: asyncpg.Connection):
        """
        Create helpful indexes for hot paths (idempotent).
        """
        try:
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_guild_level_exp ON users (guild_id, level DESC, exp DESC)"
            )
        except Exception as e:
            print(f"[Progression] Index creation warning: {e}")

    async def cog_load(self):
        """
        Initialize persistent database tables when the cog is loaded.

        This method creates users, profile_theme, and user_coins tables if they do not exist.
        It's idempotent and safe to run on every cog reload.
        """
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT,
                    guild_id BIGINT,
                    exp BIGINT NOT NULL DEFAULT 0,
                    level INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS profile_theme (
                    user_id BIGINT PRIMARY KEY,
                    theme_name TEXT DEFAULT 'default',
                    bg_file TEXT DEFAULT 'NULL',
                    font_color TEXT DEFAULT 'white'
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_coins (
                    user_id BIGINT,
                    guild_id BIGINT,
                    coins BIGINT DEFAULT 0,
                    PRIMARY KEY(user_id, guild_id)
                )
            """)
            await self._create_indexes(conn)

    async def cog_unload(self):
        """
        Close the database connection when the cog is unloaded; swallow errors to avoid
        disrupting bot shutdown. Also tear down the process pool to free workers.
        """
        try:
            if self.pool:
                await self.pool.close()
        except Exception:
            pass
        try:
            if self.redis:
                await self.redis.close()
        except Exception:
            pass
        try:
            self._process_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    async def safe_send(self, ctx, *args, **kwargs):
        """
        Send a message using either interaction response/followup semantics or ctx.send.

        This helper centralizes the logic for hybrid commands and reduces duplicated
        try/except blocks in command implementations.
        """
        interaction = getattr(ctx, "interaction", None)
        if interaction is not None:
            try:
                if not interaction.response.is_done():
                    return await interaction.response.send_message(*args, **kwargs)
                return await interaction.followup.send(*args, **kwargs)
            except discord.errors.NotFound:
                return await ctx.channel.send(*args, **kwargs)
            except discord.errors.InteractionResponded:
                return await interaction.followup.send(*args, **kwargs)
        else:
            return await ctx.send(*args, **kwargs)

    async def _fetch_avatar_bytes(self, member_or_user, size=128, timeout=3.0):
        """
        Fetch avatar bytes with a short timeout.

        Returns b"" on failure and logs the error. This protects rendering code from
        indefinite waits when fetching remote avatars.
        """
        try:
            return await asyncio.wait_for(member_or_user.display_avatar.with_size(size).read(), timeout=timeout)
        except Exception as e:
            print(f"[avatar_fetch] failed for {getattr(member_or_user,'id',None)}: {e}")
            return b""

    def _get_render_cache_key(
        self,
        avatar_bytes: bytes,
        display_name: str,
        title_name: str,
        level: int,
        exp: int,
        next_exp: int,
        bg_file: str,
        theme_name: str,
        font_color: str,
        user_rank: Optional[int] = None,
    ) -> str:
        """
        Compute a compact cache key for rendered profile images.

        The key is designed to change when visible attributes do (avatar, name, title, level,
        theme, bg_file, font color, rank). It uses a short SHA1-derived prefix of avatar bytes
        to balance collision risk and key length.
        """
        avatar_hash = hashlib.sha1(avatar_bytes[:256] if avatar_bytes else b"").hexdigest()[:16]
        return f"{avatar_hash}:{display_name}:{title_name}:{level}:{exp}:{next_exp}:{theme_name}:{bg_file}:{font_color}:{user_rank}"

    def _get_from_cache(self, key: str) -> bytes | None:
        """
        Retrieve image bytes from in-memory cache if present and not expired.

        Also moves the key to the end to implement LRU-like behavior.
        """
        if key not in self._render_cache:
            return None

        img_bytes, timestamp = self._render_cache[key]
        now = asyncio.get_event_loop().time()

        if now - timestamp > self.RENDER_CACHE_TTL:
            del self._render_cache[key]
            return None

        self._render_cache.move_to_end(key)
        return img_bytes

    def _add_to_cache(self, key: str, img_bytes: bytes):
        """
        Add a rendered image to cache, evicting oldest entries when the cache exceeds its size.
        """
        now = asyncio.get_event_loop().time()
        self._render_cache[key] = (img_bytes, now)
        self._render_cache.move_to_end(key)

        while len(self._render_cache) > self.RENDER_CACHE_SIZE:
            self._render_cache.popitem(last=False)

    async def _render_profile_cached(
        self,
        avatar_bytes: bytes,
        display_name: str,
        title_name: str,
        level: int,
        exp: int,
        next_exp: int,
        bg_file: Optional[str] = None,
        theme_name: str = "default",
        font_color: str = "white",
        user_rank: int = None,
     ) -> bytes | None:
        """
        Render a profile card into bytes with caching and concurrency control.

        Behavior:
        - Check in-memory cache first.
        - If not cached, acquire a semaphore permit and offload rendering to a process
          via run_in_executor with a 20s timeout (bypassing the GIL).
        - On success, cache the output and return bytes; on failure return None.
        - This keeps the event loop responsive while supporting high-quality Pillow renders.
        """
        cache_key = self._get_render_cache_key(
            avatar_bytes,
            display_name,
            title_name,
            level,
            exp,
            next_exp,
            bg_file,
            theme_name,
            font_color,
            user_rank,
        )
        cached = self._get_from_cache(cache_key)
        if cached:
            print(f"[Progression] Cache hit for {display_name}")
            return cached

        async with self._render_semaphore:
            loop = asyncio.get_running_loop()
            try:
                img_bytes = await asyncio.wait_for(
                    loop.run_in_executor(
                        self._process_pool,
                        _render_profile_in_process,
                        avatar_bytes,
                        display_name,
                        title_name,
                        level,
                        exp,
                        next_exp,
                        bg_file,
                        theme_name,
                        font_color,
                        user_rank,
                    ),
                    timeout=20.0,
                )

                if img_bytes:
                    self._add_to_cache(cache_key, img_bytes)
                    print(f"[Progression] Rendered and cached profile for {display_name}")

                return img_bytes

            except asyncio.TimeoutError:
                print(f"[Progression] Render timeout for {display_name}")
                return None
            except Exception as e:
                print(f"[Progression] Render error for {display_name}: {e}")
                traceback.print_exc()
                return None
            
    async def _build_rows_data(self, ctx, rows, avatar_size=128, avatar_timeout=3.0):
        """
        Build the structured rows used by the leaderboard renderer.

        - rows: list of tuples (user_id, level, exp) as returned by SQL query.
        - The function concurrently fetches display names and avatar bytes for each user
          and returns a list of dicts suitable for create_leaderboard_image.
        - Failures for individual fetches are logged and replaced with placeholders.
        """
        meta = [(idx, user_id, level, exp) for idx, (user_id, level, exp) in enumerate(rows, start=1)]

        async def get_name_and_avatar(user_id: int) -> tuple[str, bytes]:
            member = ctx.guild.get_member(user_id)
            if member:
                name = member.display_name
                return name, await self._fetch_avatar_bytes(member, size=avatar_size, timeout=avatar_timeout)
            try:
                user = await self.bot.fetch_user(user_id)
                name = user.name
                return name, await self._fetch_avatar_bytes(user, size=avatar_size, timeout=avatar_timeout)
            except Exception as e:
                print(f"[avatar_fetch] failed for user {user_id}: {e}")
                return f"User {user_id}", b""

        tasks = [get_name_and_avatar(user_id) for _, user_id, _, _ in meta]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        rows_data = []
        for (idx, user_id, level, exp), res in zip(meta, results):
            if isinstance(res, Exception):
                print(f"[avatar_fetch] task exception for user {user_id}: {res}")
                name, avatar_bytes = f"User {user_id}", b""
            else:
                name, avatar_bytes = res

            next_exp = None if level >= self.MAX_LEVEL else (50 * level + 20 * level**2)
            rows_data.append({
                "rank": idx,
                "avatar_bytes": avatar_bytes or b"",
                "name": self.truncate(name, self.MAX_NAME_WIDTH),
                "level": level,
                "title": get_title(level),
                "exp": exp or 0,
                "next_exp": next_exp
            })

        return rows_data

    async def get_coins(self, user_id: int, guild_id: int) -> int:
        """
        Return the coin balance for a user in a guild, creating the row if missing.

        """
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT coins FROM user_coins WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )
            if not row:
                await conn.execute(
                    "INSERT INTO user_coins (user_id, guild_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    user_id, guild_id
                )
                return 0
            return int(row["coins"])

    async def add_coins(self, user_id: int, guild_id: int, amount: int):
        """
        Add `amount` coins to a user's balance; creates the row if necessary.

        Uses an INSERT OR UPDATE pattern to avoid race conditions 
        """
        if amount == 0:
            return
        amount = int(amount)
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            await conn.execute(SQL_INSERT_OR_IGNORE_USER_COINS_ZERO, user_id, guild_id)
            await conn.execute(
                """
                INSERT INTO user_coins (user_id, guild_id, coins) VALUES ($1, $2, $3)
                ON CONFLICT(user_id, guild_id) DO UPDATE SET coins = user_coins.coins + EXCLUDED.coins
                """,
                user_id, guild_id, amount
            )

    async def ensure_user_row(self, user_id: int, guild_id: int):
        """
        Ensure a user_coins row exists for the given user; useful for test/setup flows.
        """
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            await conn.execute(SQL_INSERT_OR_IGNORE_USER_COINS_ZERO, user_id, guild_id)

    async def remove_coins(self, user_id: int, guild_id: int, amount: int) -> bool:
        """
        Attempt to subtract `amount` coins from the user's balance only if they have enough.

        Returns True on success, False otherwise.
        """
        amount = int(amount)
        if amount <= 0:
            return False
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            await conn.execute(SQL_INSERT_OR_IGNORE_USER_COINS_ZERO, user_id, guild_id)
            result = await conn.execute(
                "UPDATE user_coins SET coins = coins - $1 WHERE user_id = $2 AND guild_id = $3 AND coins >= $1",
                amount, user_id, guild_id
            )
            # result is like "UPDATE 1"
            try:
                updated = int(result.split()[-1])
            except Exception:
                updated = 0
            return updated > 0

    async def reserve_coins(self, user_id: int, guild_id: int, amount: int) -> bool:
        """
        Alias used by gamble flows that currently directly remove_coins as a reservation.

        If reservation semantics need to change (e.g., using a reserved column) update
        this function only to keep callers unaffected.
        """
        return await self.remove_coins(user_id, guild_id, amount)

    async def get_user_theme(self, user_id: int):
        """
        Return the stored profile theme for a user, inserting a default row if missing.

        Returns a tuple (theme_name, bg_file, font_color).
        """
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT theme_name, bg_file, font_color FROM profile_theme WHERE user_id = $1",
                user_id
            )
            if not row:
                await conn.execute(
                    "INSERT INTO profile_theme (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
                    user_id
                )
                return "galaxy", "GALAXY.PNG", "white"
            return (row["theme_name"], row["bg_file"], row["font_color"])

    async def set_user_theme(self, user_id: int, theme_name: str, bg_file: Optional[str], font_color: str = "white"):
        """
        Persist the user's theme selection into profile_theme.
        """
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO profile_theme (user_id, theme_name, bg_file, font_color)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) DO UPDATE
                SET theme_name = EXCLUDED.theme_name,
                    bg_file = EXCLUDED.bg_file,
                    font_color = EXCLUDED.font_color
                """,
                user_id, theme_name, bg_file, font_color
            )

    def truncate(self, text: str, max_len: int):
        """
        Truncate a string to max_len and append ellipsis if truncated.

        Helper used to keep names within image layout constraints.
        """
        return text if len(text) <= max_len else text[:max_len - 3] + "..."

    async def get_user(self, user_id: int, guild_id: int):
        """
        Return (exp, level) for a user, creating a default row if necessary.
        """
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT exp, level FROM users WHERE user_id = $1 AND guild_id = $2",
                user_id, guild_id
            )
            if row is None:
                await conn.execute(
                    "INSERT INTO users (user_id, guild_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    user_id, guild_id
                )
                return 0, 1
            return (row["exp"], row["level"])

    async def add_exp(self, user_id: int, guild_id: int, amount: int):
        """
        Add EXP safely using a short transaction and row-level locking.
        Prevents lost updates when multiple events for the same user run concurrently.
        Returns (new_level, new_exp, leveled_up).
        """
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Lock the row to serialize concurrent updates for this user/guild.
                row = await conn.fetchrow(
                    """
                    SELECT exp, level
                    FROM users
                    WHERE user_id = $1 AND guild_id = $2
                    FOR UPDATE
                    """,
                    user_id, guild_id,
                )

                if row is None:
                    # Insert a default row atomically; repeat the lock read to keep logic unified.
                    await conn.execute(
                        """
                        INSERT INTO users (user_id, guild_id, exp, level)
                        VALUES ($1, $2, 0, 1)
                        ON CONFLICT DO NOTHING
                        """,
                        user_id, guild_id,
                    )
                    # Lock the freshly inserted row (or the existing one if created elsewhere)
                    row = await conn.fetchrow(
                        """
                        SELECT exp, level
                        FROM users
                        WHERE user_id = $1 AND guild_id = $2
                        FOR UPDATE
                        """,
                        user_id, guild_id,
                    )

                exp, level = row["exp"], row["level"]
                new_exp = exp + amount
                leveled_up = False

                while level < self.MAX_LEVEL:
                    next_exp = 50 * level + 20 * level**2
                    if new_exp >= next_exp:
                        new_exp -= next_exp
                        level += 1
                        leveled_up = True
                    else:
                        break

                if level >= self.MAX_LEVEL:
                    level = self.MAX_LEVEL
                    new_exp = 0

                await conn.execute(
                    """
                    UPDATE users
                    SET exp = $1, level = $2
                    WHERE user_id = $3 AND guild_id = $4
                    """,
                    new_exp, level, user_id, guild_id,
                )

                return level, new_exp, leveled_up

    async def get_rank(self, user_id: int, guild_id: int):
        """
        Compute the 1-based rank of a user within a guild ordered by level desc, exp desc.
        """
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) + 1 AS rnk
                FROM users
                WHERE guild_id = $1
                    AND (
                    level > (SELECT level FROM users WHERE user_id = $2 AND guild_id = $1)
                    OR (
                        level = (SELECT level FROM users WHERE user_id = $2 AND guild_id = $1)
                        AND exp > (SELECT exp FROM users WHERE user_id = $2 AND guild_id = $1)
                    )
                    )
                """,
                guild_id, user_id
            )
            return int(row["rnk"]) if row and row["rnk"] is not None else 1

    async def get_rank_for(self, guild_id: int, level: int, exp: int):
        """
        Compute what rank a hypothetical (level, exp) would have inside the guild.
        Useful for announcements comparing old/new ranks on level-up.
        """
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) + 1 AS rnk FROM users WHERE guild_id = $1 AND (level > $2 OR (level = $2 AND exp > $3))",
                guild_id, level, exp
            )
            return int(row["rnk"]) if row and row["rnk"] is not None else 1

    async def announce_level_up(self, guild_id: int, user_id: int, new_level: int, old_level: int, channel: discord.abc.Messageable):
        """
        Announce a user's level-up in a specified channel.

        Sends an embed summarizing the level/title change and grants a small coin reward.
        """
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        member = guild.get_member(user_id)
        if not member:
            return
        old_title = get_title(old_level)
        new_title = get_title(new_level)
        old_emoji = get_title_emoji(old_level)
        new_emoji = get_title_emoji(new_level)
        if new_title != old_title:
            embed_title = f"{member.display_name} {CustomEmojis['UPWARDARROW']} {new_level}    {old_emoji} {CustomEmojis['RIGHTWARDARROW']} {new_emoji}"
            embed_description = (
                f"```Congratulations {member.display_name}! You have reached level {new_level} and ascended to {new_title}. ```\n"
                f"Title: `{new_title}` {new_emoji}"
            )
        else:
            embed_title = f"{member.display_name} {CustomEmojis['UPWARDARROW']} {new_level}"
            embed_description = (
                f"```Congratulations {member.display_name}! You have reached level {new_level}.```\n"
                f"Title: `{new_title}` {new_emoji}"
            )
        embed = discord.Embed(
            title=embed_title,
            description=embed_description,
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        lvlup_msg = await channel.send(embed=embed)
        coins_amount = random.randint(30, 50)
        await self.add_coins(user_id, guild_id, coins_amount)
        await channel.send(
            f"{member.display_name} received {COINS_EMOJI} {coins_amount} coins for leveling up!",
            reference=MessageReference(message_id=lvlup_msg.id, channel_id=lvlup_msg.channel.id, guild_id=lvlup_msg.guild.id)
        )

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """
        Cleanup handler that removes user rows for a guild when the bot is removed from it.

        This keeps the users table compact and avoids retaining stale data for left guilds.
        """
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE guild_id = $1", guild.id)
        print(f"[Progression] Cleaned up DB for guild {guild.id} ({guild.name})")

    @commands.hybrid_command(name="profile", description="Check your level, EXP, and title")
    @commands.guild_only()
    async def profile(self, ctx, member: discord.Member = None):
        """
        Command to display a rendered profile card for a user (or the invoking user).

        The command attempts to render a profile image (with caching) and delivers it
        as a file attachment; when rendering fails a friendly error is shown.
        """
        member = member or ctx.author
        if member.bot:
            await ctx.send(f"{member.display_name} is a bot and cannot have a profile.")
            return

        try:
            if ctx.interaction:
                await ctx.defer()
                
            exp, level = await self.get_user(member.id, ctx.guild.id)
            title_name = get_title(level)
            next_exp = None if level >= self.MAX_LEVEL else (50 * level + 20 * level**2)

            avatar_bytes = await self._fetch_avatar_bytes(member, size=128, timeout=3.0)

            theme_name, bg_file, font_color = await self.get_user_theme(member.id)
            user_rank = await self.get_rank(member.id, ctx.guild.id)

            img_bytes = await self._render_profile_cached(
                avatar_bytes,
                member.display_name,
                title_name,
                level,
                exp,
                next_exp,
                bg_file=bg_file,
                theme_name=theme_name,
                font_color=font_color,
                user_rank=user_rank
            )

            if not img_bytes:
                await ctx.send("❌ Failed to generate profile image — check bot logs.")
                return

            file = discord.File(io.BytesIO(img_bytes), filename=PROFILE_PNG)

            badge_path = TITLE_EMOJI_FILES.get(title_name)
            badge_text = "" if (badge_path and os.path.exists(badge_path)) else get_title_emoji(level)
            content = f"{member.display_name} {badge_text}".strip()

            await self.safe_send(ctx, content=content if badge_text else None, file=file)

        except Exception:
            traceback.print_exc()
            await ctx.send("❌ Unexpected error while generating profile. Check console/logs.")

    @commands.hybrid_command(name="leaderboard", description="Show server rankings leaderboard")
    @commands.guild_only()
    async def leaderboard_image(self, ctx):
        """
        Generate and send a leaderboard image showing the top users in a guild.

        Refactor: Only do DB query, avatar fetch, and rendering when Redis cache misses.
        """
        start = time.perf_counter()

        def lb_log(msg: str):
            print(f"[Leaderboard] {msg}")

        try:
            await ctx.defer()
        except Exception:
            pass

        cache_key = f"lb_cache:{ctx.guild.id}"
        cached_bytes = None

        # 1) Check Redis first
        if self.redis:
            try:
                cached_bytes = await self.redis.get(cache_key)
                lb_log("Cache hit" if cached_bytes else "Cache miss")
            except Exception as e:
                lb_log(f"Cache read failed: {e}")

        # 1a) FAST CACHE EXIT PATH
        if cached_bytes:
            user_rank = await self.get_rank(ctx.author.id, ctx.guild.id)
            user_coins = await self.get_coins(ctx.author.id, ctx.guild.id)
            formatted_coins = format_coins(user_coins)

            # Build a generic embed (no expensive queries)
            file = discord.File(io.BytesIO(cached_bytes), filename="leaderboard.png")
            embed = discord.Embed(
                title=f"{ctx.guild.name}'s Top Rank List {TitleEmojis['CHAMPION']}",
                color=discord.Color.purple(),
                description=(f"**Your Rank**\n"
                             f"You are ranked **#{user_rank}** on this server\n"
                             f"with a total of **{formatted_coins}** {COINS_EMOJI}")
            )
            if ctx.guild.icon:
                embed.set_thumbnail(url=ctx.guild.icon.url)
            embed.set_image(url="attachment://leaderboard.png")

            await self.safe_send(ctx, embed=embed, file=file)
            lb_log(f"FAST CACHE path completed in {time.perf_counter() - start:.3f}s")
            return

        # 2) WORK PATH (only runs on cache miss)
        async def query_rows():
            lb_log(f"Query start (guild={ctx.guild.id})")
            try:
                await self._ensure_pool()
                async with self.pool.acquire() as conn:
                    rows = await conn.fetch(
                        """
                        SELECT user_id, level, exp
                        FROM users
                        WHERE guild_id = $1
                            AND ((exp > 0 AND level >= 1) OR level = $2)
                        ORDER BY level DESC, exp DESC
                        LIMIT 10
                        """,
                        ctx.guild.id, self.MAX_LEVEL
                    )
                    rows_list = [(r["user_id"], r["level"], r["exp"]) for r in rows]
                    lb_log(f"Query done, rows={len(rows_list)}")
                    return rows_list
            except Exception as e:
                lb_log(f"DB query failed: {e}")
                return None

        async def build_rows_data(rows):
            try:
                lb_log(f"Build rows data start (rows={len(rows) if rows else 0})")
                data = await self._build_rows_data(ctx, rows, avatar_size=128, avatar_timeout=3.0)
                lb_log(f"Build rows data done (rows_data={len(data)})")
                return data
            except Exception as e:
                lb_log(f"_build_rows_data failed: {e}\n{traceback.format_exc()}")
                data = []
                for idx, (user_id, level, exp) in enumerate(rows or [], start=1):
                    try:
                        member = ctx.guild.get_member(user_id)
                        if member:
                            name = member.display_name
                            avatar_bytes = await asyncio.wait_for(member.display_avatar.with_size(128).read(), timeout=2.0)
                        else:
                            user = await self.bot.fetch_user(user_id)
                            name = user.name
                            avatar_bytes = await asyncio.wait_for(user.display_avatar.with_size(128).read(), timeout=2.0)
                    except Exception:
                        name, avatar_bytes = f"User {user_id}", b""
                    next_exp = None if level >= self.MAX_LEVEL else (50 * level + 20 * level**2)
                    data.append({
                        "rank": idx,
                        "avatar_bytes": avatar_bytes,
                        "name": self.truncate(name, self.MAX_NAME_WIDTH),
                        "level": level,
                        "title": get_title(level),
                        "exp": exp or 0,
                        "next_exp": next_exp
                    })
                lb_log(f"Build rows data fallback done (rows_data={len(data)})")
                return data

        async def render_image(rows_data):
            lb_log(f"Render start (rows={len(rows_data)})")
            exp_icon_path = os.path.join(EMOJI_PATH, "EXP.png")
            loop = asyncio.get_running_loop()
            cache_key_inner = str(ctx.guild.id)
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(
                        self._process_pool,
                        _render_leaderboard_in_process,
                        rows_data,
                        exp_icon_path,
                        cache_key_inner,
                        self.LEADERBOARD_CACHE_TTL,
                    ),
                    timeout=20.0
                )
            except asyncio.TimeoutError:
                lb_log("Render timed out — retrying")
                try:
                    return await asyncio.wait_for(
                        loop.run_in_executor(
                            self._process_pool,
                            _render_leaderboard_in_process,
                            rows_data,
                            exp_icon_path,
                            cache_key_inner,
                            self.LEADERBOARD_CACHE_TTL,
                        ),
                        timeout=20.0
                    )
                except Exception as e:
                    lb_log(f"Fallback render failed: {e}\n{traceback.format_exc()}")
                    return None
            except Exception as e:
                lb_log(f"Render error: {e}\n{traceback.format_exc()}")
                return None

        rows = await query_rows()
        if rows is None:
            return await self.safe_send(ctx, "Failed to fetch leaderboard data (check logs).")
        if not rows:
            return await self.safe_send(ctx, "No users found in the leaderboard.")

        rows_data = await build_rows_data(rows)
        img_bytes = await render_image(rows_data)
        if not img_bytes:
            return await self.safe_send(ctx, "Failed to generate leaderboard image (check logs).")

        user_rank = await self.get_rank(ctx.author.id, ctx.guild.id)
        user_coins = await self.get_coins(ctx.author.id, ctx.guild.id)
        formatted_coins = format_coins(user_coins)

        embed_color = TITLE_COLORS.get(get_title(rows_data[0]["level"]) if rows_data else "Leaderboard",
                                       discord.Color.purple())
        file = discord.File(io.BytesIO(img_bytes), filename="leaderboard.png")
        embed = discord.Embed(
            title=f"{ctx.guild.name}'s Top Rank List {TitleEmojis['CHAMPION']}",
            color=embed_color,
            description=(f"**Your Rank**\n"
                         f"You are ranked **#{user_rank}** on this server\n"
                         f"with a total of **{formatted_coins}** {COINS_EMOJI}")
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        embed.set_image(url="attachment://leaderboard.png")

        await self.safe_send(ctx, embed=embed, file=file)

        # Fire-and-forget Redis upload (only on miss after sending)
        if self.redis:
            lb_log("Upload to Redis (fire-and-forget)")
            try:
                self.bot.loop.create_task(self.redis.set(cache_key, img_bytes, ex=120))
            except Exception as e:
                lb_log(f"Redis set failed: {e}")

        lb_log(f"Completed command (total {time.perf_counter() - start:.3f}s)\n")
                    
    @commands.hybrid_command(name="profiletheme", description="Choose your profile card background theme")
    @commands.guild_only()
    async def profiletheme(self, ctx):
        """
        Allow users to view and change their profile card theme through an interactive view.

        The command sends a rendered preview of the user's current theme and attaches a
        MainThemeView that starts the selection flow.
        """
        exp, level = await self.get_user(ctx.author.id, ctx.guild.id)
        title_name = get_title(level)
        next_exp = 50 * level + 20 * level**2 if level < self.MAX_LEVEL else None

        avatar_asset = ctx.author.display_avatar.with_size(128)
        buffer_avatar = io.BytesIO()
        await avatar_asset.save(buffer_avatar)
        buffer_avatar.seek(0)
        avatar_bytes = buffer_avatar.getvalue()

        theme_name, bg_file, font_color = await self.get_user_theme(ctx.author.id)

        img_bytes = await self._render_profile_cached(
            avatar_bytes,
            ctx.author.display_name,
            title_name,
            level,
            exp,
            next_exp,
            bg_file=bg_file,
            theme_name=theme_name,
            font_color=font_color
        )

        file = discord.File(io.BytesIO(img_bytes), filename=PROFILE_PNG)

        # NOTE : SAME LOGIC AS IN SubThemeSelect TO GET THE SUB LABEL
        sub_label = "Default"
        try:
            if bg_file and bg_file.lower() != "null":
                theme_path = os.path.join(BG_PATH, theme_name)
                files = [f for f in os.listdir(theme_path)
                         if f.lower().endswith((".png", ".jpg", ".jpeg"))]

                lower_files = [f.lower() for f in files]
                target = os.path.basename(bg_file).lower()

                if target in lower_files:
                    idx = lower_files.index(target)
                    sub_label = f"Theme {idx + 1}"
                else:
                    sub_label = bg_file
        except Exception:
            sub_label = bg_file or "Unknown"

        embed = discord.Embed(
            title="Your current profile theme: ",
            description=(
                f"Main theme: `{theme_name.capitalize()}`\n"
                f"Background: `{sub_label}`\n\n"
                "Below is your current profile card theme. "
                "You can change it by selecting a theme from the dropdown menu."
            )
        )
        embed.set_image(url=ATTACHMENT_PROFILE)

        view = MainThemeView(ctx.author.id, cog=self)
        await ctx.send(embed=embed, file=file, view=view)

    @commands.hybrid_command(name="resetprofiletheme",description="Reset your profile card theme to default")
    @commands.guild_only()
    async def resetprofiletheme(self, ctx):
        """
        Reset a user's stored theme to the default and send a preview of the default profile.
        """
        try:
            await self.set_user_theme(ctx.author.id, "default", None, "white")

            exp, level = await self.get_user(ctx.author.id, ctx.guild.id)
            title_name = get_title(level)
            next_exp = 50 * level + 20 * level**2 if level < self.MAX_LEVEL else None
            avatar_asset = ctx.author.display_avatar.with_size(128)
            buffer_avatar = io.BytesIO()
            await avatar_asset.save(buffer_avatar)
            buffer_avatar.seek(0)
            avatar_bytes = buffer_avatar.getvalue()

            img_bytes = await self._render_profile_cached(
                avatar_bytes,
                ctx.author.display_name,
                title_name,
                level,
                exp,
                next_exp,
                bg_file=None,
                theme_name="default",
                font_color="white"
            )

            file = discord.File(io.BytesIO(img_bytes), filename="profile.png")
            embed = discord.Embed(
                title="Profile Theme Reset",
                description="Your profile card theme has been reset to default."
            )
            embed.set_image(url=ATTACHMENT_PROFILE)

            await ctx.send(embed=embed, file=file)

        except Exception:
            traceback.print_exc()
            await ctx.send("❌ Failed to reset profile theme. Check console/logs.")

    @commands.Cog.listener()
    async def on_message(self, message):
        """
        Grant EXP for user messages with a small per-user/guild cooldown to deter farming.

        On level-up, announce and optionally post rank-up information to the same channel.
        """
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        user_id = message.author.id

        cooldown_key = f"cooldown:{guild_id}:{user_id}"

        # Redis-backed cooldown (sharding-safe). Fallback to in-memory timestamp if Redis is unavailable.
        try:
            if self.redis:
                allowed = await self.redis.set(cooldown_key, b"1", ex=5, nx=True)
                if not allowed:
                    return
            else:
                raise RuntimeError("Redis not configured")
        except Exception as e:
            if isinstance(e, RuntimeError) and str(e) == "Redis not configured":
                pass
            else:
                print(f"[cooldown] Redis check failed: {e}")
            now = discord.utils.utcnow().timestamp()
            last = self._fallback_cooldowns.get(cooldown_key, 0)
            if now - last < 5:
                return
            self._fallback_cooldowns[cooldown_key] = now

        exp, level = await self.get_user(user_id, guild_id)
        old_level = level

        exp_gain = random.randint(5 + level * 8, 10 + level * 12)
        level, new_exp, leveled_up = await self.add_exp(user_id, guild_id, exp_gain)

        if leveled_up:
            await self.announce_level_up(guild_id, user_id, level, old_level, message.channel)
            old_rank = await self.get_rank_for(guild_id, old_level, exp)
            new_rank = await self.get_rank_for(guild_id, level, new_exp)
            if new_rank < old_rank:
                embed = discord.Embed(
                    title=f"{CustomEmojis['UPWARDARROW']} Rank Up! {message.author.display_name}",
                    description=f"```{message.author.display_name} has ranked up to #{new_rank} in the server leaderboard! 🎉```",
                    color=discord.Color.gold()
                )
                embed.set_thumbnail(url=message.author.display_avatar.url)
                await message.channel.send(embed=embed)

    # THIS IS A TESTING LISTENER TO ADD EXP/COINS TO SPECIFIC USERS ON BOT STARTUP TO VERIFY FUNCTIONALITY REMOVE OR COMMENT OUT FOR PRODUCTION USE
    # @commands.Cog.listener()
    # async def on_ready(self):
    #     """
    #     Development helper that seeds EXP/coins for a predefined list of users on startup.
    
    #     NOTE: This block is explicitly intended for testing and should be removed in
    #     production deployments or gated behind configuration.
    #     """
    #     print(f"{self.bot.user} is ready!")
    
    #     YOUR_ID = [
    #         955268891125375036, 550201320074903563, 872679412573802537,
    #         1016489027211378719, 849510586568015923, 905752774497685554,
    #         848525048201478184, 609614026573479936, 736068611017539585,
    #         592632082841337857, 757192501831663627, 489068781705101335,
    #         696014510367965275, 669515429823381505
    #     ]
    
    #     GUILD_ID = 974498807817588756
    
    #     progression = self.bot.get_cog("Progression")
    #     if not progression:
    #         print("Progression cog not loaded!")
    #         return
    
    #     rand_exp = random.randint(1, 10000)
    #     for user_id in YOUR_ID:
    #         level, exp, leveled_up = await self.add_exp(user_id, GUILD_ID, rand_exp)
    #         print(f"User {user_id} → Level {level}, EXP {exp}, Leveled up? {leveled_up}")
    
    #         await progression.add_coins(user_id, GUILD_ID, 100)
    #         coins = await progression.get_coins(user_id, GUILD_ID)
    #         print(f"User {user_id} → Coins: {coins}")
    
    #     first_user = YOUR_ID[0]
    #     print(f"🎉 First user {first_user} now has Level {level}, EXP {exp}, Coins {coins}. Leveled up? {leveled_up}")

async def setup(bot):
    await bot.add_cog(Progression(bot))