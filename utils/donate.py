import discord
class DonateAmountModal(discord.ui.Modal):
    """Modal for entering donation amount."""
    def __init__(self, item_name, max_amount, parent_view):
        super().__init__(title=f"Donate {item_name}")
        self.item_name = item_name
        self.max_amount = max_amount
        self.parent_view = parent_view
        self.amount_input = discord.ui.TextInput(
            label="Amount",
            placeholder=f"Max {max_amount}" if max_amount else "Enter amount",
            style=discord.TextStyle.short
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount_input.value)
        except (ValueError, TypeError):
            await interaction.response.edit_message(content="❌ Invalid number.", view=self.parent_view)
            return

        if amt <= 0:
            await interaction.response.edit_message(content="❌ Amount must be at least 1.", view=self.parent_view)
            return
        if self.max_amount is not None and amt > self.max_amount:
            await interaction.response.edit_message(
                content=f"❌ You can only donate up to {self.max_amount} of this item.", 
                view=self.parent_view
            )
            return

        await self.parent_view.finalize_donate_callback(self.item_name, amt, interaction)

class DonateSelect(discord.ui.Select):
    """Dropdown menu for selecting donation item."""
    def __init__(self, options, caps):
        super().__init__(placeholder="Select an item to donate", min_values=1, max_values=1, options=options)
        self.caps = caps

    async def callback(self, interaction: discord.Interaction):
        selected_item = self.values[0]
        max_cap = self.caps.get(selected_item, None)

        if max_cap == 1:
            await self.view.finalize_donate_callback(selected_item, 1, interaction)
        else:
            await interaction.response.send_modal(DonateAmountModal(selected_item, max_cap, self.view))

class DonateView(discord.ui.View):
    """View for handling donation interaction."""
    def __init__(self, author_id, cog, donor_id, receiver_id, guild_id, items, timeout=180):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.cog = cog
        self.donor_id = donor_id
        self.receiver_id = receiver_id
        self.guild_id = guild_id
        self.items = items
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("⚠️ This is not your donate menu!", ephemeral=True)
            return False
        return True

    async def finalize_donate_callback(self, item_name: str, amount: int, interaction: discord.Interaction):
        """Delegate logic to cog helper to keep View clean."""
        await self.cog._execute_donation(
            interaction, self, item_name, amount, 
            self.donor_id, self.receiver_id, self.guild_id, self.items
        )