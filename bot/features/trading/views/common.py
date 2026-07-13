"""Shared helpers for trading Discord views."""

import discord


def format_coins(coins: int) -> str:
    """
    Format a coin integer into a compact human-readable string.
    """
    if coins < 1_000:
        return str(coins)
    elif coins < 1_000_000:
        return f"{coins / 1_000:.2f}K".rstrip("0").rstrip(".")
    elif coins < 1_000_000_000:
        return f"{coins / 1_000_000:.2f}M".rstrip("0").rstrip(".")
    else:
        return f"{coins / 1_000_000_000:.2f}B".rstrip("0").rstrip(".")


class CloseButton(discord.ui.Button):
    """
    A reusable 'Close' button for shop and inventory views.
    """

    def __init__(
        self,
        owner_id: int,
        close_text: str,
        label: str = "Close",
        menu_type: str = None,
        cog=None,
        guild_id: int = None,
    ):
        self.guild_id = guild_id
        super().__init__(label=label, style=discord.ButtonStyle.danger)
        self.owner_id = owner_id
        self.close_text = close_text
        self.menu_type = menu_type
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        """Handle button click to close the menu."""
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "⚠️ This is not your menu!", ephemeral=True
            )
            return

        if self.menu_type == "shop":
            self.cog.open_shops.get(self.guild_id, {}).pop(self.owner_id, None)
        elif self.menu_type == "inventory":
            self.cog.open_inventories.get(self.guild_id, {}).pop(self.owner_id, None)

        t = getattr(self.view, "_timeout_task", None)
        if t:
            t.cancel()

        await interaction.response.edit_message(
            content=self.close_text, embed=None, view=None
        )
