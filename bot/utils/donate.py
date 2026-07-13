"""Discord UI for donating trading inventory items."""

from __future__ import annotations

import discord

from bot.features.trading.donation_service import (
    DonationService,
)


class DonateAmountModal(discord.ui.Modal):
    """Collect the quantity of an item to donate."""

    def __init__(
        self,
        item_name: str,
        max_amount: int | None,
        parent_view: DonateView,
    ) -> None:
        super().__init__(title=f"Donate {item_name}")

        self.item_name = item_name
        self.max_amount = max_amount
        self.parent_view = parent_view

        self.amount_input = discord.ui.TextInput(
            label="Amount",
            placeholder=(f"Max {max_amount}" if max_amount else "Enter amount"),
            style=discord.TextStyle.short,
        )

        self.add_item(self.amount_input)

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Validate and submit the donation amount."""
        try:
            amount = int(self.amount_input.value)
        except (TypeError, ValueError):
            await self.parent_view.edit_message(
                interaction,
                content="? Invalid number.",
            )
            return

        if amount <= 0:
            await self.parent_view.edit_message(
                interaction,
                content=("? Amount must be at least 1."),
            )
            return

        if self.max_amount is not None and amount > self.max_amount:
            await self.parent_view.edit_message(
                interaction,
                content=(
                    f"? You can only donate up to {self.max_amount} of this item."
                ),
            )
            return

        await self.parent_view.finalize_donate_callback(
            self.item_name,
            amount,
            interaction,
        )


class DonateSelect(discord.ui.Select):
    """Select which inventory item to donate."""

    def __init__(
        self,
        options: list[discord.SelectOption],
        caps: dict[str, int],
    ) -> None:
        super().__init__(
            placeholder="Select an item to donate",
            min_values=1,
            max_values=1,
            options=options,
        )

        self.caps = caps

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Open the amount modal or donate one item."""
        selected_item = self.values[0]
        max_cap = self.caps.get(selected_item)

        if max_cap == 1:
            await self.view.finalize_donate_callback(
                selected_item,
                1,
                interaction,
            )
            return

        await interaction.response.send_modal(
            DonateAmountModal(
                selected_item,
                max_cap,
                self.view,
            )
        )


class DonateView(discord.ui.View):
    """Coordinate the item-donation interaction."""

    def __init__(
        self,
        *,
        author_id: int,
        donation_service: DonationService,
        donor_id: int,
        receiver_id: int,
        guild_id: int,
        items: list[tuple[str, int, str]],
        timeout: float = 180,
    ) -> None:
        super().__init__(timeout=timeout)

        self.author_id = author_id
        self.donation_service = donation_service
        self.donor_id = donor_id
        self.receiver_id = receiver_id
        self.guild_id = guild_id
        self.items = items
        self.message: discord.Message | None = None

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        """Allow only the menu owner to donate."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                ("?? This is not your donate menu!"),
                ephemeral=True,
            )
            return False

        return True

    async def edit_message(
        self,
        interaction: discord.Interaction,
        *,
        content: str,
    ) -> None:
        """Edit the donation message safely."""
        if not interaction.response.is_done():
            await interaction.response.edit_message(
                content=content,
                view=self,
            )
            return

        if self.message is not None:
            await self.message.edit(
                content=content,
                view=self,
            )
            return

        await interaction.followup.send(
            content,
            ephemeral=True,
        )

    async def finalize_donate_callback(
        self,
        item_name: str,
        amount: int,
        interaction: discord.Interaction,
    ) -> None:
        """Transfer the selected item and update the UI."""
        result = await self.donation_service.transfer_item(
            donor_id=self.donor_id,
            receiver_id=self.receiver_id,
            guild_id=self.guild_id,
            item_name=item_name,
            amount=amount,
        )

        if not result.success:
            await self.edit_message(
                interaction,
                content=("? You don't have enough of this item."),
            )
            return

        for child in self.children:
            child.disabled = True

        emoji = next(
            (
                item_emoji
                for (
                    name,
                    _,
                    item_emoji,
                ) in self.items
                if name == item_name
            ),
            "??",
        )

        member = (
            interaction.guild.get_member(self.receiver_id)
            if interaction.guild
            else None
        )

        receiver_name = member.display_name if member else "User"

        await self.edit_message(
            interaction,
            content=(f"You donated {amount}x {emoji} {item_name} to {receiver_name}!"),
        )
