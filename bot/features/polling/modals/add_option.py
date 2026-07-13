"""Modal used to append options to an active poll."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import ui

from bot.config.configs import PollingConstants as POLCONST
from bot.config.emojis import CustomEmojis, MinoriEmojis
from bot.features.polling.models import PollData
from bot.features.polling.repository import save_active_poll

if TYPE_CHECKING:
    from bot.features.polling.views.poll_view import PollView


class AddOptionModal(ui.Modal, title="Add Poll Options"):
    """
    Modal presented to the poll creator to add up to 5 additional options.
    """

    opt1 = ui.TextInput(
        label="Option 1 (optional)",
        required=False,
        max_length=100,
        placeholder=POLCONST.MODAL_PLACEHOLDER,
    )
    opt2 = ui.TextInput(
        label="Option 2 (optional)",
        required=False,
        max_length=100,
        placeholder=POLCONST.MODAL_PLACEHOLDER,
    )
    opt3 = ui.TextInput(
        label="Option 3 (optional)",
        required=False,
        max_length=100,
        placeholder=POLCONST.MODAL_PLACEHOLDER,
    )
    opt4 = ui.TextInput(
        label="Option 4 (optional)",
        required=False,
        max_length=100,
        placeholder=POLCONST.MODAL_PLACEHOLDER,
    )
    opt5 = ui.TextInput(
        label="Option 5 (optional)",
        required=False,
        max_length=100,
        placeholder=POLCONST.MODAL_PLACEHOLDER,
    )

    def __init__(self, poll_view: "PollView"):
        super().__init__()
        self.poll_view = poll_view
        self.description = (
            "Note: Discord only allows a maximum of 25 options per select menu."
        )

    async def on_submit(self, interaction: discord.Interaction):
        """
        Handle submission of new options.
        """
        if not self.poll_view.message:
            return await interaction.response.send_message(
                "⚠️ Poll message no longer exists.", ephemeral=True
            )

        new_opts_raw = [
            self.opt1.value.strip(),
            self.opt2.value.strip(),
            self.opt3.value.strip(),
            self.opt4.value.strip(),
            self.opt5.value.strip(),
        ]
        new_opts = [o for o in new_opts_raw if o]

        if not new_opts:
            return await interaction.response.send_message(
                "⚠️ No new options were added.", ephemeral=True
            )

        normalized_existing = [o.lower() for o in self.poll_view.options]
        for opt in new_opts:
            if opt.lower() in normalized_existing:
                return await interaction.response.send_message(
                    f"{MinoriEmojis['MinoriConfused']} You can't add duplicate options.",
                    ephemeral=True,
                )
        MAX_OPTIONS = 14
        if len(self.poll_view.options) + len(new_opts) > MAX_OPTIONS:
            return await interaction.response.send_message(
                f"⚠️ You can only add up to {MAX_OPTIONS} options.", ephemeral=True
            )

        for opt in new_opts:
            self.poll_view.options.append(opt)
            self.poll_view.votes[opt] = set()
            select: discord.ui.Select = next(
                (
                    i
                    for i in self.poll_view.children
                    if isinstance(i, discord.ui.Select)
                ),
                None,
            )
            if select:
                select.options = [
                    discord.SelectOption(label=opt, value=str(idx))
                    for idx, opt in enumerate(self.poll_view.options)
                ]
                select.placeholder = (
                    "Select one answer (scroll for more)"
                    if len(self.poll_view.options) > 10
                    else "Select one answer"
                )

        embed = self.poll_view.make_poll_embed()
        await self.poll_view.message.edit(embed=embed, view=self.poll_view)

        try:
            data = PollData(
                message_id=self.poll_view.message.id,
                guild_id=self.poll_view.message.guild.id,
                channel_id=self.poll_view.message.channel.id,
                author_id=self.poll_view.author.id,
                question=self.poll_view.question,
                options=self.poll_view.options,
                end_time=self.poll_view.end_time,
            )
            await save_active_poll(self.poll_view.pool, data)
        except Exception as e:
            print(f"[Poll DB Save Error on add_option] {e}")

        await interaction.response.send_message(
            f"{CustomEmojis['VERIFIED']} Added {len(new_opts)} option(s). Total options: {len(self.poll_view.options)}",
            ephemeral=True,
        )
