import discord
from discord.ext import commands
import sqlite3
import os
import random
from PIL import Image, ImageDraw, ImageFont
import asyncio
import traceback
import io

COG_PATH = os.path.dirname(os.path.abspath(__file__))   # ...\AniAvatar\cogs
ROOT_PATH = os.path.dirname(COG_PATH)                   # ...\AniAvatar

FONT_DIR = os.path.join(ROOT_PATH, "assets", "fonts")
EMOJI_PATH = os.path.join(ROOT_PATH, "assets", "emojis", "RANK ICONS")

def render_profile_image(
    avatar_bytes: bytes,
    display_name: str,
    title_name: str,
    level: int,
    exp: int,
    next_exp: int,
    fonts: dict,
    title_emoji_files: dict,
) -> bytes:
    try:
        def _load_font(path, size):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                return ImageFont.load_default()

        font_username = _load_font(fonts["bold"], 32)
        font_medium = _load_font(fonts["medium"], 24)
        font_small = _load_font(fonts["regular"], 20)

        # base canvas with rounded rectangle
        width, height = 600, 260
        corner_radius = 30

        # transparent base
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))

        # mask for rounded rectangle
        mask = Image.new("L", (width, height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([0, 0, width, height], radius=corner_radius, fill=255)


        # solid light purple background
        base_bg = Image.new("RGBA", (width, height), (167, 139, 250, 255))  # dark purple

        # triangle overlay (darker purple at top-right corner)
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)

        # triangle coordinates (cover top-right corner)
        triangle = [(width//2, 0), (width, 0), (width, height//2)]
        overlay_draw.polygon(triangle, fill=(216, 180, 254, 255))  # light purple

        # combine background + triangle
        base_bg.alpha_composite(overlay)

        # apply rounded rectangle mask
        img.paste(base_bg, (0, 0), mask)

        draw = ImageDraw.Draw(img)

        # avatar
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((100, 100))
        img.paste(avatar, (20, 30), avatar)

        # starting position
        x, y = 140, 30

        # username
        draw.text((x, y), display_name, font=font_username, fill="white")
        y += 40

        # aligned labels
        title_label = "Title    :" 
        level_label = "Level  :" 
        exp_label   = "EXP    :"  

        # Title
        draw.text((x, y), title_label, font=font_medium, fill="white")
        label_width = draw.textlength(title_label, font=font_medium)
        value_x = x + label_width + 10
        draw.text((value_x, y), title_name, font=font_medium, fill="white")
        text_width = draw.textlength(title_name, font=font_medium)

        # Badge after title
        emoji_path = title_emoji_files.get(title_name)
        if emoji_path and os.path.exists(emoji_path):
            try:
                badge = Image.open(emoji_path).convert("RGBA").resize((26, 26))
                bx = int(value_x + text_width + 10)
                by = int(y + 5)
                img.paste(badge, (bx, by), badge)
            except Exception as e:
                print("❌ Badge paste failed:", e)
                traceback.print_exc()
        else:
            print("⚠️ No badge file found for:", title_name)

        y += 32

        # Level
        draw.text((x, y), level_label, font=font_medium, fill="white")
        label_width = draw.textlength(level_label, font=font_medium)
        value_x = x + label_width + 10
        draw.text((value_x, y), str(level), font=font_medium, fill="white")
        y += 32

        # EXP
        exp_text = (
            "∞" if next_exp == exp and next_exp != 0
            else f"{exp:,} / {next_exp:,}" if next_exp > 0
            else f"{exp:,}"
        )
        draw.text((x, y), exp_label, font=font_medium, fill="white")
        label_width = draw.textlength(exp_label, font=font_medium)
        value_x = x + label_width + 10
        draw.text((value_x, y), exp_text, font=font_medium, fill="white")
        y += 32

        # message line
        if next_exp > 0:
            exp_left = max(0, next_exp - exp)
            next_line = f"Gain {exp_left:,} more EXP to level up!"
        else:
            next_line = "You are at max level!"
        draw.text((x, y), next_line, font=font_small, fill=(200, 200, 200))
        y += 40

        # progress bar
        bar_x, bar_y = x, y
        bar_width, bar_height = width - bar_x - 40, 24
        progress = min(exp / next_exp, 1) if next_exp > 0 else 1

        draw.rounded_rectangle(
            [bar_x, bar_y, bar_x + bar_width, bar_y + bar_height],
            radius=12,
            fill=(30, 30, 30)
        )
        if progress > 0:
            draw.rounded_rectangle(
                [bar_x, bar_y, bar_x + int(bar_width * progress), bar_y + bar_height],
                radius=12,
                fill=(0, 200, 120)
            )

        # resize smaller (optional tweak)
        final_img = img.resize((390, 169), Image.Resampling.LANCZOS)

        # export as PNG bytes
        out = io.BytesIO()
        final_img.save(out, format="PNG")
        return out.getvalue()

    except Exception:
        traceback.print_exc()
        return None

    
FONTS = {
    "bold": os.path.join(FONT_DIR, "gg sans Bold.ttf"),
    "medium": os.path.join(FONT_DIR, "gg sans Medium.ttf"),
    "regular": os.path.join(FONT_DIR, "gg sans Regular.ttf"),
    "semibold": os.path.join(FONT_DIR, "gg sans Semibold.ttf"),
}

TITLE_EMOJI_FILES = {
    "Novice": os.path.join(EMOJI_PATH, "NOVICE.png"),
    "Warrior": os.path.join(EMOJI_PATH, "WARRIOR.png"),
    "Elite": os.path.join(EMOJI_PATH, "ELITE.png"),
    "Champion": os.path.join(EMOJI_PATH, "CHAMPION.png"),
    "Hero": os.path.join(EMOJI_PATH, "HERO.png"),
    "Legend": os.path.join(EMOJI_PATH, "LEGEND.png"),
    "Mythic": os.path.join(EMOJI_PATH, "MYTHIC.png"),
    "Ascendant": os.path.join(EMOJI_PATH, "ASCENDANT.png"),
    "Immortal": os.path.join(EMOJI_PATH, "IMMORTAL.png"),
    "Celestial": os.path.join(EMOJI_PATH, "CELESTIAL.png"),
    "Transcendent": os.path.join(EMOJI_PATH, "TRANSCENDENT.png"),
    "Aetherborn": os.path.join(EMOJI_PATH, "AETHERBORN.png"),
    "Cosmic": os.path.join(EMOJI_PATH, "COSMIC.png"),
    "Divine": os.path.join(EMOJI_PATH, "DIVINE.png"),
    "Eternal": os.path.join(EMOJI_PATH, "ETERNAL.png"),
    "Enlightened": os.path.join(EMOJI_PATH, "ENLIGHTENED.png"),
}

TITLE_COLORS = {
    "Novice": discord.Color.light_gray(),
    "Warrior": discord.Color.red(),
    "Elite": discord.Color.orange(),
    "Champion": discord.Color.gold(),
    "Hero": discord.Color.green(),
    "Legend": discord.Color.blue(),
    "Mythic": discord.Color.purple(),
    "Ascendant": discord.Color.teal(),
    "Immortal": discord.Color.dark_red(),
    "Celestial": discord.Color.dark_blue(),
    "Transcendent": discord.Color.dark_purple(),
    "Aetherborn": discord.Color.dark_teal(),
    "Cosmic": discord.Color.dark_magenta(),
    "Divine": discord.Color.green(),
    "Eternal": discord.Color.red(),
    "Enlightened": discord.Color.blue(),
}

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

def load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception as e:
        print(f"Font load failed for {path}: {e}")
        return ImageFont.load_default()
    
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
    
    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """Cleanup DB when bot is removed from a guild"""
        self.c.execute("DELETE FROM users WHERE guild_id = ?", (guild.id,))
        self.conn.commit()
        print(f"[Progression] Cleaned up DB for guild {guild.id} ({guild.name})")
        
    @commands.hybrid_command(name="profile", description="Check your level, EXP, and title")
    @commands.guild_only()
    async def profile(self, ctx, member: discord.Member = None):
        member = member or ctx.author

        try:
            exp, level = self.get_user(member.id, ctx.guild.id)
            title_name = get_title(level)

            # compute next_exp etc
            if level >= self.MAX_LEVEL:
                next_exp = exp
            else:
                next_exp = 50 * level + 20 * level**2

            # fetch avatar bytes (async)
            avatar_asset = member.display_avatar.with_size(128)
            buffer_avatar = io.BytesIO()
            await avatar_asset.save(buffer_avatar)   # this is async API
            buffer_avatar.seek(0)
            avatar_bytes = buffer_avatar.getvalue()

            # call the blocking render in a thread
            img_bytes = await asyncio.to_thread(
                render_profile_image,
                avatar_bytes,
                member.display_name,
                title_name,
                level,
                exp,
                next_exp,
                FONTS,
                TITLE_EMOJI_FILES,
            )

            # if rendering failed, report error and fallback to text embed (safe)
            if not img_bytes:
                await ctx.send("❌ Failed to generate profile image — check bot logs.")
                return

            file = discord.File(io.BytesIO(img_bytes), filename="profile.png")

            # If badge PNG doesn't exist, attach emoji in message content (so user still sees it)
            badge_path = TITLE_EMOJI_FILES.get(title_name)
            badge_text = ""
            if not (badge_path and os.path.exists(badge_path)):
                badge_text = get_title_emoji(level)

            content = f"{member.display_name} {badge_text}".strip()
            await ctx.send(content=content if badge_text else None, file=file)

        except Exception:
            # catch unexpected errors, log to console, notify user
            traceback.print_exc()
            await ctx.send("❌ Unexpected error while generating profile. Check console/logs.")



    @commands.hybrid_command(name="leaderboard", description="Show top levels in this server")
    @commands.guild_only()
    async def leaderboard(self, ctx):
        self.c.execute(
            """
            SELECT user_id, level, exp
            FROM users
            WHERE guild_id = ?
            AND ((exp > 0 AND level >= 1) OR level = ?)
            ORDER BY level DESC, exp DESC
            LIMIT 10
            """,
            (ctx.guild.id, self.MAX_LEVEL)
        )
        top_users = self.c.fetchall()
        if not top_users:
            return await ctx.send("No users found in the leaderboard.")

        embed = discord.Embed(
            title=f"{ctx.guild.name}'s Top 10 List 🏆",
            color=discord.Color.purple()
        )

        max_level_len = max(len(str(lvl)) for _, lvl, _ in top_users)
        max_exp_len = max(len(str(xp)) for _, _, xp in top_users if xp is not None)
        
        leaderboard_text = ""
        for idx, (user_id, level, exp) in enumerate(top_users, start=1):
            member = ctx.guild.get_member(user_id)
            name = member.display_name if member else f"User {user_id}"
            name = self.truncate(name, self.MAX_NAME_WIDTH)

            lvl_str = str(level).rjust(max_level_len)
            xp_str = "∞".rjust(max_exp_len) if level >= self.MAX_LEVEL else str(exp).rjust(max_exp_len)

            leaderboard_text += (
                f"```\n"
                f"{idx} • {name}\n"
                f"LVL {lvl_str} │ XP {xp_str}\n"
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
        
        old_level = level
        old_title = get_title(old_level)
        
        exp_gain = random.randint(5 + level * 8, 10 + level * 12)
        level, new_exp, leveled_up = self.add_exp(user_id, guild_id, exp_gain)

        new_rank = self.get_rank(user_id, guild_id)
        new_title = get_title(level)

        # Level-up message
        if leveled_up:
            old_emoji = get_title_emoji(old_level)
            new_emoji = get_title_emoji(level)
            new_title = get_title(level)

            if new_title != old_title:  # Ascension happened
                embed_title = f"{message.author.display_name} <:LEVELUP:1413479714428948551> {level}    {old_emoji} <:RIGHTWARDARROW:1414227272302334062> {new_emoji}"
                embed_description = (
                    f"```Congratulations {message.author.display_name}! You have reached level {level} and ascended to {new_title}. ```\n"
                    f"Title: `{new_title}`"
                )
            else:  # Normal level-up
                embed_title = f"{message.author.display_name} <:LEVELUP:1413479714428948551> {level}"
                embed_description = (
                    f"```Congratulations {message.author.display_name}! You have reached level {level}.```\n"
                    f"Title: `{new_title}`"
                )

            embed = discord.Embed(
                title=embed_title,
                description=embed_description,
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
            
        await self.bot.process_commands(message)
        
    def get_rank(self, user_id: int, guild_id: int):
        self.c.execute(
            "SELECT COUNT(*)+1 FROM users WHERE guild_id = ? AND (level > (SELECT level FROM users WHERE user_id = ? AND guild_id = ?) OR (level = (SELECT level FROM users WHERE user_id = ? AND guild_id = ?) AND exp > (SELECT exp FROM users WHERE user_id = ? AND guild_id = ?)))",
            (guild_id, user_id, guild_id, user_id, guild_id, user_id, guild_id)
        )
        return self.c.fetchone()[0]
    
    @commands.Cog.listener()
    async def on_ready(self):
        print(f"{self.bot.user} is ready!")

        YOUR_ID = [955268891125375036]
        GUILD_ID = 974498807817588756

        for user_id in YOUR_ID:
            level, exp, leveled_up = self.add_exp(user_id, GUILD_ID, 0)
            print(f"User {user_id} → Level {level}, EXP {exp}, Leveled up? {leveled_up}")

        print(f"🎉 You are now level {level} with {exp} EXP in guild {GUILD_ID}. Leveled up? {leveled_up}")
        


async def setup(bot):
    await bot.add_cog(Progression(bot))
    print("📦 Loaded progression cog.")



