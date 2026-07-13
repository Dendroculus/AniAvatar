"""Shared helpers for trading Discord views."""

from collections.abc import Callable

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
    """A reusable close button for trading views."""

    def __init__(
        self,
        owner_id: int,
        close_text: str,
        *,
        on_close: Callable[[], None],
        label: str = "Close",
    ) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.danger)
        self.owner_id = owner_id
        self.close_text = close_text
        self.on_close = on_close

    async def callback(self, interaction: discord.Interaction) -> None:
        """Close the menu when its owner clicks the button."""
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "⚠️ This is not your menu!",
                ephemeral=True,
            )
            return

        self.on_close()

        timeout_task = getattr(self.view, "_timeout_task", None)
        if timeout_task:
            timeout_task.cancel()

        await interaction.response.edit_message(
            content=self.close_text,
            embed=None,
            view=None,
        )
