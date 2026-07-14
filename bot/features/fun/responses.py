"""Shared response routing for hybrid entertainment commands."""

from __future__ import annotations

from typing import Any, Optional

import discord
from discord.ext import commands


class ResponseMixin:
    async def _send(
        self,
        ctx: commands.Context,
        interaction: Optional[discord.Interaction],
        content: Optional[str] = None,
        *,
        ephemeral: bool = False,
        **kwargs: Any,
    ) -> Optional[discord.Message]:
        """
        Unified send helper for Context and Interaction flows.

        Handles the complexity of responding to an interaction that might
        already be deferred or responded to, falling back to standard context
        sending if necessary.

        Args:
            ctx (commands.Context): The command context.
            interaction (Optional[discord.Interaction]): The interaction object, if available.
            content (Optional[str]): The message content to send.
            ephemeral (bool): Whether the response should be ephemeral (interaction only).
            **kwargs: Additional arguments for the send method (embeds, views, etc).

        Returns:
            Optional[discord.Message]: The sent message object, if retrievable.
        """
        if interaction:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        content, ephemeral=ephemeral, **kwargs
                    )
                    try:
                        return await interaction.original_response()
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        return None
                return await interaction.followup.send(
                    content, ephemeral=ephemeral, **kwargs
                )
            except (discord.HTTPException, discord.Forbidden, discord.NotFound):
                kwargs.pop("ephemeral", None)
                return await ctx.send(content, **kwargs)
        kwargs.pop("ephemeral", None)
        return await ctx.send(content, **kwargs)
