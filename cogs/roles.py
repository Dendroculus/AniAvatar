import discord
from discord.ext import commands
from .progression import get_title, TITLE_COLORS

class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    async def update_roles(self, member: discord.Member, level: int):
        guild = member.guild
        title = get_title(level)
        
        role = discord.utils.get(guild.roles, name=title)
        
        if not role :
            color = TITLE_COLORS.get(title, discord.Color.default())
            role = await guild.create_role(name=title, color=color, reason="Auto created by AniAvatar")
            
        roles_to_remove = [r for r in member.roles if r.name in TITLE_COLORS.keys() and r !=role]
            
        if roles_to_remove :
            await member.remove_roles(*roles_to_remove)
            
        await member.add_roles(role, reason="Level update")
        
    @commands.Cog.listener()
    async def on_ready(self):
        print("Syncing progression roles..")
        progression = self.bot.get_cog("Progression")
        if not progression:
            print("Progression cog not found.")
            return
        
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot:
                    continue
                exp, level = progression.get_user(member.id, guild.id)
                await self.update_roles(member, level)
                
        print("Role sync complete.")
        
async def setup(bot):
    await bot.add_cog(Roles(bot))
    print("📦 Loaded roles cog.")