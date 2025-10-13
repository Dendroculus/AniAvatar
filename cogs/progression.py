import discord
from discord.ext import commands
import aiosqlite
import os
import random
import asyncio
import traceback
import io
from discord import MessageReference
from cogs.utils.progUtils import *
from cogs.utils.constants import BG_PATH, EMOJI_PATH

PROFILE_PNG = "profile.png"
ATTACHMENT_PROFILE = f"attachment://{PROFILE_PNG}"

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

        await self.cog.set_user_theme(self.user_id, theme_name, bg_file, font_color)

        for item in self.view.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True

        embed = discord.Embed(
            title="Your profile card theme has been updated!",
            description=f"Your selection has been saved!\n You have selected `{theme_name} {selected_label}`."
        )
        embed.set_image(url=ATTACHMENT_PROFILE)
        try:
            await interaction.response.edit_message(embed=embed, view=self.view)
        except discord.errors.InteractionResponded:
            await interaction.followup.send(embed=embed)
        await interaction.message.edit(content="")

        member = interaction.user
        exp, level = await self.cog.get_user(member.id, interaction.guild.id)
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
            file = discord.File(io.BytesIO(img_bytes), filename=PROFILE_PNG)
            await interaction.followup.send(
                content=f"{member.mention}, here’s your updated profile! <:MinoriSmile:1415182284914556928>",
                file=file
            )

class SubThemeView(discord.ui.View):
    def __init__(self, user_id, theme, cog):
        super().__init__()
        self.cog = cog  
        self.add_item(SubThemeSelect(user_id, theme, cog))
    
class Progression(commands.Cog):
    MAX_LEVEL = 999
    MAX_BOX_WIDTH = 50
    MAX_NAME_WIDTH = 20
    MAX_EXP_WIDTH = 12

    def __init__(self, bot):
        self.bot = bot
        self.cooldowns = {}
        data_path = os.path.join(os.path.dirname(__file__), "..", "data", "minori.db")
        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        data_path = os.path.abspath(data_path)
        self.db_path = data_path
        self.conn: aiosqlite.Connection | None = None
        self.db_lock = asyncio.Lock()

    async def cog_load(self):
        self.conn = await aiosqlite.connect(self.db_path)
        await self.conn.execute("PRAGMA journal_mode=WAL;")
        await self.conn.execute("PRAGMA synchronous=NORMAL;")
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER,
                guild_id INTEGER,
                exp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        await self.conn.execute("""
        CREATE TABLE IF NOT EXISTS profile_theme (
            user_id INTEGER PRIMARY KEY,
            theme_name TEXT DEFAULT 'default',
            bg_file TEXT DEFAULT 'NULL',
            font_color TEXT DEFAULT 'white'
        )
        """)
        await self.conn.execute("""
        CREATE TABLE IF NOT EXISTS user_coins (
            user_id INTEGER,
            guild_id INTEGER,
            coins INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, guild_id)
        )
        """)
        await self.conn.commit()

    async def cog_unload(self):
        try:
            if self.conn:
                await self.conn.close()
        except Exception:
            pass
        
    async def safe_send(self, ctx, *args, **kwargs):
        interaction = getattr(ctx, "interaction", None)
        if interaction is not None:
            try:
                if not interaction.response.is_done():
                    return await interaction.response.send_message(*args, **kwargs)
                return await interaction.followup.send(*args, **kwargs)
            except discord.errors.NotFound:
                return await ctx.channel.send(*args, **kwargs)
            except discord.errors.InteractionResponded:
                return await interaction.followup.send(*args, **kwargs)
        else:
            return await ctx.send(*args, **kwargs)
    
    async def _fetch_avatar_bytes(self, member_or_user, size=128, timeout=3.0):
        try:
            return await asyncio.wait_for(member_or_user.display_avatar.with_size(size).read(), timeout=timeout)
        except Exception as e:
            print(f"[avatar_fetch] failed for {getattr(member_or_user,'id',None)}: {e}")
            return b""

    async def _build_rows_data(self, ctx, rows, avatar_size=128, avatar_timeout=3.0):
        meta = [(idx, user_id, level, exp) for idx, (user_id, level, exp) in enumerate(rows, start=1)]

        fetch_tasks = []
        for idx, user_id, level, exp in meta:
            member = ctx.guild.get_member(user_id)
            if member:
                fetch_tasks.append(self._fetch_avatar_bytes(member, size=avatar_size, timeout=avatar_timeout))
            else:
                async def fetch_user_avatar(uid=user_id):
                    try:
                        u = await self.bot.fetch_user(uid)
                        return await self._fetch_avatar_bytes(u, size=avatar_size, timeout=avatar_timeout)
                    except Exception as e:
                        print(f"[fetch_user_avatar] failed fetch user {uid}: {e}")
                        return b""
                fetch_tasks.append(fetch_user_avatar())

        avatar_bytes_list = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        rows_data = []
        for (idx, user_id, level, exp), avatar_bytes in zip(meta, avatar_bytes_list):
            if isinstance(avatar_bytes, Exception):
                print(f"[avatar_fetch] task exception for user {user_id}: {avatar_bytes}")
                avatar_bytes = b""
            next_exp = None if level >= self.MAX_LEVEL else (50 * level + 20 * level**2)
            member = ctx.guild.get_member(user_id)
            if member:
                name = member.display_name
            else:
                try:
                    user = await self.bot.fetch_user(user_id)
                    name = user.name
                except Exception:
                    name = f"User {user_id}"
            rows_data.append({
                "rank": idx,
                "avatar_bytes": avatar_bytes or b"",
                "name": self.truncate(name, self.MAX_NAME_WIDTH),
                "level": level,
                "title": get_title(level),
                "exp": exp or 0,
                "next_exp": next_exp
            })

        return rows_data

    async def get_coins(self, user_id: int, guild_id: int) -> int:
        async with self.db_lock:
            async with self.conn.execute("SELECT coins FROM user_coins WHERE user_id = ? AND guild_id = ?", (user_id, guild_id)) as cur:
                row = await cur.fetchone()
            if not row:
                await self.conn.execute("INSERT INTO user_coins (user_id, guild_id) VALUES (?, ?)", (user_id, guild_id))
                await self.conn.commit()
                return 0
            return int(row[0])

    async def add_coins(self, user_id: int, guild_id: int, amount: int):
        if amount == 0:
            return
        amount = int(amount)
        async with self.db_lock:
            await self.conn.execute(
                "INSERT OR IGNORE INTO user_coins (user_id, guild_id, coins) VALUES (?, ?, 0)",
                (user_id, guild_id)
            )
            await self.conn.execute(
                """
                INSERT INTO user_coins (user_id, guild_id, coins) VALUES (?, ?, ?)
                ON CONFLICT(user_id, guild_id) DO UPDATE SET coins = coins + ?
                """,
                (user_id, guild_id, amount, amount)
            )
            await self.conn.commit()
        
    async def ensure_user_row(self, user_id: int, guild_id: int):
        async with self.db_lock:
            await self.conn.execute(
                "INSERT OR IGNORE INTO user_coins (user_id, guild_id, coins) VALUES (?, ?, 0)",
                (user_id, guild_id)
            )
            await self.conn.commit()

    async def remove_coins(self, user_id: int, guild_id: int, amount: int) -> bool:
        amount = int(amount)
        if amount <= 0:
            return False

        async with self.db_lock:
            await self.conn.execute(
                "INSERT OR IGNORE INTO user_coins (user_id, guild_id, coins) VALUES (?, ?, 0)",
                (user_id, guild_id)
            )
            async with self.conn.execute(
                "UPDATE user_coins SET coins = coins - ? WHERE user_id = ? AND guild_id = ? AND coins >= ?",
                (amount, user_id, guild_id, amount)
            ) as cur:
                await self.conn.commit()
                return cur.rowcount > 0

    async def reserve_coins(self, user_id: int, guild_id: int, amount: int) -> bool:
        return await self.remove_coins(user_id, guild_id, amount)

    async def get_user_theme(self, user_id: int):
        async with self.db_lock:
            async with self.conn.execute("SELECT theme_name, bg_file, font_color FROM profile_theme WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
            if not row:
                await self.conn.execute("INSERT INTO profile_theme (user_id) VALUES (?)", (user_id,))
                await self.conn.commit()
                return "galaxy", "GALAXY.PNG", "white"
            return row

    async def set_user_theme(self, user_id: int, theme_name: str, bg_file: str, font_color: str = "white"):
        async with self.db_lock:
            await self.conn.execute(
                "INSERT OR REPLACE INTO profile_theme (user_id, theme_name, bg_file, font_color) VALUES (?, ?, ?, ?)",
                (user_id, theme_name, bg_file, font_color)
            )
            await self.conn.commit()
    
    def truncate(self, text: str, max_len: int):
        return text if len(text) <= max_len else text[:max_len - 3] + "..."

    async def get_user(self, user_id: int, guild_id: int):
        async with self.db_lock:
            async with self.conn.execute(
                "SELECT exp, level FROM users WHERE user_id = ? AND guild_id = ?",
                (user_id, guild_id)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                await self.conn.execute(
                    "INSERT INTO users (user_id, guild_id) VALUES (?, ?)",
                    (user_id, guild_id)
                )
                await self.conn.commit()
                return 0, 1
            return row

    async def add_exp(self, user_id: int, guild_id: int, amount: int):
        async with self.db_lock:
            async with self.conn.execute(
                "SELECT exp, level FROM users WHERE user_id = ? AND guild_id = ?",
                (user_id, guild_id)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                await self.conn.execute(
                    "INSERT INTO users (user_id, guild_id, exp, level) VALUES (?, ?, 0, 1)",
                    (user_id, guild_id)
                )
                await self.conn.commit()
                exp = 0
                level = 1
            else:
                exp, level = row

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

            await self.conn.execute(
                "UPDATE users SET exp = ?, level = ? WHERE user_id = ? AND guild_id = ?",
                (new_exp, level, user_id, guild_id)
            )
            await self.conn.commit()
            return level, new_exp, leveled_up

    async def get_rank(self, user_id: int, guild_id: int):
        async with self.db_lock:
            async with self.conn.execute(
                "SELECT COUNT(*)+1 FROM users WHERE guild_id = ? AND (level > (SELECT level FROM users WHERE user_id = ? AND guild_id = ?) OR (level = (SELECT level FROM users WHERE user_id = ? AND guild_id = ?) AND exp > (SELECT exp FROM users WHERE user_id = ? AND guild_id = ?)))",
                (guild_id, user_id, guild_id, user_id, guild_id, user_id, guild_id)
            ) as cur:
                row = await cur.fetchone()
                return int(row[0]) if row else 1

    async def get_rank_for(self, guild_id: int, level: int, exp: int):
        async with self.db_lock:
            async with self.conn.execute(
                "SELECT COUNT(*)+1 FROM users WHERE guild_id = ? AND (level > ? OR (level = ? AND exp > ?))",
                (guild_id, level, level, exp)
            ) as cur:
                row = await cur.fetchone()
                return int(row[0]) if row else 1

    async def announce_level_up(self, guild_id: int, user_id: int, new_level: int, old_level: int, channel: discord.abc.Messageable):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        member = guild.get_member(user_id)
        if not member:
            return
        old_title = get_title(old_level)
        new_title = get_title(new_level)
        old_emoji = get_title_emoji(old_level)
        new_emoji = get_title_emoji(new_level)
        if new_title != old_title:
            embed_title = f"{member.display_name} <:LEVELUP:1413479714428948551> {new_level}    {old_emoji} <:RIGHTWARDARROW:1414227272302334062> {new_emoji}"
            embed_description = (
                f"```Congratulations {member.display_name}! You have reached level {new_level} and ascended to {new_title}. ```\n"
                f"Title: `{new_title}` {new_emoji}"
            )
        else:
            embed_title = f"{member.display_name} <:LEVELUP:1413479714428948551> {new_level}"
            embed_description = (
                f"```Congratulations {member.display_name}! You have reached level {new_level}.```\n"
                f"Title: `{new_title}` {new_emoji}"
            )
        embed = discord.Embed(
            title=embed_title,
            description=embed_description,
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        lvlup_msg = await channel.send(embed=embed)
        coins_amount = random.randint(30, 50)
        await self.add_coins(user_id, guild_id, coins_amount)
        await channel.send(
            f"{member.display_name} received <:Coins:1415353285270966403> {coins_amount} coins for leveling up!",
            reference=MessageReference(message_id=lvlup_msg.id, channel_id=lvlup_msg.channel.id, guild_id=lvlup_msg.guild.id)
        )

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        async with self.db_lock:
            await self.conn.execute("DELETE FROM users WHERE guild_id = ?", (guild.id,))
            await self.conn.commit()
        print(f"[Progression] Cleaned up DB for guild {guild.id} ({guild.name})")
        
    @commands.hybrid_command(name="profile", description="Check your level, EXP, and title")
    @commands.guild_only()
    async def profile(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        if member.bot:
            await ctx.send(f"{member.display_name} is a bot and cannot have a profile.")
            return
        
        try:
            exp, level = await self.get_user(member.id, ctx.guild.id)
            title_name = get_title(level)

            if level >= self.MAX_LEVEL:
                next_exp = None  
            else:
                next_exp = 50 * level + 20 * level**2

            avatar_asset = member.display_avatar.with_size(128)
            buffer_avatar = io.BytesIO()
            await avatar_asset.save(buffer_avatar)
            buffer_avatar.seek(0)
            avatar_bytes = buffer_avatar.getvalue()

            theme_name, bg_file, font_color = await self.get_user_theme(member.id)
            user_rank = await self.get_rank (member.id, ctx.guild.id)
            
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
                font_color=font_color,
                user_rank=user_rank
            )

            if not img_bytes:
                await ctx.send("❌ Failed to generate profile image — check bot logs.")
                return

            file = discord.File(io.BytesIO(img_bytes), filename=PROFILE_PNG)

            badge_path = TITLE_EMOJI_FILES.get(title_name)
            badge_text = ""
            if not (badge_path and os.path.exists(badge_path)):
                badge_text = get_title_emoji(level)

            content = f"{member.display_name} {badge_text}".strip()
            interaction = getattr(ctx, "interaction", None)

            if interaction is not None:
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(content=content if badge_text else None, file=file)
                    else:
                        await interaction.followup.send(content=content if badge_text else None, file=file)
                except discord.errors.NotFound:
                    try:
                        await ctx.channel.send(content=content if badge_text else None, file=file)
                    except Exception as e:
                        try:
                            await ctx.author.send("Couldn't send your profile in the server channel. " 
                                                "Make sure I have permission to send messages and attach files.")
                        except Exception:
                            pass
                except discord.errors.InteractionResponded:
                    await interaction.followup.send(content=content if badge_text else None, file=file)
            else:
                await ctx.send(content=content if badge_text else None, file=file)

        except Exception:
            traceback.print_exc()
            await ctx.send("❌ Unexpected error while generating profile. Check console/logs.")


    @commands.hybrid_command(name="leaderboard", description="Show server rankings leaderboard")
    @commands.guild_only()
    async def leaderboard_image(self, ctx):
        try:
            await ctx.defer()
        except Exception:
            pass

        try:
            async with self.db_lock:
                async with self.conn.execute(
                    """
                    SELECT user_id, level, exp
                    FROM users
                    WHERE guild_id = ?
                    AND ((exp > 0 AND level >= 1) OR level = ?)
                    ORDER BY level DESC, exp DESC
                    LIMIT 10
                    """,
                    (ctx.guild.id, self.MAX_LEVEL)
                ) as cur:
                    rows = await cur.fetchall()
        except Exception as e:
            print("[leaderboard] DB query failed:", e)
            return await ctx.send("Failed to fetch leaderboard data (check logs).")

        if not rows:
            return await ctx.send("No users found in the leaderboard.")

        try:
            rows_data = await self._build_rows_data(ctx, rows, avatar_size=128, avatar_timeout=3.0)
        except Exception as e:
            print("[leaderboard] _build_rows_data failed:", e, traceback.format_exc())
            rows_data = []
            try:
                for idx, (user_id, level, exp) in enumerate(rows, start=1):
                    try:
                        member = ctx.guild.get_member(user_id)
                        if member:
                            name = member.display_name
                            avatar_bytes = await asyncio.wait_for(member.display_avatar.with_size(128).read(), timeout=2.0)
                        else:
                            user = await self.bot.fetch_user(user_id)
                            name = user.name
                            avatar_bytes = await asyncio.wait_for(user.display_avatar.with_size(128).read(), timeout=2.0)
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
            except Exception as se:
                print("[leaderboard] fallback sequential build failed:", se, traceback.format_exc())
                return await ctx.send("Failed to build leaderboard (check logs).")

        print("Generating leaderboard for", len(rows_data), "rows")
        for idx, rd in enumerate(rows_data[:6]):
            print(f" row[{idx}]: name={rd.get('name')} level={rd.get('level')} exp={rd.get('exp')} next={rd.get('next_exp')}")

        exp_icon_path = os.path.join(EMOJI_PATH, "EXP.png")

        try:
            print("[create_leaderboard_image] start")
            img_bytes = await asyncio.wait_for(
                asyncio.to_thread(
                    create_leaderboard_image,
                    rows_data,
                    fonts=FONTS,
                    exp_icon_path=exp_icon_path
                ),
                timeout=20.0
            )
            print("[create_leaderboard_image] done")
        except asyncio.TimeoutError:
            print("create_leaderboard_image timed out — retrying without gradient")
            try:
                img_bytes = await asyncio.wait_for(
                    asyncio.to_thread(
                        create_leaderboard_image,
                        rows_data,
                        fonts=FONTS,
                        exp_icon_path=exp_icon_path,
                        gradient=False,
                        gradient_noise=False
                    ),
                    timeout=20.0
                )
            except Exception as e:
                print("Fallback render failed:", e)
                print(traceback.format_exc())
                return await ctx.send("Leaderboard render timed out and fallback failed. Check logs for details.")
        except Exception as e:
            print("create_leaderboard_image error:", e)
            print(traceback.format_exc())
            return await ctx.send("Failed to generate leaderboard image (check bot logs).")

        if not img_bytes:
            return await ctx.send("Renderer returned no image bytes.")

        user_rank = await self.get_rank(ctx.author.id, ctx.guild.id)
        user_exp, user_level = await self.get_user(ctx.author.id, ctx.guild.id)
        user_total_exp_display = f"{user_exp:,}"

        top_title = get_title(rows_data[0]["level"]) if rows_data else "Leaderboard"
        embed_color = TITLE_COLORS.get(top_title, discord.Color.purple())

        file = discord.File(io.BytesIO(img_bytes), filename="leaderboard.png")
        exp_emoji_str = "<:EXP:1415642038589984839>"

        embed = discord.Embed(
            title=f"{ctx.guild.name}'s Top Rank List <:CHAMPION:1414508304448749568>",
            color=embed_color,
            description=(f"**Your Rank**\n"
                        f"You are ranked **#{user_rank}** on this server\n"
                        f"with a total of **{user_total_exp_display}** {exp_emoji_str}")
        )

        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)

        embed.set_image(url="attachment://leaderboard.png")

        try:
            await ctx.send(embed=embed, file=file)
            print("Sent leaderboard image via ctx.send.")
        except Exception as e:
            print("Failed to send via ctx.send:", e, traceback.format_exc())
            try:
                await ctx.interaction.followup.send(embed=embed, file=file)
                print("Sent leaderboard image via followup.")
            except Exception as e2:
                print("Failed to send leaderboard via followup:", e2, traceback.format_exc())
                try:
                    await ctx.send("Failed to send leaderboard image (check bot logs).")
                except Exception:
                    pass

    @commands.hybrid_command(name="profiletheme", description="Choose your profile card background theme")
    @commands.guild_only()
    async def profiletheme(self, ctx):
        exp, level = await self.get_user(ctx.author.id, ctx.guild.id)
        title_name = get_title(level)
        next_exp = 50 * level + 20 * level**2 if level < self.MAX_LEVEL else None

        avatar_asset = ctx.author.display_avatar.with_size(128)
        buffer_avatar = io.BytesIO()
        await avatar_asset.save(buffer_avatar)
        buffer_avatar.seek(0)
        avatar_bytes = buffer_avatar.getvalue()

        theme_name, bg_file, font_color = await self.get_user_theme(ctx.author.id)

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

        file = discord.File(io.BytesIO(img_bytes), filename=PROFILE_PNG)
        embed = discord.Embed(
        title="Your current profile",
        description="Below is your current profile card theme. You can change it by selecting a theme from the dropdown menu."
        )
        embed.set_image(url=ATTACHMENT_PROFILE)

        view = MainThemeView(ctx.author.id, cog=self)
        await ctx.send(embed=embed, file=file, view=view)
        
    @commands.hybrid_command(name="resetprofiletheme",description="Reset your profile card theme to default")
    @commands.guild_only()
    async def resetprofiletheme(self, ctx):
        try:
            await self.set_user_theme(ctx.author.id, "default", None, "white")

            exp, level = await self.get_user(ctx.author.id, ctx.guild.id)
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
                description="Your profile card theme has been reset to default."
            )
            embed.set_image(url=ATTACHMENT_PROFILE)

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

        exp, level = await self.get_user(user_id, guild_id)
        old_level = level
        old_title = get_title(old_level)
        
        exp_gain = random.randint(5 + level * 8, 10 + level * 12)
        level, new_exp, leveled_up = await self.add_exp(user_id, guild_id, exp_gain)

        if leveled_up:
            await self.announce_level_up(guild_id, user_id, level, old_level, message.channel)
            old_rank = await self.get_rank_for(guild_id, old_level, exp)
            new_rank = await self.get_rank_for(guild_id, level, new_exp)
            if new_rank < old_rank:
                embed = discord.Embed(
                    title=f"<:LEVELUP:1413479714428948551> Rank Up! {message.author.display_name}",
                    description=f"```{message.author.display_name} has ranked up to #{new_rank} in the server leaderboard! 🎉```",
                    color=discord.Color.gold()
                )
                embed.set_thumbnail(url=message.author.display_avatar.url)
                await message.channel.send(embed=embed)
                
    @commands.Cog.listener()
    async def on_ready(self):
        print(f"{self.bot.user} is ready!")

        YOUR_ID = [
            955268891125375036, 872679412573802537, 609614026573479936
        ] 

        GUILD_ID = 974498807817588756 

        progression = self.bot.get_cog("Progression")
        if not progression:
            print("Progression cog not loaded!")
            return

        rand_exp = random.randint(0, 0)
        for user_id in YOUR_ID:
            level, exp, leveled_up = await self.add_exp(user_id, GUILD_ID, rand_exp)
            print(f"User {user_id} → Level {level}, EXP {exp}, Leveled up? {leveled_up}")

            await progression.add_coins(user_id, GUILD_ID, 99999)
            coins = await progression.get_coins(user_id, GUILD_ID)
            print(f"User {user_id} → Coins: {coins}")

        first_user = YOUR_ID[0]
        print(f"🎉 First user {first_user} now has Level {level}, EXP {exp}, Coins {coins}. Leveled up? {leveled_up}")

    
async def setup(bot):
    await bot.add_cog(Progression(bot))
