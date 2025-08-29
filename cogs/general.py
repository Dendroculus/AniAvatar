import discord
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.hybrid_command(name="ping", description="Shows bot latency")
    async def ping(self, ctx):
        latency = round(self.bot.latency * 1000)
        await ctx.send(f"🏓 Pong! `{latency}ms`")
    
    @commands.hybrid_command(name="help", description="Show bot commands")
    async def help(self, ctx):
        embed = discord.Embed(
            title="✨ AniAvatar Help",
            description="Here’s a list of available commands, organized by category.",
            color=discord.Color.purple()
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        # Loop through all cogs
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

        await ctx.send(embed=embed)
    
async def setup(bot):
    await bot.add_cog(General(bot))
    print("📦 Loaded general cog.")