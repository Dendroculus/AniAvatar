import discord
from discord.ext import commands, tasks
from .progression import get_title, TITLE_COLORS

class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sync_roles_loop.start()  # start the loop

    async def update_roles(self, member: discord.Member, level: int):
        guild = member.guild
        title = get_title(level)
        
        role = discord.utils.get(guild.roles, name=title)
        
        if not role:
            color = TITLE_COLORS.get(title, discord.Color.default())
            role = await guild.create_role(name=title, color=color, reason="Auto created by AniAvatar")
            
        roles_to_remove = [r for r in member.roles if r.name in TITLE_COLORS.keys() and r != role]
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)
            
        await member.add_roles(role, reason="Level update")

    @tasks.loop(minutes=2)
    async def sync_roles_loop(self):
        progression = self.bot.get_cog("Progression")
        if not progression:
            print("Progression cog not found for sync loop.")
            return

        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot:
                    continue
                exp, level = progression.get_user(member.id, guild.id)
                await self.update_roles(member, level)
        print("Periodic role sync complete.")

    @sync_roles_loop.before_loop
    async def before_sync_roles(self):
        await self.bot.wait_until_ready()
        print("Started periodic role sync loop.")

    @commands.Cog.listener()
    async def on_ready(self):
        print("Syncing progression roles on startup..")
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

        print("Startup role sync complete.")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles != after.roles:
            progression = self.bot.get_cog("Progression")
            if not progression:
                return
            exp, level = progression.get_user(after.id, after.guild.id)
            await self.update_roles(after, level)
            
async def setup(bot):
    await bot.add_cog(Roles(bot))
    print("📦 Loaded roles cog.")
