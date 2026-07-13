"""Discord views and modals for interactive polls."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import asyncpg
import discord
from discord import ui
from discord.ext import commands

from bot.config.configs import PollingConstants as POLCONST
from bot.config.emojis import CustomEmojis, MinoriEmojis
from bot.features.polling.models import PollData
from bot.features.polling.repository import (
    delete_vote,
    record_poll_result,
    save_active_poll,
    upsert_vote,
)


class PollView(discord.ui.View):
    """
    Interactive in-memory representation of a poll.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        question: str,
        options: List[str],
        author: discord.Member,
        timeout: Optional[int] = None,
    ):
        super().__init__(timeout=timeout)
        self.pool = pool
        self.question = question
        self.options = options
        # votes stored as option -> set(user_id)
        self.votes = {opt: set() for opt in options}
        self.author = author
        self.message: Optional[discord.Message] = None
        self.updater_task: Optional[asyncio.Task] = None
        self.ended = False
        self.end_time = (
            (datetime.now(timezone.utc) + timedelta(seconds=timeout))
            if timeout
            else None
        )

        # UI components
        add_button = discord.ui.Button(
            label="Add Option", style=discord.ButtonStyle.green
        )
        add_button.callback = self.add_option
        self.add_item(add_button)

        select = discord.ui.Select(
            placeholder="Select one answer",
            options=[
                discord.SelectOption(label=opt, value=str(i))
                for i, opt in enumerate(options)
            ],
            min_values=1,
            max_values=1,
        )
        select.callback = self.select_callback
        self.add_item(select)

        remove_button = discord.ui.Button(
            label="Remove Vote", style=discord.ButtonStyle.danger
        )
        remove_button.callback = self.remove_vote
        self.add_item(remove_button)

        end_button = discord.ui.Button(label="End Poll", style=discord.ButtonStyle.red)
        end_button.callback = self.end_poll
        self.add_item(end_button)

        if self.end_time:
            loop = asyncio.get_running_loop()
            self.updater_task = loop.create_task(self._auto_end())

    async def _auto_end(self):
        """
        Background coroutine that waits until end_time and then finalizes the poll.
        """
        if self.ended or not self.end_time:
            return

        remaining = (self.end_time - datetime.now(timezone.utc)).total_seconds()
        if remaining > 0:
            await asyncio.sleep(remaining)

        if not self.ended:
            await self.on_timeout()

    async def _send_poll_error(self, interaction: discord.Interaction, message: str):
        """Helper to send ephemeral error messages safely."""
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(message, ephemeral=True)
            else:
                await interaction.followup.send(message, ephemeral=True)
        except Exception:
            pass

    async def _handle_poll_expiration(self):
        """Helper to handle the cleanup when a poll expires naturally."""
        if self.updater_task and not self.updater_task.done():
            try:
                self.updater_task.cancel()
            except Exception:
                pass
        await self.on_timeout()

    async def _ensure_poll_active(self, interaction: discord.Interaction) -> bool:
        """
        Ensure the poll is still active before processing an interaction.
        Refactored to reduce Cognitive Complexity.
        """
        if self.ended:
            await self._send_poll_error(interaction, "⚠️ Poll already closed.")
            return False

        if self.end_time and datetime.now(timezone.utc) >= self.end_time:
            await self._handle_poll_expiration()
            await self._send_poll_error(interaction, "⚠️ Poll has already ended.")
            return False

        return True

    def _cancel_updater_if_needed(self):
        """
        Cancel the background updater_task if it is still running.
        """
        try:
            current = asyncio.current_task()
        except Exception:
            current = None
        if (
            self.updater_task
            and self.updater_task is not current
            and not self.updater_task.done()
        ):
            try:
                self.updater_task.cancel()
            except Exception:
                pass

    def _compute_results(self):
        """
        Compute result aggregates for the poll.
        """
        results = {opt: len(users) for opt, users in self.votes.items()}
        winners = []
        winner_text = ""
        if results:
            max_votes = max(results.values())
            winners = [opt for opt, count in results.items() if count == max_votes]
            if max_votes > 0:
                if len(winners) == 1:
                    winner_text = (
                        f"\n\n{MinoriEmojis['MinoriPray']} Polling for `{self.question}` ended. "
                        f"The highest vote goes to **{winners[0]}** with {max_votes} vote{'s' if max_votes != 1 else ''}."
                    )
                else:
                    winner_text = (
                        f"\n\n{MinoriEmojis['MinoriPray']} Polling for `{self.question}` ended. "
                        f"It's a tie between {', '.join(winners)} — each with {max_votes} votes."
                    )
            else:
                winner_text = (
                    f"\n\n{MinoriEmojis['MinoriWink']} Polling for `{self.question}` ended. "
                    "No votes were cast."
                )
        return results, winners, winner_text

    async def _persist_results(self, results, winners):
        """
        Persist final poll results to the database via record_poll_result.
        """
        try:
            await record_poll_result(
                self.pool,
                message_id=self.message.id if self.message else None,
                winners=winners,
                counts=results,
                total_votes=sum(results.values()),
            )
        except Exception as e:
            print(f"[Poll DB Save Error] {e}")

    async def _finalize_view(self, winner_text: str):
        """
        Update the Discord message to a closed view and optionally announce winners.
        """
        self.clear_items()
        if self.message:
            final_embed = self.make_poll_embed(closed=True)
            try:
                await self.message.edit(embed=final_embed, view=self)
            except Exception as e:
                print(f"[on_timeout] failed editing final embed: {e}")
            if winner_text:
                try:
                    await self.message.channel.send(winner_text)
                except Exception as e:
                    print(f"[on_timeout] failed sending winner_text: {e}")

    async def on_timeout(self):
        """
        Finalize a poll when it times out. Safe to call multiple times.
        """
        if self.ended:
            return
        self.ended = True
        self._cancel_updater_if_needed()
        results, winners, winner_text = self._compute_results()
        await self._persist_results(results, winners)
        await self._finalize_view(winner_text)

    async def select_callback(self, interaction: discord.Interaction):
        """
        Handler for a user selecting an option from the Select menu.
        """
        if not await self._ensure_poll_active(interaction):
            return

        try:
            idx = int(interaction.data["values"][0])
        except Exception:
            return await interaction.response.send_message(
                "⚠️ Invalid selection.", ephemeral=True
            )

        if idx < 0 or idx >= len(self.options):
            return await interaction.response.send_message(
                "⚠️ Invalid choice.", ephemeral=True
            )

        choice_label = self.options[idx]

        for opt in self.votes:
            self.votes[opt].discard(interaction.user.id)
        self.votes[choice_label].add(interaction.user.id)

        # Persist only the single vote change (no JSON blob rewrite)
        if self.message:
            try:
                await upsert_vote(self.pool, self.message.id, interaction.user.id, idx)
            except Exception as e:
                print(f"[Poll DB Save Error on vote] {e}")

        await self.update_poll(
            interaction, f"{CustomEmojis['VERIFIED']} You voted for **{choice_label}**"
        )

    async def add_option(self, interaction: discord.Interaction):
        """
        Initiate the AddOptionModal to let the poll author append options.
        """
        if not await self._ensure_poll_active(interaction):
            return

        if interaction.user.id != self.author.id:
            return await interaction.response.send_message(
                "⚠️ Only the poll creator can add options.", ephemeral=True
            )

        modal = AddOptionModal(self)
        await interaction.response.send_modal(modal)

    async def remove_vote(self, interaction: discord.Interaction):
        """
        Remove the invoking user's vote if present.
        """
        if not await self._ensure_poll_active(interaction):
            return

        removed = False
        for opt in self.votes:
            if interaction.user.id in self.votes[opt]:
                self.votes[opt].remove(interaction.user.id)
                removed = True

        if removed:
            if self.message:
                try:
                    await delete_vote(self.pool, self.message.id, interaction.user.id)
                except Exception as e:
                    print(f"[Poll DB Save Error on remove] {e}")
            await self.update_poll(interaction, "❌ Your vote was removed.")
        else:
            await interaction.response.send_message(
                "⚠️ You haven't voted yet.", ephemeral=True
            )

    async def end_poll(self, interaction: discord.Interaction):
        """
        Allow the poll author to end the poll immediately.
        """
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message(
                "⚠️ Only the poll creator can end this poll.", ephemeral=True
            )

        if self.updater_task and not self.updater_task.done():
            self.updater_task.cancel()

        await interaction.response.defer(ephemeral=True)
        await self.on_timeout()

    async def _respond_to_interaction(self, interaction: discord.Interaction, msg: str):
        """Helper to safely send the ephemeral confirmation."""
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)
        except Exception:
            pass

    async def _resend_poll_message(self, embed: discord.Embed):
        """Helper to send a new message if editing fails completely."""
        try:
            if self.message and self.message.channel:
                self.message = await self.message.channel.send(embed=embed, view=self)
        except Exception as ex:
            print(f"[update_poll] failed to send new message: {ex}")

    async def _recover_message_state(self, embed: discord.Embed):
        """Helper to attempt re-fetching the message before editing, falling back to resend."""
        try:
            if self.message and self.message.channel:
                self.message = await self.message.channel.fetch_message(self.message.id)
                await self.message.edit(embed=embed, view=self)
        except Exception:
            await self._resend_poll_message(embed)

    async def _retry_with_smaller_embeds(self) -> bool:
        """Helper to retry editing with smaller visual elements to satisfy size limits."""
        for bl in (8, 6, 4, 2):
            try:
                smaller_embed = self.make_poll_embed(bar_len=bl)
                if self.message:
                    await self.message.edit(embed=smaller_embed, view=self)
                return True
            except Exception:
                continue
        return False

    async def _handle_update_error(self, error: Exception, embed: discord.Embed):
        """Dispatches error handling logic based on exception type."""
        err_str = str(error).lower()
        if isinstance(error, discord.errors.HTTPException) and (
            "embed size" in err_str or "exceeds" in err_str
        ):
            if await self._retry_with_smaller_embeds():
                return

        # Fallback for non-size errors or if size retry failed
        await self._recover_message_state(embed)

    async def update_poll(self, interaction: discord.Interaction, ephemeral_msg: str):
        """
        Update the Discord message embed and respond to the interaction with an
        ephemeral confirmation.
        Refactored to reduce Cognitive Complexity.
        """
        embed = self.make_poll_embed()

        if self.message:
            try:
                await self.message.edit(embed=embed, view=self)
            except Exception as e:
                await self._handle_update_error(e, embed)
        else:
            # First time sending or lost reference
            try:
                self.message = await interaction.channel.send(embed=embed, view=self)
            except Exception:
                pass

        await self._respond_to_interaction(interaction, ephemeral_msg)

    def make_poll_embed(self, closed: bool = False, bar_len: int = 10):
        """
        Build and return a Discord embed representation of the poll.
        """
        total_votes = sum(len(v) for v in self.votes.values())
        colors = ["🟦", "🟥", "🟩", "🟨", "🟪", "🟧", "🟫"]

        embed = discord.Embed(
            title=f"{CustomEmojis['CHART']}  {self.question}",
            color=discord.Color.blurple(),
        )

        for i, (opt, users) in enumerate(self.votes.items(), 1):
            count = len(users)
            percent = (count / total_votes * 100) if total_votes > 0 else 0
            filled = int(percent / 100 * bar_len) if bar_len > 0 else 0
            empty = max(0, bar_len - filled)
            color = colors[i % len(colors)]
            bar = color * filled + f"{CustomEmojis['Gray_Large_Square']}" * empty

            embed.add_field(
                name=opt, value=f"{bar} `{percent:.0f}% ({count})`", inline=False
            )

        if closed:
            if self.end_time:
                status = (
                    f"{CustomEmojis['Locked']} Poll closed <t:{int(self.end_time.timestamp())}:R>\n"
                    f"{CustomEmojis['SecretBox']} Votes are anonymous\n"
                    f"With total of `{total_votes} votes`"
                )
            else:
                status = f"{CustomEmojis['Locked']} Poll closed\n{CustomEmojis['SecretBox']} Votes are anonymous\n{total_votes} votes"
        elif self.end_time:
            status = (
                f"{CustomEmojis['TIME']} Poll closes <t:{int(self.end_time.timestamp())}:R>\n"
                f"{CustomEmojis['SecretBox']} Votes are anonymous\n"
                f"Total Votes: `{total_votes}` votes"
            )
        else:
            status = (
                f"{CustomEmojis['SecretBox']} Votes are anonymous\n{total_votes} votes"
            )
        embed.add_field(name="\u200b", value=status, inline=False)
        return embed


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
