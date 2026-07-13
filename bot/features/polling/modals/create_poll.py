"""Modal used to create a new poll."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import ui
from discord.ext import commands

from bot.config.emojis import CustomEmojis, MinoriEmojis
from bot.features.polling.models import PollData
from bot.features.polling.repository import save_active_poll
from bot.features.polling.views.poll_view import PollView


class PollInputModal(ui.Modal, title="Create Poll"):
    """
    Modal used to create a new poll.
    """

    question = ui.TextInput(
        label="Question",
        placeholder="What's the poll about?",
        required=True,
        max_length=200,
    )
    opt1 = ui.TextInput(
        label="Option 1 (required)",
        placeholder="First option (required)",
        required=True,
        max_length=100,
    )
    opt2 = ui.TextInput(
        label="Option 2 (required)",
        placeholder="Second option (required)",
        required=True,
        max_length=100,
    )
    opt3 = ui.TextInput(
        label="Option 3 (optional)",
        placeholder="Third option (optional)",
        required=False,
        max_length=100,
    )
    opt4 = ui.TextInput(
        label="Option 4 (optional)",
        placeholder="Fourth option (optional)",
        required=False,
        max_length=100,
    )

    def __init__(self, ctx: commands.Context, timeout_seconds: Optional[int] = None):
        super().__init__()
        self.ctx = ctx
        self.timeout_seconds = timeout_seconds

    async def on_submit(self, interaction: discord.Interaction):
        raw_opts = [
            self.opt1.value.strip(),
            self.opt2.value.strip(),
            self.opt3.value.strip(),
            self.opt4.value.strip(),
        ]
        opts = [o for o in raw_opts if o]

        if len(opts) < 2:
            return await interaction.response.send_message(
                "⚠️ Please provide at least two options (Option 1 and Option 2 are required).",
                ephemeral=True,
            )

        normalized = [o.strip().lower() for o in opts]
        if len(set(normalized)) != len(normalized):
            return await interaction.response.send_message(
                f"{MinoriEmojis['MinoriConfused']} You cant make same options",
                ephemeral=True,
            )
        try:
            pool = self.ctx.bot.pool
            view = PollView(
                pool,
                self.question.value,
                opts,
                self.ctx.author,
                timeout=self.timeout_seconds,
            )
            embed = view.make_poll_embed()
            msg = await interaction.channel.send(embed=embed, view=view)
            view.message = msg
            end_time = (
                (datetime.now(timezone.utc) + timedelta(seconds=self.timeout_seconds))
                if self.timeout_seconds
                else None
            )

            data = PollData(
                message_id=msg.id,
                guild_id=interaction.guild.id,
                channel_id=interaction.channel.id,
                author_id=interaction.user.id,
                question=self.question.value,
                options=opts,
                end_time=end_time,
            )
            await save_active_poll(pool, data)

            try:
                await interaction.response.send_message(
                    f"{CustomEmojis['VERIFIED']} Poll successfully created!",
                    ephemeral=True,
                )
            except discord.errors.InteractionResponded:
                await interaction.followup.send(
                    f"{CustomEmojis['VERIFIED']} Poll successfully created!",
                    ephemeral=True,
                )
        except Exception as e:
            print(f"[Poll Create Error] {e}")
            try:
                await interaction.response.send_message(
                    f"⚠️ Failed to create poll: {e}", ephemeral=True
                )
            except discord.errors.InteractionResponded:
                await interaction.followup.send(
                    f"⚠️ Failed to create poll: {e}", ephemeral=True
                )
