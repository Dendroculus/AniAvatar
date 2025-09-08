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
BG_PATH = os.path.join(ROOT_PATH, "assets", "backgrounds")

THEMES = ["Galaxy", "Cyberpunk", "Minimal", "Sakura", "Nature"]

def render_profile_image(
    avatar_bytes: bytes,
    display_name: str,
    title_name: str,
    level: int,
    exp: int,
    next_exp: int,
    fonts: dict,
    title_emoji_files: dict,
    bg_file: str = "GALAXY.PNG",
    theme_name: str = "galaxy",
    font_color: str = "white",
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

        width, height = 600, 260
        corner_radius = 35

        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        mask = Image.new("L", (width, height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([0, 0, width, height], radius=corner_radius, fill=255)

        # Use user-selected theme folder dynamically
        bg_path = os.path.join(BG_PATH, theme_name.lower(), bg_file)
        if os.path.exists(bg_path):
            bg = Image.open(bg_path).convert("RGBA").resize((width, height))
        else:
            bg = Image.new("RGBA", (width, height), (167, 139, 250, 255))

        img.paste(bg, (0, 0), mask)

        draw = ImageDraw.Draw(img)

        # Avatar
        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((100, 100))
        img.paste(avatar, (20, 30), avatar)

        x, y = 140, 30
        draw.text((x, y), display_name, font=font_username, fill=font_color)
        y += 40

        title_label = "Title    :" 
        level_label = "Level  :" 
        exp_label   = "EXP    :"

        draw.text((x, y), title_label, font=font_medium, fill=font_color)
        label_width = draw.textlength(title_label, font=font_medium)
        value_x = x + label_width + 10
        draw.text((value_x, y), title_name, font=font_medium, fill=font_color)
        text_width = draw.textlength(title_name, font=font_medium)

        # Badge
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

        y += 32
        draw.text((x, y), level_label, font=font_medium, fill=font_color)
        label_width = draw.textlength(level_label, font=font_medium)
        value_x = x + label_width + 10
        draw.text((value_x, y), str(level), font=font_medium, fill=font_color)
        y += 32

        exp_text = (
            "∞" if next_exp == exp and next_exp != 0
            else f"{exp:,} / {next_exp:,}" if next_exp > 0
            else f"{exp:,}"
        )
        draw.text((x, y), exp_label, font=font_medium, fill=font_color)
        label_width = draw.textlength(exp_label, font=font_medium)
        value_x = x + label_width + 10
        draw.text((value_x, y), exp_text, font=font_medium, fill=font_color)
        y += 32

        next_line = f"Gain {max(0, next_exp - exp):,} more EXP to level up!" if next_exp > 0 else "You are at max level!"
        draw.text((x, y), next_line, font=font_small, fill=(200, 200, 200))
        y += 40

        bar_x, bar_y = x, y
        bar_width, bar_height = width - bar_x - 40, 24
        progress = min(exp / next_exp, 1) if next_exp > 0 else 1

        draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_width, bar_y + bar_height], radius=12, fill=(30, 30, 30))
        if progress > 0:
            draw.rounded_rectangle([bar_x, bar_y, bar_x + int(bar_width * progress), bar_y + bar_height], radius=12, fill=(0, 200, 120))

        final_img = img.resize((360, 165), Image.Resampling.LANCZOS)
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
    
class MainThemeSelect(discord.ui.Select):
    def __init__(self, user_id, cog):
        self.user_id = user_id
        self.cog = cog
        self.folders = [folder for folder in os.listdir(BG_PATH) if os.path.isdir(os.path.join(BG_PATH, folder))]
        options = [
            discord.SelectOption(label=folder.capitalize(), description=f"Choose {folder.capitalize()} theme")
            for folder in self.folders
        ]
        super().__init__(placeholder="Select a theme...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        idx = self.values[0].lower()  # label selected by user
        selected_theme = next(f for f in self.folders if f.lower() == idx)
        await interaction.response.send_message(
            f"✅ You selected **{selected_theme.capitalize()}**! Now pick a background:",
            view=SubThemeView(self.user_id, selected_theme, self.cog),
            ephemeral=True
        )

        
class MainThemeView(discord.ui.View):
    def __init__(self, user_id, cog):
        super().__init__()
        self.cog = cog
        self.add_item(MainThemeSelect(user_id, cog))

class SubThemeSelect(discord.ui.Select):
    def __init__(self, user_id, theme, cog):
        self.theme = theme
        self.cog = cog
        theme_path = os.path.join(BG_PATH, theme)

        # List all image files
        files = [f for f in os.listdir(theme_path) if f.lower().endswith((".png", ".jpg", ".jpeg"))]

        # Map them to Theme 1, Theme 2, ...
        self.file_map = {f"Theme {i+1}": file for i, file in enumerate(files)}

        options = [
            discord.SelectOption(label=name, description=f"Select {name}")
            for name in self.file_map.keys()
        ]

        super().__init__(placeholder="Select a background...", min_values=1, max_values=1, options=options)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        selected_label = self.values[0]  # Theme 1, Theme 2, etc.
        bg_file = self.file_map[selected_label]  # actual filename
        theme_name = self.theme
        font_color = "white"  # or fetch from DB

        self.cog.set_user_theme(self.user_id, theme_name, bg_file, font_color)

        await interaction.response.send_message(
            f"✅ Your profile background has been set to **{theme_name} / {selected_label}**!",
            ephemeral=True
        )


class SubThemeView(discord.ui.View):
    def __init__(self, user_id, theme, cog):
        super().__init__()
        self.cog = cog  # store cog reference
        self.add_item(SubThemeSelect(user_id, theme, cog))
    
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
        self.c.execute("""
        CREATE TABLE IF NOT EXISTS profile_theme (
            user_id INTEGER PRIMARY KEY,
            theme_name TEXT DEFAULT 'galaxy',
            bg_file TEXT DEFAULT 'GALAXY.PNG',
            font_color TEXT DEFAULT 'white'
        )
    """)

        self.conn.commit()

    def get_user_theme(self, user_id: int):
        self.c.execute("SELECT theme_name, bg_file, font_color FROM profile_theme WHERE user_id = ?", (user_id,))
        result = self.c.fetchone()
        if not result:
            # insert default
            self.c.execute(
                "INSERT INTO profile_theme (user_id) VALUES (?)", (user_id,)
            )
            self.conn.commit()
            return "galaxy", "GALAXY.PNG", "white"
        return result

    def set_user_theme(self, user_id: int, theme_name: str, bg_file: str, font_color: str = "white"):
        self.c.execute(
            "INSERT OR REPLACE INTO profile_theme (user_id, theme_name, bg_file, font_color) VALUES (?, ?, ?, ?)",
            (user_id, theme_name, bg_file, font_color)
        )
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
            # Get EXP and level
            exp, level = self.get_user(member.id, ctx.guild.id)
            title_name = get_title(level)

            # Next EXP
            next_exp = 50 * level + 20 * level**2 if level < self.MAX_LEVEL else exp

            # Fetch avatar bytes
            avatar_asset = member.display_avatar.with_size(128)
            buffer_avatar = io.BytesIO()
            await avatar_asset.save(buffer_avatar)
            buffer_avatar.seek(0)
            avatar_bytes = buffer_avatar.getvalue()

            # Fetch user theme from DB
            theme_name, bg_file, font_color = self.get_user_theme(member.id)

            # Render profile image in a thread
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
                bg_file=bg_file,
                theme_name=theme_name,
                font_color=font_color
            )

            if not img_bytes:
                await ctx.send("❌ Failed to generate profile image — check bot logs.")
                return

            file = discord.File(io.BytesIO(img_bytes), filename="profile.png")

            # Badge fallback if PNG missing
            badge_path = TITLE_EMOJI_FILES.get(title_name)
            badge_text = ""
            if not (badge_path and os.path.exists(badge_path)):
                badge_text = get_title_emoji(level)

            content = f"{member.display_name} {badge_text}".strip()
            await ctx.send(content=content if badge_text else None, file=file)

        except Exception:
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

    @commands.hybrid_command(name="profiletheme", description="Choose your profile card background theme")
    async def profiletheme(self, ctx):
        view = MainThemeView(ctx.author.id, cog=self)  # pass the cog
        await ctx.send("Select your profile theme:", view=view)


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

        YOUR_ID = [1257852423918190675]
        GUILD_ID = 974498807817588756

        for user_id in YOUR_ID:
            level, exp, leveled_up = self.add_exp(user_id, GUILD_ID, 10000)
            print(f"User {user_id} → Level {level}, EXP {exp}, Leveled up? {leveled_up}")

        print(f"🎉 You are now level {level} with {exp} EXP in guild {GUILD_ID}. Leveled up? {leveled_up}")
        


async def setup(bot):
    await bot.add_cog(Progression(bot))
    print("📦 Loaded progression cog.")



