import discord
from discord.ext import commands
from discord import ui, ButtonStyle
from utils.emojis import MinoriEmojis, CustomEmojis

class DeleteView(ui.View):
    def __init__(self, user, timeout = None):
        super().__init__(timeout=timeout)
        self.user = user
        
    @discord.ui.button(label="Delete", style=ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, _: discord.ui.Button): # _ is the button instance to avoid unused variable warning
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("You can't delete someone else's message.", ephemeral=True)
        
        await interaction.response.defer()
        try:
            await interaction.message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.hybrid_command(name="ping", description="Shows bot latency")
    async def ping(self, ctx):
        latency = round(self.bot.latency * 1000)
        await ctx.send(f"{CustomEmojis['PINGPONG']} Pong! `{latency}ms`")
    
    @commands.hybrid_command(name="help", description="Show bot commands")
    async def help(self, ctx):
        embed = discord.Embed(
            title=f" {MinoriEmojis['MinoriWink']} Minori - your anime profile & fun companion!",
            description="Here’s a list of available commands, organized by category.",
            color=discord.Color.purple()
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        for cog_name, cog in self.bot.cogs.items():
            commands_list = []
            for command in cog.get_commands():
                if not command.hidden:
                    commands_list.append(f"`/{command.name}` - {command.description or 'No description'}")

            if commands_list:  # Only show if cog has commands
                embed.add_field(
                    name=f"{cog_name}",
                    value="\n".join(commands_list),
                    inline=False
                )

        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        view = DeleteView(user=ctx.author)
        await ctx.send(embed=embed, view=view)
    
async def setup(bot):
    await bot.add_cog(General(bot))
