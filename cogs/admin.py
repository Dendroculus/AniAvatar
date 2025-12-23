import discord
from discord.ext import commands
from discord import app_commands
from utils.discord_helpers import create_choices

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

class AnnounceModal(discord.ui.Modal):
    def __init__(self, channel: discord.TextChannel, author: discord.Member, mention: bool):
        super().__init__(title="📢 Create Announcement")
        self.channel = channel
        self.author = author
        self.mention = mention

        """
        TextInput rationale:
        - paragraph style enables multi-line announcements suitable for detailed notices.
        - max_length is set to 4000 to align with Discord's message limits and prevent
          excessively long submissions that would inevitably fail when sending.
        - required=True enforces that the admin provides message content before submission.
        """
        self.message = discord.ui.TextInput(
            label="Announcement Message",
            style=discord.TextStyle.paragraph,
            placeholder="Type your announcement here",
            required=True,
            max_length=4000
        )
        self.add_item(self.message)

    async def on_submit(self, interaction: discord.Interaction):
        """
        Send the announcement composed in the modal.

        Behavior notes:
        - The interaction is deferred ephemerally so the modal UX closes immediately for the user
          and follow-up messages (success or failure) can be sent privately to the invoker.
        - The announcement content is constructed with an optional everyone mention prefix.
        - allowed_mentions is explicitly configured to prevent accidental pings from any mention-like
          substrings contained in the message body.
        - Exceptions are not swallowed; the raw exception is reported back to the admin ephemerally
          to aid in diagnosing permission issues, invalid channel types, or rate limit responses.
        """
        await interaction.response.defer(ephemeral=True)

        content = f"{'@everyone\n' if self.mention else ''}{self.message.value}"

        try:
            await self.channel.send(
                content=content,
                allowed_mentions=discord.AllowedMentions(everyone=self.mention)
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to send announcement: {e}", ephemeral=True)


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
    async def announce(self, ctx: commands.Context, mention: app_commands.Choice[str], channel: discord.TextChannel):
        """
        Open an announcement modal for authorized users.

        Security and UX:
        - Access is restricted to members with manage_guild to reduce misuse risk.
        - The 'mention' argument is parsed flexibly to support both slash and legacy inputs.
        - When invoked as a slash command (interaction present) a Modal is presented so the admin
          can compose multi-line announcements; legacy prefix usage is redirected to the slash form.
        """
        if not ctx.author.guild_permissions.manage_guild:
            if ctx.interaction:
                return await ctx.interaction.response.send_message(
                    "❌ You don’t have permission to use this command.", ephemeral=True
                )
            return await ctx.reply("❌ You don’t have permission to use this command.")

        mention_bool = mention.value == "yes"

        if ctx.interaction:
            modal = AnnounceModal(channel=channel, author=ctx.author, mention=mention_bool)
            return await ctx.interaction.response.send_modal(modal)

        return await ctx.reply(
            "❌ Please use the slash version of this command to open the modal.",
            mention_author=False
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))