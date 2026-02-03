import discord
from discord.ext import commands
from discord import app_commands
from utils.discord_helpers import create_choices, is_admin
from utils.announce_modal import AnnounceModal

"""
Purpose:
Admin utility cog that lets authorized guild members create announcements via a Modal.

Design considerations:
- Security: mentions are explicit and controlled via discord.AllowedMentions to avoid
  accidental pings embedded in message content.
- UX: a Modal is used to allow multi-line, long-form announcements within Discord's
  modal constraints (max_length enforced).
- Observability: failures are surfaced to the invoking admin ephemerally so they can
  diagnose permission or delivery issues without spamming public channels.
"""

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _deny(self, ctx: commands.Context, message: str) -> None:
        """
        A small helper to send denial messages ephemerally based on context type.
        Security and UX:
        - Ephemeral responses prevent cluttering channels with denial messages.
        - Interaction checks ensure proper response methods are used.
        
        Args:
            ctx (commands.Context): The command context.
            message (str): The denial message to send.
        
        Returns:
            None
        """
        await ctx.send(message, ephemeral=True, mention_author=False)
            
    @commands.hybrid_command(
        name="announce",
        description="Announce something in a channel (Admin only, modal input)"
    )
    @app_commands.describe(
        mention="Choose whether to mention @everyone",
        channel="The channel where the announcement will be sent"
    )
    @app_commands.choices(mention=create_choices({"Yes": "yes", "No" : "no"}))
    @commands.guild_only()
    @is_admin()
    async def announce(self, ctx: commands.Context, mention: app_commands.Choice[str], channel: discord.TextChannel):
        """
        Open an announcement modal for authorized users.

        Security and UX:
        - Access is restricted to members with manage_guild to reduce misuse risk.
        - The 'mention' argument is parsed flexibly to support both slash and legacy inputs.
        - When invoked as a slash command (interaction present) a Modal is presented so the admin
          can compose multi-line announcements; legacy prefix usage is redirected to the slash form.
        """
        mention_bool = mention.value == "yes"

        if ctx.interaction:
            modal = AnnounceModal(channel=channel, author=ctx.author, mention=mention_bool)
            return await ctx.interaction.response.send_modal(modal)

        return await self._deny(
            ctx,
            "❌ Please use the slash version of this command to open the modal."
        )

    @announce.error
    async def announce_error(self, ctx: commands.Context, error: commands.CommandError):
        """
        Local error handler for the announce command to handle permission check failures.
        """
        if isinstance(error, commands.CheckFailure):
            await self._deny(ctx, "❌ You don’t have permission to use this command.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))