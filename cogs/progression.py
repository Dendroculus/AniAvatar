import discord
from discord.ext import commands
import sqlite3
import os
import random
import asyncio
import traceback
import io
from discord import MessageReference
from cogs.utils.pUtils import *
from cogs.utils.constants import BG_PATH, EMOJI_PATH
    
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
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⚠️ You can only select a background for yourself.", ephemeral=True)
            return
        idx = self.values[0].lower()
        selected_theme = next(f for f in self.folders if f.lower() == idx)
        self.disabled = True
        for item in self.view.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True
        await interaction.response.edit_message(
            content=f"You have selected **{selected_theme.capitalize()}**! Now pick a background:",
            view=SubThemeView(self.user_id, selected_theme, self.cog)
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

        files = [f for f in os.listdir(theme_path) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
        self.file_map = {f"Theme {i+1}": file for i, file in enumerate(files)}

        options = [
            discord.SelectOption(label=name, description=f"Select {name}")
            for name in self.file_map.keys()
        ]

        super().__init__(placeholder="Select a background...", min_values=1, max_values=1, options=options)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "⚠️ You can only select a background for yourself.", ephemeral=True
            )
            return

        selected_label = self.values[0]
        bg_file = self.file_map[selected_label]
        theme_name = self.theme
        font_color = "white"

        self.cog.set_user_theme(self.user_id, theme_name, bg_file, font_color)

        # Disable all selects in the view
        for item in self.view.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True

        # Edit the original message's embed to show selection saved
        embed = discord.Embed(
            title="Your profile card theme has been updated!",
            description=f"Your selection has been saved!\n You have selected **`{theme_name} {selected_label}`**."
        )
        embed.set_image(url=f"attachment://profile.png")  # keep the old image in embed
        await interaction.response.edit_message(embed=embed, view=self.view)
        await interaction.message.edit(content="")

        # Generate updated profile image
        member = interaction.user
        exp, level = self.cog.get_user(member.id, interaction.guild.id)
        title_name = get_title(level)
        next_exp = None if level >= self.cog.MAX_LEVEL else 50 * level + 20 * level**2

        avatar_bytes = await member.display_avatar.with_size(128).read()

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

        if img_bytes:
            file = discord.File(io.BytesIO(img_bytes), filename="profile.png")
            await interaction.followup.send(
                content=f"{member.mention}, here’s your updated profile! <:MinoriSmile:1415182284914556928>",
                file=file
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
        data_path = os.path.join(os.path.dirname(__file__), "..", "data", "minori.db")
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
            theme_name TEXT DEFAULT 'default',
            bg_file TEXT DEFAULT 'NULL',
            font_color TEXT DEFAULT 'white'
        )
    """)

        self.conn.commit()
        
        self.c.execute("""
        CREATE TABLE IF NOT EXISTS user_coins (
            user_id INTEGER,
            guild_id INTEGER,
            coins INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, guild_id)
        )
    """)
        self.conn.commit()

    async def get_coins(self, user_id: int, guild_id: int) -> int:
        self.c.execute("SELECT coins FROM user_coins WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        result = self.c.fetchone()
        if not result:
            self.c.execute("INSERT INTO user_coins (user_id, guild_id) VALUES (?, ?)", (user_id, guild_id))
            self.conn.commit()
            return 0
        return result[0]

    async def add_coins(self, user_id: int, guild_id: int, amount: int):
        self.c.execute("""
            INSERT INTO user_coins (user_id, guild_id, coins) VALUES (?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET coins = coins + ?
        """, (user_id, guild_id, amount, amount))
        self.conn.commit()
        
    async def remove_coins(self, user_id: int, guild_id: int, amount: int) -> bool:
        coins = await self.get_coins(user_id, guild_id)
        if coins < amount:
            return False
        self.c.execute("UPDATE user_coins SET coins = coins - ? WHERE user_id = ? AND guild_id = ?", (amount, user_id, guild_id))
        self.conn.commit()
        return True

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
            
            if level >= self.MAX_LEVEL:
                exp_text = "∞"
                next_exp = None  # skip progress bar logic
            else:
                exp_text = exp
                next_exp = 50 * level + 20 * level**2

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


    @commands.hybrid_command(name="leaderboard", description="Show server rankings leaderboard")
    @commands.guild_only()
    async def leaderboard_image(self, ctx):
        # Fetch rows (same as before)
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
        rows = self.c.fetchall()
        if not rows:
            return await ctx.send("No users found in the leaderboard.")

        # Build rows_data and compute user rank and total server exp
        rows_data = []
        for idx, (user_id, level, exp) in enumerate(rows, start=1):
            try:
                member = ctx.guild.get_member(user_id)
                if member:
                    name = member.display_name
                    avatar_bytes = await member.display_avatar.with_size(128).read()
                else:
                    user = await self.bot.fetch_user(user_id)
                    name = user.name
                    avatar_bytes = await user.display_avatar.with_size(128).read()
            except Exception:
                name = f"User {user_id}"
                avatar_bytes = b""

            next_exp = None if level >= self.MAX_LEVEL else (50 * level + 20 * level**2)
            rows_data.append({
                "rank": idx,
                "avatar_bytes": avatar_bytes,
                "name": self.truncate(name, self.MAX_NAME_WIDTH),
                "level": level,
                "title": get_title(level),
                "exp": exp or 0,
                "next_exp": next_exp
            })

        # compute invoking user's rank & exp
        user_rank = self.get_rank(ctx.author.id, ctx.guild.id)
        user_exp, user_level = self.get_user(ctx.author.id, ctx.guild.id)
        user_total_exp_display = f"{user_exp:,}"

        top_title = get_title(rows_data[0]["level"]) if rows_data else "Leaderboard"
        embed_color = TITLE_COLORS.get(top_title, discord.Color.purple())
        exp_icon_path = os.path.join(EMOJI_PATH, "EXP.png")

        img_bytes = await asyncio.to_thread(create_leaderboard_image, rows_data, fonts=FONTS, exp_icon_path=exp_icon_path)

        if not img_bytes:
            return await ctx.send("Failed to generate leaderboard image.")

        file = discord.File(io.BytesIO(img_bytes), filename="leaderboard.png")

        exp_emoji_str = "<:EXP:1415642038589984839>"  
        embed = discord.Embed(
            title=f"{ctx.guild.name}'s Top Rank List <:CHAMPION:1414508304448749568>",
            color=embed_color,
            description=(f"{exp_emoji_str} **Your Rank**\n"
                        f"You are rank **#{user_rank}** on this server\n"
                        f"with a total of **{user_total_exp_display}** {exp_emoji_str}")
        )

        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)

        embed.set_image(url="attachment://leaderboard.png")
        await ctx.send(embed=embed, file=file)

    @commands.hybrid_command(name="profiletheme", description="Choose your profile card background theme")
    @commands.guild_only()
    async def profiletheme(self, ctx):
        exp, level = self.get_user(ctx.author.id, ctx.guild.id)
        title_name = get_title(level)
        next_exp = 50 * level + 20 * level**2 if level < self.MAX_LEVEL else None

        avatar_asset = ctx.author.display_avatar.with_size(128)
        buffer_avatar = io.BytesIO()
        await avatar_asset.save(buffer_avatar)
        buffer_avatar.seek(0)
        avatar_bytes = buffer_avatar.getvalue()

        theme_name, bg_file, font_color = self.get_user_theme(ctx.author.id)

        img_bytes = await asyncio.to_thread(
            render_profile_image,
            avatar_bytes,
            ctx.author.display_name,
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

        file = discord.File(io.BytesIO(img_bytes), filename="profile.png")
        embed = discord.Embed(
        title="Your current profile",
        description="Below is your current profile card theme. You can change it by selecting a theme from the dropdown menu."
        )
        embed.set_image(url="attachment://profile.png")

        view = MainThemeView(ctx.author.id, cog=self)
        await ctx.send(embed=embed, file=file, view=view)
        
    @commands.hybrid_command(name="resetprofiletheme",description="Reset your profile card theme to default")
    @commands.guild_only()
    async def resetprofiletheme(self, ctx):
        try:
            # Reset theme in DB
            self.set_user_theme(ctx.author.id, "default", None, "white")

            # Fetch current EXP & level
            exp, level = self.get_user(ctx.author.id, ctx.guild.id)
            title_name = get_title(level)
            next_exp = 50 * level + 20 * level**2 if level < self.MAX_LEVEL else None
            avatar_asset = ctx.author.display_avatar.with_size(128)
            buffer_avatar = io.BytesIO()
            await avatar_asset.save(buffer_avatar)
            buffer_avatar.seek(0)
            avatar_bytes = buffer_avatar.getvalue()
            img_bytes = await asyncio.to_thread(
                render_profile_image,
                avatar_bytes,
                ctx.author.display_name,
                title_name,
                level,
                exp,
                next_exp,
                FONTS,
                TITLE_EMOJI_FILES,
                bg_file=None,
                theme_name="default",
                font_color="white"
            )

            file = discord.File(io.BytesIO(img_bytes), filename="profile.png")
            embed = discord.Embed(
                title="Profile Theme Reset",
                description="✅ Your profile card theme has been reset to default."
            )
            embed.set_image(url="attachment://profile.png")

            await ctx.send(embed=embed, file=file)

        except Exception:
            traceback.print_exc()
            await ctx.send("❌ Failed to reset profile theme. Check console/logs.")

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
                    f"Title: `{new_title}` {new_emoji}"
                )
            else:  # Normal level-up
                embed_title = f"{message.author.display_name} <:LEVELUP:1413479714428948551> {level}"
                embed_description = (
                    f"```Congratulations {message.author.display_name}! You have reached level {level}.```\n"
                    f"Title: `{new_title}` {new_emoji}"
                )

            embed = discord.Embed(
                title=embed_title,
                description=embed_description,
                color=discord.Color.green()
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)
            lvlup_msg = await message.channel.send(embed=embed)
            # ---------------- COINS REWARD ----------------
            coins_amount = random.randint(30, 50)
            prog_cog = self.bot.get_cog("Progression")
            if prog_cog:
                await prog_cog.add_coins(user_id, guild_id, coins_amount)
                await message.channel.send(
                    f"{message.author.display_name} received <:Coins:1415353285270966403> {coins_amount} coins for leveling up!",
                    reference=MessageReference(message_id=lvlup_msg.id, channel_id=lvlup_msg.channel.id, guild_id=lvlup_msg.guild.id)
                )
                    
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
    
    @commands.Cog.listener()
    async def on_ready(self):
        print(f"{self.bot.user} is ready!")

        YOUR_ID = [955268891125375036]  # Add all relevant user IDs here
        GUILD_ID = 974498807817588756  # Your guild ID

        progression = self.bot.get_cog("Progression")
        if not progression:
            print("Progression cog not loaded!")
            return

        for user_id in YOUR_ID:
            # Add EXP
            level, exp, leveled_up = self.add_exp(user_id, GUILD_ID, 0)
            print(f"User {user_id} → Level {level}, EXP {exp}, Leveled up? {leveled_up}")

            # Add coins
            await progression.add_coins(user_id, GUILD_ID, 0)
            coins = await progression.get_coins(user_id, GUILD_ID)
            print(f"User {user_id} → Coins: {coins}")

        # Optional summary of the first user
        first_user = YOUR_ID[0]
        print(f"🎉 First user {first_user} now has Level {level}, EXP {exp}, Coins {coins}. Leveled up? {leveled_up}")

    
async def setup(bot):
    await bot.add_cog(Progression(bot))
    print("📦 Loaded progression cog.")



