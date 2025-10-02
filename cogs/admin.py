import discord
from discord.ext import commands
from discord import app_commands

class AnnounceModal(discord.ui.Modal):
    def __init__(self, channel: discord.TextChannel, author: discord.Member):
        super().__init__(title="📢 Create Announcement")
        self.channel = channel
        self.author = author
        self.message = discord.ui.TextInput(
            label="Announcement Message",
            style=discord.TextStyle.paragraph,
            placeholder="Type your announcement here...",
            required=True,
            max_length=4000
        )
        self.add_item(self.message)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        content = f"@everyone\n{self.message.value}"
        try:
            await self.channel.send(content=content, allowed_mentions=discord.AllowedMentions(everyone=True))
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to send announcement: {e}", ephemeral=True)

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="announce", description="Announce something in a channel (Admin only, modal input)")
    @app_commands.describe(channel="The channel where the announcement will be sent")
    @commands.guild_only()
    async def announce(self, ctx: commands.Context, channel: discord.TextChannel):
        if not ctx.author.guild_permissions.manage_guild:
            if ctx.interaction:
                return await ctx.interaction.response.send_message("❌ You don’t have permission to use this command.", ephemeral=True)
            return await ctx.reply("❌ You don’t have permission to use this command.")
        if ctx.interaction:
            modal = AnnounceModal(channel=channel, author=ctx.author)
            return await ctx.interaction.response.send_modal(modal)
        return await ctx.reply("❌ Please use the slash version of this command to open the modal.", mention_author=False)

async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
