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
    elif level < 50: return "Immortal"
    elif level < 60: return "Celestial"
    elif level < 70: return "Transcendent"
    elif level < 80: return "Aetherborn"
    elif level < 90: return "Cosmic"
    elif level < 100: return "Divine"
    elif level < 125: return "Eternal"
    else: return "Enlightened"

def get_title_emoji(level: int):
    if level < 5: return "<:NOVICE:1413497054642307153>"
    elif level < 10: return "<:WARRIOR:1413545369966608465>"
    elif level < 15: return "<:ELITE:1413735235379658812>"
    elif level < 20: return "<:CHAMPION:1413738197246152834>"
    elif level < 25: return "<:HERO:1413742569304752170>"
    elif level < 30: return "<:LEGEND:1413748431599698071>"
    elif level < 35: return "<:MYTHIC:1413749422524989450>"
    elif level < 40: return "<:ASCENDANT:1413754160410660864>"
    elif level < 50: return "<:IMMORTAL:1413848406161621103>"
    elif level < 60: return "<:CELESTIAL:1413858244144660532>"
    elif level < 70: return "<:TRANSCENDENT:1413862700299194561>"
    elif level < 80: return "<:AETHERBORN:1413863769825869856>"
    elif level < 90: return "<:COSMIC:1413864596661338172>"
    elif level < 100: return "<:DIVINE:1413865527050506311>"
    elif level < 125: return "<:ETERNAL:1413824371994136598>"
    else: return "<:ENLIGHTENED:1413866534605951079>"
    
class Progression(commands.Cog):
    MAX_LEVEL = 150
    MAX_BOX_WIDTH = 50
    MAX_NAME_WIDTH = 20
    MAX_EXP_WIDTH = 12

    def __init__(self, bot):
        self.bot = bot
        self.cooldowns = {}
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

    def truncate(self, text: str, max_len: int):
        return text if len(text) <= max_len else text[:max_len - 3] + "..."

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

        while level < self.MAX_LEVEL:
            next_exp = 50 * level + 20 * level**2
            if new_exp >= next_exp:
                new_exp -= next_exp
                level += 1
                leveled_up = True
            else:
                break

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
        title = get_title(level)

        if level >= self.MAX_LEVEL:
            exp_line = f"EXP     : ∞"
            line = "You are already at max level! "
        else:
            next_exp = 50 * level + 20 * level**2
            exp_left = next_exp - exp
            exp_line = f"EXP     : {exp}/{next_exp}"
            line = f"Gain {exp_left} more EXP to level up!"

        title_emoji = get_title_emoji(level)    
        
        embed = discord.Embed(
            title=f"{member.display_name}'s Profile  {title_emoji}",
            color=discord.Color.purple()
        )
        title_line = f"Title   : {title}"
        level_line = f"Level   : {level}"

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
            "SELECT user_id, level, exp FROM users WHERE guild_id = ? AND (exp > 0 and level >= 1) ORDER BY level DESC, exp DESC LIMIT 10",
            (ctx.guild.id,)
        )
        top_users = self.c.fetchall()
        if not top_users:
            return await ctx.send("No users found in the leaderboard.")

        embed = discord.Embed(
            title=f"{ctx.guild.name}'s Top 10 List 🏆",
            color=discord.Color.purple()
        )

        leaderboard_text = ""
        for idx, (user_id, level, exp) in enumerate(top_users, start=1):
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f"User {user_id}"
            name = self.truncate(name, self.MAX_NAME_WIDTH)

            exp_str = "∞" if level >= self.MAX_LEVEL else str(exp)
            exp_str = self.truncate(exp_str, self.MAX_EXP_WIDTH)

            # Each entry in its own code block
            leaderboard_text += (
                f"```\n"
                f"{idx} • {name}\n"
                f"LVL {level} │ XP {exp_str}\n"
                f"```\n"
            )

        embed.description = leaderboard_text

        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)

        await ctx.send(embed=embed)


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        user_id = message.author.id

        cooldown = 5
        last_time = self.cooldowns.get((guild_id, user_id), 0)
        now = discord.utils.utcnow().timestamp()
        if now - last_time < cooldown:
            return
        self.cooldowns[(guild_id, user_id)] = now

        old_rank = self.get_rank(user_id, guild_id)

        # Scaled EXP gain (random 5-15)
        exp, level = self.get_user(user_id, guild_id)
        exp_gain = random.randint(5 + level * 8, 10 + level * 12)
        level, new_exp, leveled_up = self.add_exp(user_id, guild_id, exp_gain)

        new_rank = self.get_rank(user_id, guild_id)

        # Level-up message
        if leveled_up:
            title = get_title(level)
            next_exp = 50 * level + 20 * level**2 if level < self.MAX_LEVEL else "∞"
            embed = discord.Embed(
                title=f"{message.author.display_name} <:LEVELUP:1413479714428948551> {level}",
                description=f"```Congratulations {message.author.display_name}! You have reached level {level}.```\nTitle: `{title}`",
                color=discord.Color.green()
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)
            await message.channel.send(embed=embed)

        # Rank-up message
        if new_rank < old_rank:
            embed = discord.Embed(
                title=f"<:LEVELUP:1413479714428948551> Rank Up! {message.author.display_name}",
                description=f"```{message.author.display_name} has ranked up to #{new_rank} in the server leaderboard! 🎉```",
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
    
    # @commands.Cog.listener()
    # async def on_ready(self):
    #     print(f"{self.bot.user} is ready!")

    #     YOUR_ID = [955268891125375036]
    #     GUILD_ID = 974498807817588756

    #     for user_id in YOUR_ID:
    #         level, exp, leveled_up = self.add_exp(user_id, GUILD_ID, 400)
    #         print(f"User {user_id} → Level {level}, EXP {exp}, Leveled up? {leveled_up}")

    #     print(f"🎉 You are now level {level} with {exp} EXP in guild {GUILD_ID}. Leveled up? {leveled_up}")
        

async def setup(bot):
    await bot.add_cog(Progression(bot))
    print("📦 Loaded progression cog.")

