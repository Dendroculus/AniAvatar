"""Leaderboard orchestration for progression commands."""

from __future__ import annotations

import asyncio
import io
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import discord
import redis.asyncio as redis

from bot.config.configs import (
    AssetPaths as AP,
    ProfileCardConstants as PCC,
    ProgressionConstants as PC,
)
from bot.config.emojis import TitleEmojis
from bot.features.progression.domain.levels import (
    get_title,
    required_exp,
)
from bot.core.rendering.render_manager import RenderManager
from bot.core.repositories.user_repository import UserRepository
from bot.features.trading.views import format_coins

AvatarFetcher = Callable[..., Awaitable[bytes]]


@dataclass(slots=True)
class LeaderboardResult:
    """Discord-ready leaderboard output or failure message."""

    embed: discord.Embed | None = None
    file: discord.File | None = None
    error_message: str | None = None


class LeaderboardWorkflow:
    """Fetch, cache, render, and present a leaderboard."""

    def __init__(
        self,
        *,
        bot: Any,
        repository: UserRepository,
        render_manager: RenderManager,
        redis_client: redis.Redis | None,
        avatar_fetcher: AvatarFetcher,
    ) -> None:
        self.bot = bot
        self.repository = repository
        self.render_manager = render_manager
        self.redis = redis_client
        self.avatar_fetcher = avatar_fetcher

    async def execute(
        self,
        ctx: Any,
    ) -> LeaderboardResult:
        """Build the leaderboard output for a command."""
        start = time.perf_counter()
        await self._defer(ctx)

        cache_key = f"lb_cache:{ctx.guild.id}"
        cached_bytes = await self._get_cache(cache_key)

        if cached_bytes:
            embed, file = await self._build_embed(
                ctx,
                cached_bytes,
                discord.Color.purple(),
            )

            print(
                "[Leaderboard] FAST CACHE path completed in "
                f"{time.perf_counter() - start:.3f}s"
            )

            return LeaderboardResult(
                embed=embed,
                file=file,
            )

        rows = await self._query_rows(ctx.guild.id)

        if rows is None:
            return LeaderboardResult(
                error_message=("Failed to fetch leaderboard data (check logs).")
            )

        if not rows:
            return LeaderboardResult(
                error_message=("No users found in the leaderboard.")
            )

        rows_data = await self._build_rows_data(
            ctx,
            rows,
        )

        image_bytes = await self.render_manager.render_leaderboard(
            rows_data,
            AP.ESSENTIAL_ICONS["EXP"],
            str(ctx.guild.id),
        )

        if not image_bytes:
            return LeaderboardResult(
                error_message=("Failed to generate leaderboard image (check logs).")
            )

        top_title = get_title(rows_data[0]["level"])

        embed_color = PCC.TITLE_COLORS.get(
            top_title,
            discord.Color.purple(),
        )

        embed, file = await self._build_embed(
            ctx,
            image_bytes,
            embed_color,
        )

        self._fire_cache_set(
            cache_key,
            image_bytes,
        )

        print(
            "[Leaderboard] Completed command "
            f"(total {time.perf_counter() - start:.3f}s)\n"
        )

        return LeaderboardResult(
            embed=embed,
            file=file,
        )

    async def _defer(
        self,
        ctx: Any,
    ) -> None:
        """Defer without breaking prefix commands."""
        try:
            await ctx.defer()
        except Exception as exc:
            print(f"[Leaderboard] Defer failed (non-fatal): {exc}")

    async def _get_cache(
        self,
        key: str,
    ) -> bytes | None:
        """Retrieve rendered bytes from Redis."""
        if not self.redis:
            return None

        try:
            data = await self.redis.get(key)

            print(f"[Leaderboard] {'Cache hit' if data else 'Cache miss'}")

            return data

        except Exception as exc:
            print(f"[Leaderboard] Cache read failed: {exc}")
            return None

    async def _query_rows(
        self,
        guild_id: int,
    ):
        """Fetch the highest-ranked guild users."""
        print(f"[Leaderboard] Query start (guild={guild_id})")

        try:
            rows = await self.repository.get_leaderboard_rows(
                guild_id,
                10,
            )

            print(f"[Leaderboard] Query done, rows={len(rows)}")

            return rows

        except Exception as exc:
            print(f"[Leaderboard] DB query failed: {exc}")
            return None

    async def _build_rows_data(
        self,
        ctx: Any,
        rows,
        *,
        avatar_size: int = 128,
        avatar_timeout: float = 3.0,
    ) -> list[dict[str, Any]]:
        """Resolve names and avatars for rendering."""
        metadata = [
            (
                rank,
                user_id,
                level,
                exp,
            )
            for rank, (
                user_id,
                level,
                exp,
            ) in enumerate(
                rows,
                start=1,
            )
        ]

        async def get_name_and_avatar(
            user_id: int,
        ) -> tuple[str, bytes]:
            member = ctx.guild.get_member(user_id)

            if member:
                avatar_bytes = await self.avatar_fetcher(
                    member,
                    size=avatar_size,
                    timeout=avatar_timeout,
                )

                return (
                    member.display_name,
                    avatar_bytes,
                )

            try:
                user = await self.bot.fetch_user(user_id)

                avatar_bytes = await self.avatar_fetcher(
                    user,
                    size=avatar_size,
                    timeout=avatar_timeout,
                )

                return (
                    user.name,
                    avatar_bytes,
                )

            except Exception as exc:
                print(f"[avatar_fetch] failed for user {user_id}: {exc}")

                return (
                    f"User {user_id}",
                    b"",
                )

        tasks = [get_name_and_avatar(user_id) for _, user_id, _, _ in metadata]

        results = await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        rows_data: list[dict[str, Any]] = []

        for (
            rank,
            user_id,
            level,
            exp,
        ), result in zip(
            metadata,
            results,
            strict=True,
        ):
            if isinstance(result, Exception):
                print(f"[avatar_fetch] task exception for user {user_id}: {result}")

                name = f"User {user_id}"
                avatar_bytes = b""

            else:
                name, avatar_bytes = result

            next_exp = None if level >= PC.MAX_LEVEL else required_exp(level)

            rows_data.append(
                {
                    "rank": rank,
                    "avatar_bytes": avatar_bytes or b"",
                    "name": self._truncate(
                        name,
                        PC.MAX_NAME_WIDTH,
                    ),
                    "level": level,
                    "title": get_title(level),
                    "exp": exp or 0,
                    "next_exp": next_exp,
                }
            )

        return rows_data

    async def _build_embed(
        self,
        ctx: Any,
        file_bytes: bytes,
        embed_color: discord.Color,
    ) -> tuple[discord.Embed, discord.File]:
        """Create the leaderboard embed and attachment."""
        user_rank = await self.repository.get_rank(
            ctx.author.id,
            ctx.guild.id,
        )

        user_coins = await self.repository.get_coins(
            ctx.author.id,
            ctx.guild.id,
        )

        file = discord.File(
            io.BytesIO(file_bytes),
            filename="leaderboard.png",
        )

        embed = discord.Embed(
            title=(f"{ctx.guild.name}'s Top Rank List {TitleEmojis['CHAMPION']}"),
            color=embed_color,
            description=(
                "**Your Rank**\n"
                f"You are ranked **#{user_rank}** "
                "on this server\n"
                f"with a total of "
                f"**{format_coins(user_coins)}** "
                f"{PC.coins_emoji()}"
            ),
        )

        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)

        embed.set_image(url="attachment://leaderboard.png")

        return embed, file

    def _fire_cache_set(
        self,
        key: str,
        data: bytes,
    ) -> None:
        """Schedule an expiring Redis cache write."""
        if not self.redis:
            return

        print("[Leaderboard] Upload to Redis (fire-and-forget)")

        try:
            self.bot.loop.create_task(
                self.redis.set(
                    key,
                    data,
                    ex=120,
                )
            )

        except Exception as exc:
            print(f"[Leaderboard] Redis set failed: {exc}")

    @staticmethod
    def _truncate(
        text: str,
        max_len: int,
        ellipsis: str = "...",
    ) -> str:
        """Truncate text to the supported width."""
        if len(text) <= max_len:
            return text

        return text[: max_len - len(ellipsis)] + ellipsis
