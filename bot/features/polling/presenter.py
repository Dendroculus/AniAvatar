"""Presentation helpers for polling results and embeds."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime

import discord

from bot.config.emojis import CustomEmojis, MinoriEmojis


def compute_poll_results(
    *,
    question: str,
    votes: Mapping[str, Collection[int]],
) -> tuple[dict[str, int], list[str], str]:
    """Calculate vote counts, winners, and the final announcement."""

    results = {option: len(user_ids) for option, user_ids in votes.items()}

    winners: list[str] = []
    winner_text = ""

    if not results:
        return results, winners, winner_text

    max_votes = max(results.values())
    winners = [option for option, count in results.items() if count == max_votes]

    if max_votes == 0:
        winner_text = (
            f"\n\n{MinoriEmojis['MinoriWink']} "
            f"Polling for `{question}` ended. "
            "No votes were cast."
        )
    elif len(winners) == 1:
        suffix = "s" if max_votes != 1 else ""

        winner_text = (
            f"\n\n{MinoriEmojis['MinoriPray']} "
            f"Polling for `{question}` ended. "
            f"The highest vote goes to **{winners[0]}** "
            f"with {max_votes} vote{suffix}."
        )
    else:
        winner_text = (
            f"\n\n{MinoriEmojis['MinoriPray']} "
            f"Polling for `{question}` ended. "
            f"It's a tie between {', '.join(winners)} "
            f"? each with {max_votes} votes."
        )

    return results, winners, winner_text


def build_poll_embed(
    *,
    question: str,
    votes: Mapping[str, Collection[int]],
    end_time: datetime | None,
    closed: bool = False,
    bar_len: int = 10,
) -> discord.Embed:
    """Build the Discord embed representing a poll."""

    total_votes = sum(len(user_ids) for user_ids in votes.values())

    colors = [
        "??",
        "??",
        "??",
        "??",
        "??",
        "??",
        "??",
    ]

    embed = discord.Embed(
        title=f"{CustomEmojis['CHART']}  {question}",
        color=discord.Color.blurple(),
    )

    for index, (option, user_ids) in enumerate(
        votes.items(),
        start=1,
    ):
        count = len(user_ids)

        percent = count / total_votes * 100 if total_votes > 0 else 0

        filled = int(percent / 100 * bar_len) if bar_len > 0 else 0

        empty = max(0, bar_len - filled)
        color = colors[index % len(colors)]

        bar = color * filled + CustomEmojis["Gray_Large_Square"] * empty

        embed.add_field(
            name=option,
            value=f"{bar} `{percent:.0f}% ({count})`",
            inline=False,
        )

    status = _build_poll_status(
        total_votes=total_votes,
        end_time=end_time,
        closed=closed,
    )

    embed.add_field(
        name="\u200b",
        value=status,
        inline=False,
    )

    return embed


def _build_poll_status(
    *,
    total_votes: int,
    end_time: datetime | None,
    closed: bool,
) -> str:
    """Build the status section displayed below poll options."""

    anonymous = f"{CustomEmojis['SecretBox']} Votes are anonymous"

    if closed and end_time:
        return (
            f"{CustomEmojis['Locked']} "
            f"Poll closed <t:{int(end_time.timestamp())}:R>\n"
            f"{anonymous}\n"
            f"With total of `{total_votes} votes`"
        )

    if closed:
        return f"{CustomEmojis['Locked']} Poll closed\n{anonymous}\n{total_votes} votes"

    if end_time:
        return (
            f"{CustomEmojis['TIME']} "
            f"Poll closes <t:{int(end_time.timestamp())}:R>\n"
            f"{anonymous}\n"
            f"Total Votes: `{total_votes}` votes"
        )

    return f"{anonymous}\n{total_votes} votes"
