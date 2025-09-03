import discord
from discord.ext import commands
import sqlite3
import os
import random

def get_title(level: int):
    if level < 5: return "Novice"
    elif level < 10: return "Warrior"
    elif level < 15: return "Elite"
    elif level < 20: return "Champion"
    elif level < 25: return "Hero"
    elif level < 30: return "Legend"
    elif level < 35: return "Mythic"
    elif level < 40: return "Ascendant"
    else: return "Eternal"

class Profile(commands.Cog):
    MAX_LEVEL = 100

    def __init__(self, bot):
        self.bot = bot
        data_path = os.path.join(os.path.dirname(__file__), "..", "data", "aniavatar.db")
        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        data_path = os.path.abspath(data_path)
        self.conn = sqlite3.connect(data_path)
        self.c = self.conn.cursor()
        self.c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER,
                guild_id INTEGER,
                exp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        self.conn.commit()

    def get_user(self, user_id: int, guild_id: int):
        self.c.execute(
            "SELECT exp, level FROM users WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        result = self.c.fetchone()
        if result is None:
            self.c.execute(
                "INSERT INTO users (user_id, guild_id) VALUES (?, ?)",
                (user_id, guild_id)
            )
            self.conn.commit()
            return 0, 1
        return result

    def add_exp(self, user_id: int, guild_id: int, amount: int):
        exp, level = self.get_user(user_id, guild_id)
        new_exp = exp + amount
        leveled_up = False

        while new_exp >= level * 100 and level < self.MAX_LEVEL:
            new_exp -= level * 100
            level += 1
            leveled_up = True

        if level >= self.MAX_LEVEL:
            level = self.MAX_LEVEL
            new_exp = 0

        self.c.execute(
            "UPDATE users SET exp = ?, level = ? WHERE user_id = ? AND guild_id = ?",
            (new_exp, level, user_id, guild_id)
        )
        self.conn.commit()
        return level, new_exp, leveled_up

    @commands.hybrid_command(name="profile", description="Check your level, EXP, and title")
    async def profile(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        exp, level = self.get_user(member.id, ctx.guild.id)
        next_exp = level * 100
        title = get_title(level)
        exp_left = next_exp - exp

        embed = discord.Embed(
            title=f"{member.display_name}'s Profile",
            color=discord.Color.purple()
        )
        title_line = f"Title   : {title}"
        level_line = f"Level   : {level}"
        exp_line = f"EXP     : {exp}/{next_exp}"
        line = f"Gain {exp_left} more EXP to level up! "

        max_box_width = 50  # adjustable by preference

        def truncate(text):
            return text if len(text) <= max_box_width else text[:max_box_width - 3] + "..."

        title_line = truncate(title_line)
        level_line = truncate(level_line)
        exp_line = truncate(exp_line)
        line = truncate(line)

        max_length = max(len(title_line), len(level_line), len(exp_line), len(line))

        embed.description = (
            f"```\n"
            f"┌{'─' * max_length}┐\n"
            f"│{title_line.ljust(max_length)}│\n"
            f"├{'─' * max_length}┤\n"
            f"│{level_line.ljust(max_length)}│\n"
            f"│{exp_line.ljust(max_length)}│\n"
            f"│{line.ljust(max_length)}│\n"
            f"└{'─' * max_length}┘\n"
            f"```"
        )

        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)


    @commands.hybrid_command(name="leaderboard", description="Show top levels in this server")
    async def leaderboard(self, ctx):
        self.c.execute(
            "SELECT user_id, level, exp FROM users WHERE guild_id = ? ORDER BY level DESC, exp DESC LIMIT 10",
            (ctx.guild.id,)
        )
        top_users = self.c.fetchall()
        text = f"Toplist for {ctx.guild.name} | This year | By total XP\n"
        for idx, (user_id, level, exp) in enumerate(top_users, start=1):
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f"User ID: {user_id}"
            text += f"#{idx} {name} {level}\nTotal: {exp} XP\n"
        await ctx.send(f"```\n{text}\n```")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        user_id = message.author.id

        old_rank = self.get_rank(user_id, guild_id)

        exp_gain = random.randint(5, 15)
        level, new_exp, leveled_up = self.add_exp(user_id, guild_id, exp_gain)

        new_rank = self.get_rank(user_id, guild_id)

        if leveled_up:
            title = get_title(level)
            next_exp = level * 100
            embed = discord.Embed(
                title=f"📈 Level Up! {message.author.display_name}",
                description=f"Congratulations {message.author.mention}! You have reached **level {level}**.\nTitle: **`{title}`**",
                color=discord.Color.green()
            )
            embed.add_field(name="Level", value=f"`{str(level)}`")
            embed.add_field(name="EXP", value=f"`{new_exp}/{next_exp}`")
            embed.set_thumbnail(url=message.author.display_avatar.url)
            await message.channel.send(embed=embed)

        if new_rank < old_rank:
            embed = discord.Embed(
                title=f"🏆 Rank Up! {message.author.display_name}",
                description=f"{message.author.mention} has ranked up to **#{new_rank}** in the server leaderboard! 🎉",
                color=discord.Color.gold()
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)
            await message.channel.send(embed=embed)

    def get_rank(self, user_id: int, guild_id: int):
        self.c.execute(
            "SELECT COUNT(*)+1 FROM users WHERE guild_id = ? AND (level > (SELECT level FROM users WHERE user_id = ? AND guild_id = ?) OR (level = (SELECT level FROM users WHERE user_id = ? AND guild_id = ?) AND exp > (SELECT exp FROM users WHERE user_id = ? AND guild_id = ?)))",
            (guild_id, user_id, guild_id, user_id, guild_id, user_id, guild_id)
        )
        return self.c.fetchone()[0]

async def setup(bot):
    await bot.add_cog(Profile(bot))
    print("📦 Loaded profile cog.")
