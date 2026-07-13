"""Restore active polls and finalize expired polls after restart."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import discord
from discord.ext import commands

from bot.features.polling.domain import (
    _compute_results_from_votes,
    _is_expired,
    _parse_options,
    _parse_votes,
    _remaining_seconds,
    _sanitize_votes,
)
from bot.features.polling.repository import record_poll_result
from bot.features.polling.views import PollView


async def _get_author_member(
    guild: discord.Guild, author_id: Optional[int]
) -> discord.Member:
    """Resolve the author_id to a Guild Member object."""
    if author_id:
        try:
            member = guild.get_member(int(author_id))
            if not member:
                member = await guild.fetch_member(int(author_id))
            if member:
                return member
        except Exception:
            pass
    return guild.me


def _get_guild(bot: commands.Bot, guild_id: Optional[int]) -> Optional[discord.Guild]:
    """Resolve a guild id to a Guild object using the bot's internal cache."""
    try:
        return bot.get_guild(int(guild_id)) if guild_id is not None else None
    except Exception:
        return None


def _get_channel(
    guild: discord.Guild, channel_id: Optional[int]
) -> Optional[discord.abc.GuildChannel]:
    """Resolve a channel id to a GuildChannel via guild.get_channel."""
    try:
        return guild.get_channel(int(channel_id)) if channel_id is not None else None
    except Exception:
        return None


async def _try_fetch_message(
    channel: Optional[discord.TextChannel], message_id: int
) -> Optional[discord.Message]:
    """Attempt to fetch a message from a channel; return None when the message is not found."""
    if not channel:
        return None
    try:
        return await channel.fetch_message(int(message_id))
    except Exception:
        print(f"[Poll Reload] message {message_id} not found in channel {channel.id}.")
        return None


async def _finalize_expired_poll(
    bot: commands.Bot,
    *,
    guild: Optional[discord.Guild],
    msg: Optional[discord.Message],
    message_id: int,
    question: str,
    options: list,
    sanitized_votes: Dict[str, list[int]],
    end_time: Optional[float],
    author_id: Optional[int],
) -> None:
    """Finalize a poll that has expired while the bot was offline."""
    counts, winners = _compute_results_from_votes(sanitized_votes)
    try:
        await record_poll_result(
            bot.pool,
            message_id=message_id,
            winners=winners,
            counts=counts,
            total_votes=sum(counts.values()),
        )
    except Exception as e:
        print(
            f"[Poll Reload] failed to record result for expired poll {message_id}: {e}"
        )

    if not msg:
        print(
            f"[Poll Reload] expired poll {message_id} finalized without message (no message to edit)."
        )
        return

    try:
        assert guild is not None
        author_member = await _get_author_member(guild, author_id)
        view = PollView(
            bot.pool,
            question=question or "Poll",
            options=options,
            author=author_member,
            timeout=None,
        )
        view.votes = {opt: set(uids) for opt, uids in sanitized_votes.items()}
        try:
            view.end_time = (
                datetime.fromtimestamp(float(end_time), timezone.utc)
                if end_time
                else None
            )
        except Exception:
            view.end_time = None
        view.message = msg
        await view.on_timeout()
        print(f"[Poll Reload] finalized expired poll {message_id} (edited message).")
    except Exception as e:
        print(
            f"[Poll Reload] failed to finalize expired poll {message_id} via message edit: {e}"
        )


async def _restore_active_poll(
    bot: commands.Bot,
    *,
    guild: discord.Guild,
    msg: Optional[discord.Message],
    message_id: int,
    question: str,
    options: list,
    sanitized_votes: Dict[str, list[int]],
    remaining_seconds: Optional[int],
    author_id: Optional[int],
) -> None:
    """Restore an active poll into memory and re-attach its interactive view."""
    try:
        author_member = await _get_author_member(guild, author_id)
        view = PollView(
            bot.pool,
            question=question or "Poll",
            options=options,
            author=author_member,
            timeout=remaining_seconds,
        )
        view.votes = {opt: set(uids) for opt, uids in sanitized_votes.items()}
        if msg:
            view.message = msg
            try:
                await msg.edit(view=view)
            except Exception as e:
                print(
                    f"[Poll Reload] failed to attach view to message {message_id}: {e}"
                )
        else:
            print(
                f"[Poll Reload] message not found for active poll {message_id}; view created in memory only."
            )
        print(f"♻️ Reloaded poll {message_id} (remaining: {remaining_seconds}s).")
    except Exception as e:
        print(f"[Poll Reload Error] failed to restore active poll {message_id}: {e}")


async def _finalize_or_restore(
    bot: commands.Bot,
    *,
    guild: Optional[discord.Guild],
    msg: Optional[discord.Message],
    message_id: int,
    question: str,
    options: list,
    sanitized_votes: Dict[str, list[int]],
    remaining_seconds: Optional[int],
    end_time: Optional[float],
    author_id: Optional[int],
) -> None:
    """Decide whether to finalize an expired poll or restore an active one."""
    if _is_expired(remaining_seconds):
        await _finalize_expired_poll(
            bot,
            guild=guild,
            msg=msg,
            message_id=message_id,
            question=question,
            options=options,
            sanitized_votes=sanitized_votes,
            end_time=end_time,
            author_id=author_id,
        )
    else:
        if guild is None:
            print(
                f"[Poll Reload] cannot restore active poll {message_id} without guild."
            )
            return
        await _restore_active_poll(
            bot,
            guild=guild,
            msg=msg,
            message_id=message_id,
            question=question,
            options=options,
            sanitized_votes=sanitized_votes,
            remaining_seconds=remaining_seconds,
            author_id=author_id,
        )


async def reconstruct_poll(bot: commands.Bot, row: Dict[str, Any]) -> None:
    """
    Rehydrate a single stored poll row.
    """
    try:
        message_id = row.get("message_id")
        guild_id = row.get("guild_id")
        channel_id = row.get("channel_id")
        author_id = row.get("author_id")
        question = row.get("question") or "Poll"
        options_json = row.get("options")
        votes_json = row.get("votes")
        end_time = row.get("end_time")
        ended = row.get("ended")
    except Exception:
        print("[Poll Reload] skipping row due to unexpected shape:", row)
        return

    if ended:
        return

    options = _parse_options(options_json)
    votes_raw = _parse_votes(votes_json)
    sanitized_votes = _sanitize_votes(options, votes_raw)
    remaining_seconds = _remaining_seconds(end_time)

    guild = _get_guild(bot, guild_id)
    if not guild:
        print(
            f"[Poll Reload] guild {guild_id} not found for poll {message_id}, skipping restore."
        )
        if _is_expired(remaining_seconds):
            await _finalize_expired_poll(
                bot,
                guild=None,
                msg=None,
                message_id=message_id,
                question=question,
                options=options,
                sanitized_votes=sanitized_votes,
                end_time=end_time,
                author_id=author_id,
            )
        return

    channel = _get_channel(guild, channel_id)
    if not channel:
        print(
            f"[Poll Reload] channel {channel_id} not found in guild {guild.id} for poll {message_id}, skipping."
        )
        if _is_expired(remaining_seconds):
            await _finalize_expired_poll(
                bot,
                guild=guild,
                msg=None,
                message_id=message_id,
                question=question,
                options=options,
                sanitized_votes=sanitized_votes,
                end_time=end_time,
                author_id=author_id,
            )
        return

    msg = await _try_fetch_message(channel, message_id)
    await _finalize_or_restore(
        bot,
        guild=guild,
        msg=msg,
        message_id=message_id,
        question=question,
        options=options,
        sanitized_votes=sanitized_votes,
        remaining_seconds=remaining_seconds,
        end_time=end_time,
        author_id=author_id,
    )
