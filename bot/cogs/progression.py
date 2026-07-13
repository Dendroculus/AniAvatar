import discord
from discord.ext import commands
import random
import asyncio
import io
import time
import redis.asyncio as redis
import logging
from typing import Optional, Tuple
from discord import MessageReference

from bot.features.progression.domain.levels import (
    get_title,
    get_title_emoji,
    required_exp,
)

from bot.utils.progression.profile_theme import MainThemeView
from bot.config.configs import (
    AssetPaths as AP,
    REDIS_CACHING,
    ProgressionConstants as PC,
    ProfileCardConstants as PCC,
)
from bot.utils.trading_ui import format_coins
from bot.config.emojis import CustomEmojis, TitleEmojis
from bot.services.render_manager import RenderManager
from bot.features.progression.profile_workflow import ProfileWorkflow
from bot.services.user_repository import UserRepository

"""
progression.py

Handles the leveling system, experience tracking, economy (coins), and
image generation for user profiles and leaderboards.
"""


class Progression(commands.Cog):
    """
    Manages user progression, economy, and profile rendering.
    """

    def __init__(self, bot):
        self.bot = bot
        self.repo: Optional[UserRepository] = None  # Initialized in cog_load
        self.render_manager = RenderManager()
        self.profile_workflow: ProfileWorkflow | None = None

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
                logging.getLogger("progression").warning(
                    f"Failed to connect to Redis: {e}"
                )
                self.redis = None

        self._fallback_cooldowns: dict[str, float] = {}

    async def cog_load(self):
        """Initialize database tables and repository."""
        if not self.bot.pool:
            raise RuntimeError("Bot database pool is not initialized.")

        self.repo = UserRepository(self.bot.pool)
        await self.repo.initialize_schema()
        self.profile_workflow = ProfileWorkflow(self.repo, self.render_manager)

    async def cog_unload(self):
        """Clean up resources."""
        try:
            if self.redis:
                await self.redis.close()
        except Exception as e:
            logging.getLogger("progression").warning(
                f"Error closing Redis connection: {e}"
            )
        self.render_manager.shutdown()

    async def get_coins(self, user_id: int, guild_id: int) -> int:
        """
        Function to get a user's coin balance.

        Args:
            user_id (int): The ID of the user.
            guild_id (int): The ID of the guild.

        Returns:
            int: The user's coin balance.
        """
        return await self.repo.get_coins(user_id, guild_id)

    async def add_coins(self, user_id: int, guild_id: int, amount: int):
        """
        Function to add coins to a user's balance.
        Args:
            user_id (int): The ID of the user.
            guild_id (int): The ID of the guild.
            amount (int): The amount of coins to add.

        Returns:
            None
        """
        await self.repo.add_coins(user_id, guild_id, amount)

    async def ensure_user_row(self, user_id: int, guild_id: int):
        """
        Function to ensure a user row exists in the database.
        Args:
            user_id (int): The ID of the user.
            guild_id (int): The ID of the guild.

        Returns:
            None
        """
        await self.repo.ensure_user_row(user_id, guild_id)

    async def remove_coins(self, user_id: int, guild_id: int, amount: int) -> bool:
        """
        Function to deduct coins from a user's balance.
        Args:
            user_id (int): The ID of the user.
            guild_id (int): The ID of the guild.
            amount (int): The amount of coins to deduct.

        Returns:
            bool: True if the operation was successful, False otherwise.
        """
        return await self.repo.remove_coins(user_id, guild_id, amount)

    async def reserve_coins(self, user_id: int, guild_id: int, amount: int) -> bool:
        """
        Function to reserve coins from a user's balance (for trades, etc), without permanently deducting them.
        Args:
            user_id (int): The ID of the user.
            guild_id (int): The ID of the guild.
            amount (int): The amount of coins to reserve.

        Returns:
            bool: True if the operation was successful, False otherwise.
        """
        return await self.repo.remove_coins(user_id, guild_id, amount)

    async def get_user(self, user_id: int, guild_id: int) -> Tuple[int, int]:
        """
        Function to get a user's EXP and level.
        Args:
            user_id (int): The ID of the user.
            guild_id (int): The ID of the guild.

        Returns:
            Tuple[int, int]: A tuple containing the user's EXP and level.
        """
        return await self.repo.get_user(user_id, guild_id)

    async def add_exp(
        self, user_id: int, guild_id: int, amount: int
    ) -> Tuple[int, int, bool]:
        """
        Function to add EXP to a user.
        Args:
            user_id (int): The ID of the user.
            guild_id (int): The ID of the guild.
            amount (int): The amount of EXP to add.

        Returns:
            Tuple[int, int, bool]: A tuple containing the new level, new EXP, and a boolean indicating if the user leveled up.
        """
        return await self.repo.add_exp(user_id, guild_id, amount)

    async def safe_send(self, ctx, *args, **kwargs):
        """
        Send a message safely handling both Context and Interaction objects.
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

    async def _build_rows_data(self, ctx, rows, avatar_size=128, avatar_timeout=3.0):
        """
        Prepare data structures for leaderboard rendering by fetching names and avatars.
        """
        meta = [
            (idx, user_id, level, exp)
            for idx, (user_id, level, exp) in enumerate(rows, start=1)
        ]

        async def get_name_and_avatar(user_id: int) -> tuple[str, bytes]:
            member = ctx.guild.get_member(user_id)
            if member:
                name = member.display_name
                return name, await self.profile_workflow.fetch_avatar_bytes(
                    member, size=avatar_size, timeout=avatar_timeout
                )
            try:
                user = await self.bot.fetch_user(user_id)
                name = user.name
                return name, await self.profile_workflow.fetch_avatar_bytes(
                    user, size=avatar_size, timeout=avatar_timeout
                )
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

            next_exp = None if level >= PC.MAX_LEVEL else (required_exp(level))
            rows_data.append(
                {
                    "rank": idx,
                    "avatar_bytes": avatar_bytes or b"",
                    "name": self.truncate(
                        name, PC.MAX_NAME_WIDTH, ellipsis="...", strip=False
                    ),
                    "level": level,
                    "title": get_title(level),
                    "exp": exp or 0,
                    "next_exp": next_exp,
                }
            )

        return rows_data

    def truncate(
        self, text: str, max_len: int, ellipsis: str = "...", strip: bool = False
    ) -> str:
        """Truncate a string to a maximum length."""
        if len(text) <= max_len:
            return text
        truncated = text[: max_len - len(ellipsis)]
        if strip:
            truncated = truncated.rstrip()
        return truncated + ellipsis

    async def announce_level_up(
        self,
        guild_id: int,
        user_id: int,
        new_level: int,
        old_level: int,
        channel: discord.abc.Messageable,
    ):
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
            embed_title = (
                f"{member.display_name} {CustomEmojis['UPWARDARROW']} {new_level}"
            )
            embed_description = (
                f"```Congratulations {member.display_name}! You have reached level {new_level}.```\n"
                f"Title: `{new_title}` {new_emoji}"
            )
        embed = discord.Embed(
            title=embed_title,
            description=embed_description,
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        lvlup_msg = await channel.send(embed=embed)
        coins_amount = random.randint(30, 50)
        await self.repo.add_coins(user_id, guild_id, coins_amount)
        await channel.send(
            f"{member.display_name} received {PC.coins_emoji()} {coins_amount} coins for leveling up!",
            reference=MessageReference(
                message_id=lvlup_msg.id,
                channel_id=lvlup_msg.channel.id,
                guild_id=lvlup_msg.guild.id,
            ),
        )

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """Remove all user data for a guild when the bot leaves it."""
        await self.repo.delete_guild_data(guild.id)
        print(f"[Progression] Cleaned up DB for guild {guild.id} ({guild.name})")

    @commands.hybrid_command(
        name="profile", description="Check your level, EXP, and title"
    )
    @commands.guild_only()
    async def profile(self, ctx, member: discord.Member = None):
        """Display a rendered profile card for the selected member."""
        member = member or ctx.author
        if member.bot:
            await ctx.send(f"{member.display_name} is a bot and cannot have a profile.")
            return

        try:
            if ctx.interaction:
                await ctx.defer()

            if self.profile_workflow is None:
                raise RuntimeError("Profile workflow is not initialized.")

            result = await self.profile_workflow.render(
                member,
                ctx.guild.id,
                include_rank=True,
            )
            if not result.image_bytes:
                await ctx.send(
                    "âŒ Failed to generate profile image â€” check bot logs."
                )
                return

            file = discord.File(
                io.BytesIO(result.image_bytes),
                filename=PC.PROFILE_PNG,
            )
            content = f"{member.display_name} {result.badge_text}".strip()

            await self.safe_send(
                ctx,
                content=content if result.badge_text else None,
                file=file,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Unexpected error while generating a profile."
            )
            await ctx.send(
                "âŒ Unexpected error while generating profile. Check console/logs."
            )

    async def _lb_defer(self, ctx):
        """Helper to defer the interaction safely."""
        try:
            await ctx.defer()
        except Exception as e:
            print(f"[Leaderboard] Defer failed (non-fatal): {e}")

    async def _lb_get_cache(self, key: str) -> Optional[bytes]:
        """Helper to retrieve data from Redis."""
        if not self.redis:
            return None
        try:
            data = await self.redis.get(key)
            print(f"[Leaderboard] {'Cache hit' if data else 'Cache miss'}")
            return data
        except Exception as e:
            print(f"[Leaderboard] Cache read failed: {e}")
            return None

    async def _lb_query_rows(self, guild_id: int):
        """Helper to fetch leaderboard rows from the repository."""
        print(f"[Leaderboard] Query start (guild={guild_id})")
        try:
            rows = await self.repo.get_leaderboard_rows(guild_id, 10)
            print(f"[Leaderboard] Query done, rows={len(rows)}")
            return rows
        except Exception as e:
            print(f"[Leaderboard] DB query failed: {e}")
            return None

    async def _lb_build_embed(self, ctx, file_bytes: bytes, embed_color: discord.Color):
        """Helper to construct the leaderboard embed and file."""
        user_rank = await self.repo.get_rank(ctx.author.id, ctx.guild.id)
        user_coins = await self.repo.get_coins(ctx.author.id, ctx.guild.id)
        formatted_coins = format_coins(user_coins)

        file = discord.File(io.BytesIO(file_bytes), filename="leaderboard.png")
        embed = discord.Embed(
            title=f"{ctx.guild.name}'s Top Rank List {TitleEmojis['CHAMPION']}",
            color=embed_color,
            description=(
                f"**Your Rank**\n"
                f"You are ranked **#{user_rank}** on this server\n"
                f"with a total of **{formatted_coins}** {PC.coins_emoji()}"
            ),
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        embed.set_image(url="attachment://leaderboard.png")
        return embed, file

    def _lb_fire_cache_set(self, key: str, data: bytes):
        """Helper to upload to Redis asynchronously."""
        if not self.redis:
            return
        print("[Leaderboard] Upload to Redis (fire-and-forget)")
        try:
            self.bot.loop.create_task(self.redis.set(key, data, ex=120))
        except Exception as e:
            print(f"[Leaderboard] Redis set failed: {e}")

    @commands.hybrid_command(
        name="leaderboard", description="Show server rankings leaderboard"
    )
    @commands.guild_only()
    async def leaderboard_image(self, ctx):
        """Generate and display the server leaderboard."""
        start = time.perf_counter()
        await self._lb_defer(ctx)

        cache_key = f"lb_cache:{ctx.guild.id}"

        cached_bytes = await self._lb_get_cache(cache_key)
        if cached_bytes:
            embed, file = await self._lb_build_embed(
                ctx, cached_bytes, discord.Color.purple()
            )
            await self.safe_send(ctx, embed=embed, file=file)
            print(
                f"[Leaderboard] FAST CACHE path completed in {time.perf_counter() - start:.3f}s"
            )
            return

        rows = await self._lb_query_rows(ctx.guild.id)
        if rows is None:
            return await self.safe_send(
                ctx, "Failed to fetch leaderboard data (check logs)."
            )
        if not rows:
            return await self.safe_send(ctx, "No users found in the leaderboard.")

        rows_data = await self._build_rows_data(ctx, rows)
        exp_icon_path = AP.ESSENTIAL_ICONS["EXP"]
        img_bytes = await self.render_manager.render_leaderboard(
            rows_data, exp_icon_path, str(ctx.guild.id)
        )

        if not img_bytes:
            return await self.safe_send(
                ctx, "Failed to generate leaderboard image (check logs)."
            )

        top_title = get_title(rows_data[0]["level"]) if rows_data else "Leaderboard"
        embed_color = PCC.TITLE_COLORS.get(top_title, discord.Color.purple())

        embed, file = await self._lb_build_embed(ctx, img_bytes, embed_color)
        await self.safe_send(ctx, embed=embed, file=file)

        self._lb_fire_cache_set(cache_key, img_bytes)
        print(
            f"[Leaderboard] Completed command (total {time.perf_counter() - start:.3f}s)\n"
        )

    @commands.hybrid_command(
        name="profiletheme", description="Choose your profile card background theme"
    )
    @commands.guild_only()
    async def profiletheme(self, ctx):
        """Show the current profile theme and its interactive selector."""
        if self.profile_workflow is None:
            raise RuntimeError("Profile workflow is not initialized.")

        result = await self.profile_workflow.render(
            ctx.author,
            ctx.guild.id,
            include_background_label=True,
        )
        if not result.image_bytes:
            await ctx.send("âŒ Failed to generate profile image â€” check bot logs.")
            return

        file = discord.File(
            io.BytesIO(result.image_bytes),
            filename=PC.PROFILE_PNG,
        )
        embed = discord.Embed(
            title="Your current profile theme: ",
            description=(
                f"Main theme: `{result.theme_name.capitalize()}`\n"
                f"Background: `{result.background_label}`\n\n"
                "Below is your current profile card theme. "
                "You can change it by selecting a theme from the dropdown menu."
            ),
        )
        embed.set_image(url=PC.ATTACHMENT_PROFILE)

        view = MainThemeView(ctx.author.id, cog=self)
        await ctx.send(embed=embed, file=file, view=view)

    @commands.hybrid_command(
        name="resetprofiletheme", description="Reset your profile card theme to default"
    )
    @commands.guild_only()
    async def resetprofiletheme(self, ctx):
        """Reset the user's profile theme to its default settings."""
        try:
            if self.profile_workflow is None:
                raise RuntimeError("Profile workflow is not initialized.")

            result = await self.profile_workflow.reset_and_render(
                ctx.author,
                ctx.guild.id,
            )
            if not result.image_bytes:
                await ctx.send(
                    "âŒ Failed to generate profile image â€” check bot logs."
                )
                return

            file = discord.File(
                io.BytesIO(result.image_bytes),
                filename=PC.PROFILE_PNG,
            )
            embed = discord.Embed(
                title="Profile Theme Reset",
                description="Your profile card theme has been reset to default.",
            )
            embed.set_image(url=PC.ATTACHMENT_PROFILE)

            await ctx.send(embed=embed, file=file)
        except Exception:
            logging.getLogger(__name__).exception(
                "Failed to reset a user's profile theme."
            )
            await ctx.send("âŒ Failed to reset profile theme. Check console/logs.")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listener to award EXP on message sent, subject to cooldown."""
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        user_id = message.author.id

        cooldown_key = f"cooldown:{guild_id}:{user_id}"

        use_fallback = True

        if self.redis:
            try:
                allowed = await self.redis.set(cooldown_key, b"1", ex=5, nx=True)
                if not allowed:
                    return

                use_fallback = False
            except Exception as e:
                logging.getLogger("progression").warning(
                    f"Redis error during cooldown check: {e}"
                )

        if use_fallback:
            now = discord.utils.utcnow().timestamp()
            last = self._fallback_cooldowns.get(cooldown_key, 0)
            if now - last < 5:
                return
            self._fallback_cooldowns[cooldown_key] = now

        exp, level = await self.repo.get_user(user_id, guild_id)
        old_level = level

        exp_gain = random.randint(5 + level * 8, 10 + level * 12)
        level, new_exp, leveled_up = await self.repo.add_exp(
            user_id, guild_id, exp_gain
        )

        if leveled_up:
            await self.announce_level_up(
                guild_id, user_id, level, old_level, message.channel
            )
            old_rank = await self.repo.get_rank_for(guild_id, old_level, exp)
            new_rank = await self.repo.get_rank_for(guild_id, level, new_exp)
            if new_rank < old_rank:
                embed = discord.Embed(
                    title=f"{CustomEmojis['UPWARDARROW']} Rank Up! {message.author.display_name}",
                    description=f"```{message.author.display_name} has ranked up to #{new_rank} in the server leaderboard! 🎉```",
                    color=discord.Color.gold(),
                )
                embed.set_thumbnail(url=message.author.display_avatar.url)
                await message.channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Progression(bot))
