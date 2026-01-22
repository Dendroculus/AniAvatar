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
from typing import Optional
from collections import OrderedDict
from discord import MessageReference
import redis.asyncio as redis

from utils.progression.profileCards import (
    ImageRenderer,
    get_title,
    get_title_emoji,
    TITLE_COLORS,
)
from utils.progression.profileTheme import MainThemeView
from constants.configs import (
    BG_PATH,
    EMOJI_PATH,
    TITLE_EMOJI_FILES,
    REDIS_CACHING,
    ProgressionConstants as PC,
)
from utils.progression.processWorker import (
    initialize_worker_safe,
    render_profile_in_process,
    render_leaderboard_in_process,
)
from utils.tradingUI import format_coins
from constants.emojis import CustomEmojis, TitleEmojis

"""
progression.py

Handles the leveling system, experience tracking, economy (coins), and
image generation for user profiles and leaderboards.
"""

class Progression(commands.Cog):
    """
    Manages user progression, economy, and profile rendering.

    This cog relies on the shared database pool (bot.pool) for persistence and 
    uses a ProcessPoolExecutor to handle CPU-intensive image generation.
    """

    def __init__(self, bot):
        self.bot = bot
        self._leaderboard_cache = {}

        cpu_count = os.cpu_count() or 2
        max_renders = max(2, cpu_count - 1)
        self._render_semaphore = asyncio.Semaphore(max_renders)

        self._render_cache: OrderedDict[str, tuple[bytes, float]] = OrderedDict()

        self.redis_url = REDIS_CACHING
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
        self.renderer = ImageRenderer(cache_size=PC.RENDER_CACHE_SIZE)
        
        self._process_pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=max_renders, 
            initializer=initialize_worker_safe, 
            initargs=(PC.RENDER_CACHE_SIZE,)
        )

        print(f"[Progression] Initialized with max {max_renders} concurrent renders")

    async def _create_indexes(self, conn: asyncpg.Connection):
        """Create database indexes to optimize leaderboard and user lookups."""
        try:
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_guild_level_exp ON users (guild_id, level DESC, exp DESC)"
            )
        except Exception as e:
            print(f"[Progression] Index creation warning: {e}")

    async def cog_load(self):
        """Initialize database tables and indexes using the bot's shared pool."""
        if not self.bot.pool:
            raise RuntimeError("Bot database pool is not initialized.")

        async with self.bot.pool.acquire() as conn:
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
        """Clean up resources including the process pool and Redis connection."""
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
        Send a message safely handling both Context and Interaction objects.

        Args:
            ctx: The command context.
            *args: Positional arguments for sending.
            **kwargs: Keyword arguments for sending.

        Returns:
            discord.Message: The message sent.
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

    async def _fetch_avatar_bytes(self, member_or_user, size=128, timeout=3.0) -> bytes:
        """
        Fetch the user's avatar as bytes.

        Args:
            member_or_user: The discord Member or User object.
            size (int): The requested avatar size.
            timeout (float): Max time to wait for the download.

        Returns:
            bytes: The image data, or empty bytes on failure.
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
        """Generate a unique cache key for a profile image based on its visual attributes."""
        avatar_hash = hashlib.sha1(avatar_bytes[:256] if avatar_bytes else b"").hexdigest()[:16]
        return f"{avatar_hash}:{display_name}:{title_name}:{level}:{exp}:{next_exp}:{theme_name}:{bg_file}:{font_color}:{user_rank}"

    def _get_from_cache(self, key: str) -> bytes | None:
        """Retrieve an image from the LRU cache if it exists and hasn't expired."""
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
        """Add an image to the LRU cache, evicting old entries if full."""
        now = asyncio.get_event_loop().time()
        self._render_cache[key] = (img_bytes, now)
        self._render_cache.move_to_end(key)

        while len(self._render_cache) > PC.RENDER_CACHE_SIZE:
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
        Render a profile image using a process pool, with caching.

        Args:
            avatar_bytes: The user's avatar image data.
            display_name: The user's name.
            title_name: The user's rank title.
            level: Current level.
            exp: Current experience.
            next_exp: Experience required for next level.
            bg_file: Filename of the background image.
            theme_name: Name of the theme folder.
            font_color: Color of the text.
            user_rank: The user's rank on the leaderboard.

        Returns:
            bytes | None: The rendered PNG data, or None on failure.
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
                        render_profile_in_process,
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
        Prepare data structures for leaderboard rendering by fetching names and avatars.

        Args:
            ctx: Command context.
            rows: List of user database rows (user_id, level, exp).
            avatar_size: Size of avatar to fetch.
            avatar_timeout: Timeout for avatar fetching.

        Returns:
            list[dict]: A list of user data dictionaries ready for the renderer.
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

            next_exp = None if level >= PC.MAX_LEVEL else (50 * level + 20 * level**2)
            rows_data.append({
                "rank": idx,
                "avatar_bytes": avatar_bytes or b"",
                "name": self.truncate(name, PC.MAX_NAME_WIDTH, ellipsis="...", strip=False),
                "level": level,
                "title": get_title(level),
                "exp": exp or 0,
                "next_exp": next_exp
            })

        return rows_data

    async def get_coins(self, user_id: int, guild_id: int) -> int:
        """
        Get the coin balance for a user.

        Returns:
            int: Current coin balance.
        """
        async with self.bot.pool.acquire() as conn:
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
        """Add coins to a user's balance."""
        if amount == 0:
            return
        amount = int(amount)
        async with self.bot.pool.acquire() as conn:
            await conn.execute(PC.SQL_INSERT_OR_IGNORE_USER_COINS_ZERO, user_id, guild_id)
            await conn.execute(
                """
                INSERT INTO user_coins (user_id, guild_id, coins) VALUES ($1, $2, $3)
                ON CONFLICT(user_id, guild_id) DO UPDATE SET coins = user_coins.coins + EXCLUDED.coins
                """,
                user_id, guild_id, amount
            )

    async def ensure_user_row(self, user_id: int, guild_id: int):
        """Ensure a user exists in the coin database."""
        async with self.bot.pool.acquire() as conn:
            await conn.execute(PC.SQL_INSERT_OR_IGNORE_USER_COINS_ZERO, user_id, guild_id)

    async def remove_coins(self, user_id: int, guild_id: int, amount: int) -> bool:
        """
        Remove coins from a user's balance safely.

        Returns:
            bool: True if coins were successfully removed, False if insufficient balance.
        """
        amount = int(amount)
        if amount <= 0:
            return False
        async with self.bot.pool.acquire() as conn:
            await conn.execute(PC.SQL_INSERT_OR_IGNORE_USER_COINS_ZERO, user_id, guild_id)
            result = await conn.execute(
                "UPDATE user_coins SET coins = coins - $1 WHERE user_id = $2 AND guild_id = $3 AND coins >= $1",
                amount, user_id, guild_id
            )
            try:
                updated = int(result.split()[-1])
            except Exception:
                updated = 0
            return updated > 0

    async def reserve_coins(self, user_id: int, guild_id: int, amount: int) -> bool:
        """Reserve coins (currently an alias for remove_coins)."""
        return await self.remove_coins(user_id, guild_id, amount)

    async def get_user_theme(self, user_id: int):
        """
        Get the user's profile theme configuration.

        Returns:
            tuple: (theme_name, bg_file, font_color)
        """
        async with self.bot.pool.acquire() as conn:
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
        """Update the user's profile theme configuration."""
        async with self.bot.pool.acquire() as conn:
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

    def truncate(self, text: str, max_len: int, ellipsis: str = "...", strip: bool = False) -> str:
        """Truncate a string to a maximum length."""
        if len(text) <= max_len:
            return text
        truncated = text[:max_len - len(ellipsis)]
        if strip:
            truncated = truncated.rstrip()
        return truncated + ellipsis

    async def get_user(self, user_id: int, guild_id: int):
        """
        Get user experience and level.

        Returns:
            tuple: (exp, level)
        """
        async with self.bot.pool.acquire() as conn:
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
        Add experience points to a user and handle leveling up.

        Returns:
            tuple: (new_level, new_exp, leveled_up_bool)
        """
        async with self.bot.pool.acquire() as conn:
            async with conn.transaction():
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
                    await conn.execute(
                        """
                        INSERT INTO users (user_id, guild_id, exp, level)
                        VALUES ($1, $2, 0, 1)
                        ON CONFLICT DO NOTHING
                        """,
                        user_id, guild_id,
                    )
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

                while level < PC.MAX_LEVEL:
                    next_exp = 50 * level + 20 * level**2
                    if new_exp >= next_exp:
                        new_exp -= next_exp
                        level += 1
                        leveled_up = True
                    else:
                        break

                if level >= PC.MAX_LEVEL:
                    level = PC.MAX_LEVEL
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
        """Get the user's rank position in the guild."""
        async with self.bot.pool.acquire() as conn:
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
        """Calculate the rank for a hypothetical level and experience value."""
        async with self.bot.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) + 1 AS rnk FROM users WHERE guild_id = $1 AND (level > $2 OR (level = $2 AND exp > $3))",
                guild_id, level, exp
            )
            return int(row["rnk"]) if row and row["rnk"] is not None else 1

    async def announce_level_up(self, guild_id: int, user_id: int, new_level: int, old_level: int, channel: discord.abc.Messageable):
        """Send a level-up announcement and award bonus coins."""
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
            f"{member.display_name} received {PC.COINS_EMOJI()} {coins_amount} coins for leveling up!",
            reference=MessageReference(message_id=lvlup_msg.id, channel_id=lvlup_msg.channel.id, guild_id=lvlup_msg.guild.id)
        )

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """Remove all user data for a guild when the bot leaves it."""
        async with self.bot.pool.acquire() as conn:
            await conn.execute("DELETE FROM users WHERE guild_id = $1", guild.id)
        print(f"[Progression] Cleaned up DB for guild {guild.id} ({guild.name})")

    def _check_badge_exists_safe(self, path: str) -> bool:
        """Thread-safe helper to check if a badge file exists."""
        return bool(path and os.path.exists(path))

    @commands.hybrid_command(name="profile", description="Check your level, EXP, and title")
    @commands.guild_only()
    async def profile(self, ctx, member: discord.Member = None):
        """
        Display a rendered profile card for the user.

        Args:
            member (discord.Member, optional): The user to view. Defaults to author.
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
            next_exp = None if level >= PC.MAX_LEVEL else (50 * level + 20 * level**2)

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

            file = discord.File(io.BytesIO(img_bytes), filename=PC.PROFILE_PNG)

            badge_path = TITLE_EMOJI_FILES.get(title_name)
            
            # Offload file check to thread
            badge_exists = await asyncio.to_thread(self._check_badge_exists_safe, badge_path)
            
            badge_text = "" if badge_exists else get_title_emoji(level)
            content = f"{member.display_name} {badge_text}".strip()

            await self.safe_send(ctx, content=content if badge_text else None, file=file)

        except Exception:
            traceback.print_exc()
            await ctx.send("❌ Unexpected error while generating profile. Check console/logs.")

    @commands.hybrid_command(name="leaderboard", description="Show server rankings leaderboard")
    @commands.guild_only()
    async def leaderboard_image(self, ctx):
        """Generate and display the server leaderboard."""
        start = time.perf_counter()

        def lb_log(msg: str):
            print(f"[Leaderboard] {msg}")

        try:
            await ctx.defer()
        except Exception:
            pass

        cache_key = f"lb_cache:{ctx.guild.id}"
        cached_bytes = None

        if self.redis:
            try:
                cached_bytes = await self.redis.get(cache_key)
                lb_log("Cache hit" if cached_bytes else "Cache miss")
            except Exception as e:
                lb_log(f"Cache read failed: {e}")

        if cached_bytes:
            user_rank = await self.get_rank(ctx.author.id, ctx.guild.id)
            user_coins = await self.get_coins(ctx.author.id, ctx.guild.id)
            formatted_coins = format_coins(user_coins)

            file = discord.File(io.BytesIO(cached_bytes), filename="leaderboard.png")
            embed = discord.Embed(
                title=f"{ctx.guild.name}'s Top Rank List {TitleEmojis['CHAMPION']}",
                color=discord.Color.purple(),
                description=(f"**Your Rank**\n"
                             f"You are ranked **#{user_rank}** on this server\n"
                             f"with a total of **{formatted_coins}** {PC.COINS_EMOJI()}")
            )
            if ctx.guild.icon:
                embed.set_thumbnail(url=ctx.guild.icon.url)
            embed.set_image(url="attachment://leaderboard.png")

            await self.safe_send(ctx, embed=embed, file=file)
            lb_log(f"FAST CACHE path completed in {time.perf_counter() - start:.3f}s")
            return

        async def query_rows():
            lb_log(f"Query start (guild={ctx.guild.id})")
            try:
                async with self.bot.pool.acquire() as conn:
                    rows = await conn.fetch(
                        """
                        SELECT user_id, level, exp
                        FROM users
                        WHERE guild_id = $1
                            AND ((exp > 0 AND level >= 1) OR level = $2)
                        ORDER BY level DESC, exp DESC
                        LIMIT 10
                        """,
                        ctx.guild.id, PC.MAX_LEVEL
                    )
                    rows_list = [(r["user_id"], r["level"], r["exp"]) for r in rows]
                    lb_log(f"Query done, rows={len(rows_list)}")
                    return rows_list
            except Exception as e:
                lb_log(f"DB query failed: {e}")
                return None

        async def render_image(rows_data):
            lb_log(f"Render start (rows={len(rows_data)})")
            exp_icon_path = os.path.join(EMOJI_PATH, "EXP.png")
            loop = asyncio.get_running_loop()
            cache_key_inner = str(ctx.guild.id)
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(
                        self._process_pool,
                        render_leaderboard_in_process,
                        rows_data,
                        exp_icon_path,
                        cache_key_inner,
                        PC.LEADERBOARD_CACHE_TTL,
                    ),
                    timeout=20.0
                )
            except asyncio.TimeoutError:
                lb_log("Render timed out — retrying")
                try:
                    return await asyncio.wait_for(
                        loop.run_in_executor(
                            self._process_pool,
                            render_leaderboard_in_process,
                            rows_data,
                            exp_icon_path,
                            cache_key_inner,
                            PC.LEADERBOARD_CACHE_TTL,
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

        rows_data = await self._build_rows_data(ctx, rows)
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
                         f"with a total of **{formatted_coins}** {PC.COINS_EMOJI()}")
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        embed.set_image(url="attachment://leaderboard.png")

        await self.safe_send(ctx, embed=embed, file=file)

        if self.redis:
            lb_log("Upload to Redis (fire-and-forget)")
            try:
                self.bot.loop.create_task(self.redis.set(cache_key, img_bytes, ex=120))
            except Exception as e:
                lb_log(f"Redis set failed: {e}")

        lb_log(f"Completed command (total {time.perf_counter() - start:.3f}s)\n")
    
    def _get_theme_sub_label_safe(self, bg_file: str, theme_name: str) -> str:
        """Thread-safe helper to list directory files and determine theme label."""
        try:
            if bg_file and bg_file.lower() != "null":
                theme_path = os.path.join(BG_PATH, theme_name)
                files = [f for f in os.listdir(theme_path)
                         if f.lower().endswith((".png", ".jpg", ".jpeg"))]

                lower_files = [f.lower() for f in files]
                target = os.path.basename(bg_file).lower()

                if target in lower_files:
                    idx = lower_files.index(target)
                    return f"Theme {idx + 1}"
                else:
                    return bg_file
            return bg_file or "Unknown"
        except Exception:
            return bg_file or "Unknown"

    @commands.hybrid_command(name="profiletheme", description="Choose your profile card background theme")
    @commands.guild_only()
    async def profiletheme(self, ctx):
        """Interactive command to change profile theme."""
        exp, level = await self.get_user(ctx.author.id, ctx.guild.id)
        title_name = get_title(level)
        next_exp = 50 * level + 20 * level**2 if level < PC.MAX_LEVEL else None

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

        file = discord.File(io.BytesIO(img_bytes), filename=PC.PROFILE_PNG)

        sub_label = await asyncio.to_thread(self._get_theme_sub_label_safe, bg_file, theme_name)

        embed = discord.Embed(
            title="Your current profile theme: ",
            description=(
                f"Main theme: `{theme_name.capitalize()}`\n"
                f"Background: `{sub_label}`\n\n"
                "Below is your current profile card theme. "
                "You can change it by selecting a theme from the dropdown menu."
            )
        )
        embed.set_image(url=PC.ATTACHMENT_PROFILE)

        view = MainThemeView(ctx.author.id, cog=self)
        await ctx.send(embed=embed, file=file, view=view)

    @commands.hybrid_command(name="resetprofiletheme",description="Reset your profile card theme to default")
    @commands.guild_only()
    async def resetprofiletheme(self, ctx):
        """Reset the user's profile theme to default settings."""
        try:
            await self.set_user_theme(ctx.author.id, "default", None, "white")

            exp, level = await self.get_user(ctx.author.id, ctx.guild.id)
            title_name = get_title(level)
            next_exp = 50 * level + 20 * level**2 if level < PC.MAX_LEVEL else None
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
            embed.set_image(url=PC.ATTACHMENT_PROFILE)

            await ctx.send(embed=embed, file=file)

        except Exception:
            traceback.print_exc()
            await ctx.send("❌ Failed to reset profile theme. Check console/logs.")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listener to award EXP on message sent, subject to cooldown."""
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        user_id = message.author.id

        cooldown_key = f"cooldown:{guild_id}:{user_id}"

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