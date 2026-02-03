import discord
from discord.ext import commands
from services.user_repository import UserRepository
from constants.configs import OWNER_ID

class DevCommands(commands.Cog):
    """
    Developer tools for testing and state manipulation.
    Strictly restricted to the bot owner.
    """
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        """
        Global check for this Cog: only allows the specific OWNER_ID to use commands.
        """
        if ctx.author.id != OWNER_ID:
            await ctx.send("❌ You do not have permission to use this command.", ephemeral=True)
            return False
        return True
        
    @commands.hybrid_command(name="manipulate_profile", description="Dev: Modify coins and EXP for a user.")
    async def manipulate_profile(
        self, 
        ctx: commands.Context, 
        target: discord.Member, 
        coins: int = 0, 
        exp: int = 0
    ):
        """
        Dynamically add Coins and EXP to any user.
        
        Args:
            target: The user to modify.
            coins: Amount of coins to add (can be negative).
            exp: Amount of EXP to add.
        """
        if not self.bot.pool:
            return await ctx.send("❌ Database pool is not initialized.")

        repo = UserRepository(self.bot.pool)
        guild_id = ctx.guild.id

        if coins != 0:
            if coins > 0:
                await repo.add_coins(target.id, guild_id, coins)
            else:
                await repo.remove_coins(target.id, guild_id, abs(coins))

        leveled_up = False
        
        current_coins = await repo.get_coins(target.id, guild_id)
        current_exp, current_level = await repo.get_user(target.id, guild_id)

        embed = discord.Embed(
            title="🛠️ Developer Update",
            description=f"Updated profile for **{target.display_name}**",
            color=discord.Color.red()
        )
        embed.add_field(name="Coins", value=f"{current_coins:,} ({'+' if coins > 0 else ''}{coins})", inline=True)
        embed.add_field(name="Level", value=f"{current_level} (Leveled Up: {leveled_up})", inline=True)
        embed.add_field(name="EXP", value=f"{current_exp:,} (+{exp})", inline=True)

        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(DevCommands(bot))