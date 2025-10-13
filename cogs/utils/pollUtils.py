import aiosqlite
import asyncio
import discord
import json
from datetime import datetime, timedelta, timezone 
from typing import List, Optional
from discord import ui
from discord.ext import commands
import os

DB_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "data", "minori.db")

_DB: Optional[aiosqlite.Connection] = None
_DB_LOCK = asyncio.Lock()
MODAL_PLACEHOLDER = "Leave empty if not needed"

async def get_db() -> aiosqlite.Connection:
    global _DB
    if _DB is None:
        os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
        _DB = await aiosqlite.connect(DB_FILE)
        await _DB.execute("PRAGMA journal_mode=WAL")
        await _DB.execute("PRAGMA synchronous=NORMAL")
        await _DB.execute("PRAGMA foreign_keys=ON")
        await _DB.commit()
    return _DB

async def close_db():
    global _DB
    if _DB is not None:
        await _DB.close()
        _DB = None

async def init_db():
    conn = await get_db()
    async with _DB_LOCK:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS polls (
                message_id INTEGER PRIMARY KEY,
                guild_id INTEGER,
                channel_id INTEGER,
                author_id INTEGER,
                question TEXT,
                options TEXT,
                votes TEXT,
                end_time REAL,
                ended INTEGER DEFAULT 0,
                winners TEXT,
                counts TEXT,
                total_votes INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.commit()

        async with conn.execute("PRAGMA table_info(polls)") as cur:
            cols = await cur.fetchall()
            col_names = [c[1] for c in cols]  
            if "author_id" not in col_names:
                try:
                    await conn.execute("ALTER TABLE polls ADD COLUMN author_id INTEGER")
                    await conn.commit()
                except aiosqlite.Error:
                    pass

        await conn.execute("UPDATE polls SET options='[]' WHERE options IS NULL")
        await conn.execute("UPDATE polls SET votes='{}' WHERE votes IS NULL")
        await conn.commit()

async def save_active_poll(message_id, guild_id, channel_id, author_id, question, options, votes, end_time):
    conn = await get_db()
    async with _DB_LOCK:
        await conn.execute("""
            INSERT OR REPLACE INTO polls 
            (message_id, guild_id, channel_id, author_id, question, options, votes, end_time, ended)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            message_id,
            guild_id,
            channel_id,
            author_id,
            question,
            json.dumps(options),
            json.dumps({k: list(v) for k, v in votes.items()}),
            end_time.timestamp() if end_time else None
        ))
        await conn.commit()

async def record_poll_result(message_id, winners, counts, total_votes):
    conn = await get_db()
    async with _DB_LOCK:
        await conn.execute("""
            UPDATE polls
            SET winners=?, counts=?, total_votes=?, ended=1
            WHERE message_id=?
        """, (
            json.dumps(winners),
            json.dumps(counts),
            total_votes,
            message_id
        ))
        await conn.commit()

async def load_active_polls():
    conn = await get_db()
    query = """
        SELECT
            message_id,
            guild_id,
            channel_id,
            author_id,
            question,
            options,
            votes,
            end_time,
            ended
        FROM polls
        WHERE ended = 0
    """
    async with conn.execute(query) as cursor:
        rows = await cursor.fetchall()
        cols = ["message_id","guild_id","channel_id","author_id","question","options","votes","end_time","ended"]
        return [dict(zip(cols, row)) for row in rows]

async def purge_finished_polls():
    conn = await get_db()
    async with _DB_LOCK:
        await conn.execute("DELETE FROM polls WHERE ended=1")
        await conn.commit()

class PollView(discord.ui.View):
    def __init__(self, question: str, options: List[str], author: discord.Member, timeout: Optional[int] = None):
        super().__init__(timeout=timeout)
        self.question = question
        self.options = options
        self.votes = {opt: set() for opt in options}
        self.author = author
        self.message: Optional[discord.Message] = None
        self.updater_task: Optional[asyncio.Task] = None
        self.ended = False
        self.end_time = (datetime.now(timezone.utc) + timedelta(seconds=timeout)) if timeout else None

        add_button = discord.ui.Button(label="Add Option", style=discord.ButtonStyle.green)
        add_button.callback = self.add_option
        self.add_item(add_button)

        select = discord.ui.Select(
            placeholder="Select one answer",
            options=[discord.SelectOption(label=opt, value=str(i)) for i, opt in enumerate(options)],
            min_values=1,
            max_values=1
        )
        select.callback = self.select_callback
        self.add_item(select)

        remove_button = discord.ui.Button(label="Remove Vote", style=discord.ButtonStyle.danger)
        remove_button.callback = self.remove_vote
        self.add_item(remove_button)

        end_button = discord.ui.Button(label="End Poll", style=discord.ButtonStyle.red)
        end_button.callback = self.end_poll
        self.add_item(end_button)

        if self.end_time:
            loop = asyncio.get_running_loop()
            self.updater_task = loop.create_task(self._auto_end())

    async def _auto_end(self):
        try:
            if self.ended or not self.end_time:
                return

            remaining = (self.end_time - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                await asyncio.sleep(remaining)

            if not self.ended:
                await self.on_timeout()
        except asyncio.CancelledError:
            raise

    async def _ensure_poll_active(self, interaction: discord.Interaction) -> bool:
        if self.ended:
            try:
                await interaction.response.send_message("⚠️ Poll already closed.", ephemeral=True)
            except discord.errors.InteractionResponded:
                try:
                    await interaction.followup.send("⚠️ Poll already closed.", ephemeral=True)
                except Exception:
                    pass
            return False
        if self.end_time and datetime.now(timezone.utc) >= self.end_time:
            if self.updater_task and not self.updater_task.done():
                try:
                    self.updater_task.cancel()
                except Exception:
                    pass
            await self.on_timeout()
            try:
                await interaction.response.send_message("⚠️ Poll has already ended.", ephemeral=True)
            except discord.errors.InteractionResponded:
                try:
                    await interaction.followup.send("⚠️ Poll has already ended.", ephemeral=True)
                except Exception:
                    pass
            return False
        return True

    def _cancel_updater_if_needed(self):
        try:
            current = asyncio.current_task()
        except Exception:
            current = None
        if self.updater_task and self.updater_task is not current and not self.updater_task.done():
            try:
                self.updater_task.cancel()
            except Exception:
                pass

    def _compute_results(self):
        results = {opt: len(users) for opt, users in self.votes.items()}
        winners = []
        winner_text = ""
        if results:
            max_votes = max(results.values())
            winners = [opt for opt, count in results.items() if count == max_votes]
            if max_votes > 0:
                if len(winners) == 1:
                    winner_text = (
                        f"\n\n<:MinoriPray:1418919979272896634> Polling for `{self.question}` ended. "
                        f"The highest vote goes to **{winners[0]}** with {max_votes} vote{'s' if max_votes!=1 else ''}."
                    )
                else:
                    winner_text = (
                        f"\n\n<:MinoriPray:1418919979272896634> Polling for `{self.question}` ended. "
                        f"It's a tie between {', '.join(winners)} — each with {max_votes} votes."
                    )
            else:
                winner_text = (
                    f"\n\n<:MinoriWink:1414899695209418762> Polling for `{self.question}` ended. "
                    "No votes were cast."
                )
        return results, winners, winner_text

    async def _persist_results(self, results, winners):
        try:
            await record_poll_result(
                message_id=self.message.id if self.message else None,
                winners=winners,
                counts=results,
                total_votes=sum(results.values())
            )
        except aiosqlite.Error as e:
            print(f"[Poll DB Save Error] {e}")

    async def _finalize_view(self, winner_text: str):
        self.clear_items()
        if self.message:
            final_embed = self.make_poll_embed(closed=True)
            try:
                await self.message.edit(embed=final_embed, view=self)
            except Exception as e:
                print(f"[on_timeout] failed editing final embed: {e}")
            if winner_text:
                try:
                    await self.message.channel.send(winner_text)
                except Exception as e:
                    print(f"[on_timeout] failed sending winner_text: {e}")

    async def on_timeout(self):
        if self.ended:
            return
        self.ended = True
        self._cancel_updater_if_needed()
        results, winners, winner_text = self._compute_results()
        await self._persist_results(results, winners)
        await self._finalize_view(winner_text)

    async def select_callback(self, interaction: discord.Interaction):
        if not await self._ensure_poll_active(interaction):
            return

        try:
            idx = int(interaction.data["values"][0])
        except Exception:
            return await interaction.response.send_message("⚠️ Invalid selection.", ephemeral=True)

        if idx < 0 or idx >= len(self.options):
            return await interaction.response.send_message("⚠️ Invalid choice.", ephemeral=True)

        choice_label = self.options[idx]

        for opt in self.votes:
            self.votes[opt].discard(interaction.user.id)
        self.votes[choice_label].add(interaction.user.id)

        if self.message:
            try:
                await save_active_poll(
                    message_id=self.message.id,
                    guild_id=self.message.guild.id,
                    channel_id=self.message.channel.id,
                    author_id=self.author.id,  
                    question=self.question,
                    options=self.options,
                    votes=self.votes,
                    end_time=self.end_time
                )
            except aiosqlite.Error as e:
                print(f"[Poll DB Save Error on vote] {e}")

        await self.update_poll(interaction, f"<:VERIFIED:1418921885692989532> You voted for **{choice_label}**")

    async def add_option(self, interaction: discord.Interaction):
        if not await self._ensure_poll_active(interaction):
            return

        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("⚠️ Only the poll creator can add options.", ephemeral=True)

        modal = AddOptionModal(self)
        await interaction.response.send_modal(modal)

    async def remove_vote(self, interaction: discord.Interaction):
        if not await self._ensure_poll_active(interaction):
            return

        removed = False
        for opt in self.votes:
            if interaction.user.id in self.votes[opt]:
                self.votes[opt].remove(interaction.user.id)
                removed = True

        if removed:
            if self.message:
                try:
                    await save_active_poll(
                        message_id=self.message.id,
                        guild_id=self.message.guild.id,
                        channel_id=self.message.channel.id,
                        author_id=self.author.id,         
                        question=self.question,
                        options=self.options,
                        votes=self.votes,
                        end_time=self.end_time
                    )
                except aiosqlite.Error as e:
                    print(f"[Poll DB Save Error on remove] {e}")
            await self.update_poll(interaction, "❌ Your vote was removed.")
        else:
            await interaction.response.send_message("⚠️ You haven't voted yet.", ephemeral=True)

    async def end_poll(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("⚠️ Only the poll creator can end this poll.", ephemeral=True)

        if self.updater_task and not self.updater_task.done():
            self.updater_task.cancel()

        await interaction.response.defer(ephemeral=True)
        await self.on_timeout()

    async def update_poll(self, interaction: discord.Interaction, ephemeral_msg: str):
        embed = self.make_poll_embed()
        if self.message:
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.errors.HTTPException as e:
                err_str = str(e).lower()
                if "embed size" in err_str or "exceeds" in err_str:
                    for bl in (8, 6, 4, 2):
                        try:
                            smaller = self.make_poll_embed(bar_len=bl)
                            await self.message.edit(embed=smaller, view=self)
                            embed = smaller
                            break
                        except Exception:
                            continue
                    else:
                        try:
                            fetched = await self.message.channel.fetch_message(self.message.id)
                            self.message = fetched
                            await self.message.edit(embed=embed, view=self)
                        except Exception:
                            try:
                                new_msg = await self.message.channel.send(embed=embed, view=self)
                                self.message = new_msg
                            except Exception as ex:
                                print(f"[update_poll] failed to update/send poll message: {ex}")
                else:
                    try:
                        fetched = await self.message.channel.fetch_message(self.message.id)
                        self.message = fetched
                        await self.message.edit(embed=embed, view=self)
                    except Exception:
                        try:
                            new_msg = await self.message.channel.send(embed=embed, view=self)
                            self.message = new_msg
                        except Exception as ex:
                            print(f"[update_poll] failed to recover from HTTPException: {ex}")
            except Exception as e:
                try:
                    new_msg = await self.message.channel.send(embed=embed, view=self)
                    self.message = new_msg
                except Exception as ex:
                    print(f"[update_poll] unexpected failure editing/sending message: {ex}")
        else:
            try:
                sent = await interaction.channel.send(embed=embed, view=self)
                self.message = sent
            except Exception:
                pass
        try:
            await interaction.response.send_message(ephemeral_msg, ephemeral=True)
        except discord.errors.InteractionResponded:
            try:
                await interaction.followup.send(ephemeral_msg, ephemeral=True)
            except Exception:
                pass
        except Exception:
            pass

    def make_poll_embed(self, closed: bool = False, bar_len: int = 10):
        total_votes = sum(len(v) for v in self.votes.values())
        colors = ["🟦", "🟥", "🟩", "🟨", "🟪", "🟧", "🟫"]

        embed = discord.Embed(
            title=f"<:CHART:1418908749749420085>  {self.question}",
            color=discord.Color.blurple()
        )

        for i, (opt, users) in enumerate(self.votes.items(), 1):
            count = len(users)
            percent = (count / total_votes * 100) if total_votes > 0 else 0
            filled = int(percent / 100 * bar_len) if bar_len > 0 else 0
            empty = max(0, bar_len - filled)
            color = colors[i % len(colors)]
            bar = color * filled + "<:Gray_Large_Square:1418999479557685380>" * empty

            name = opt
            embed.add_field(
                name=name,
                value=f"{bar} `{percent:.0f}% ({count})`",
                inline=False
            )

        if closed:
            if self.end_time:
                status = (
                    f"<:Locked:1419005340812316893> Poll closed <t:{int(self.end_time.timestamp())}:R>\n"
                    f"<:SecretBox:1418986878949916722> Votes are anonymous\n"
                    f"With total of `{total_votes} votes`" 
                )
            else:
                status = f"<:Locked:1419005340812316893> Poll closed\n<:SecretBox:1418986878949916722> Votes are anonymous\n{total_votes} votes"
        elif self.end_time:
            status = (
                f"<:TIME:1415961777912545341> Poll closes <t:{int(self.end_time.timestamp())}:R>\n"
                f"<:SecretBox:1418986878949916722> Votes are anonymous\n"
                f"Total Votes: `{total_votes}` votes"
            )
        else:
            status = f"<:SecretBox:1418986878949916722> Votes are anonymous\n{total_votes} votes"

        embed.add_field(name="\u200b", value=status, inline=False)
        return embed

class AddOptionModal(ui.Modal, title="Add Poll Options"):
    opt1 = ui.TextInput(label="Option 1 (optional)", required=False, max_length=100,
                        placeholder=MODAL_PLACEHOLDER)
    opt2 = ui.TextInput(label="Option 2 (optional)", required=False, max_length=100,
                        placeholder=MODAL_PLACEHOLDER)
    opt3 = ui.TextInput(label="Option 3 (optional)", required=False, max_length=100,
                        placeholder=MODAL_PLACEHOLDER)
    opt4 = ui.TextInput(label="Option 4 (optional)", required=False, max_length=100,
                        placeholder=MODAL_PLACEHOLDER)
    opt5 = ui.TextInput(label="Option 5 (optional)", required=False, max_length=100,
                        placeholder=MODAL_PLACEHOLDER)

    def __init__(self, poll_view: "PollView"):
        super().__init__()
        self.poll_view = poll_view
        self.description = "Note: Discord only allows a maximum of 25 options per select menu."

    async def on_submit(self, interaction: discord.Interaction):
        
        if not self.poll_view.message:
            return await interaction.response.send_message("⚠️ Poll message no longer exists.", ephemeral=True)
        
        new_opts_raw = [
            self.opt1.value.strip(),
            self.opt2.value.strip(),
            self.opt3.value.strip(),
            self.opt4.value.strip(),
            self.opt5.value.strip()
        ]
        new_opts = [o for o in new_opts_raw if o]

        if not new_opts:
            return await interaction.response.send_message(
                "⚠️ No new options were added.", ephemeral=True
            )

        normalized_existing = [o.lower() for o in self.poll_view.options]
        for opt in new_opts:
            if opt.lower() in normalized_existing:
                return await interaction.response.send_message(
                    "<:MinoriConfused:1415707082988060874> You can't add duplicate options.",
                    ephemeral=True
                )
        MAX_OPTIONS = 14 
        if len(self.poll_view.options) + len(new_opts) > MAX_OPTIONS:
            return await interaction.response.send_message(
                f"⚠️ You can only add up to {MAX_OPTIONS} options.", ephemeral=True
            )

        for opt in new_opts:
            self.poll_view.options.append(opt)
            self.poll_view.votes[opt] = set()
            select: discord.ui.Select = next(
                (i for i in self.poll_view.children if isinstance(i, discord.ui.Select)), None
            )
            if select:
                select.options = [discord.SelectOption(label=opt, value=str(idx)) 
                                for idx, opt in enumerate(self.poll_view.options)]
                select.placeholder = "Select one answer (scroll for more)" if len(self.poll_view.options) > 10 else "Select one answer"

        embed = self.poll_view.make_poll_embed()
        await self.poll_view.message.edit(embed=embed, view=self.poll_view)

        try:
            await save_active_poll(
                message_id=self.poll_view.message.id,
                guild_id=self.poll_view.message.guild.id,
                channel_id=self.poll_view.message.channel.id,
                author_id=self.poll_view.author.id,          # <-- required now
                question=self.poll_view.question,
                options=self.poll_view.options,
                votes=self.poll_view.votes,
                end_time=self.poll_view.end_time
            )
        except aiosqlite.Error as e:
            print(f"[Poll DB Save Error on add_option] {e}")

        await interaction.response.send_message(
            f"<:VERIFIED:1418921885692989532> Added {len(new_opts)} option(s). Total options: {len(self.poll_view.options)}",
            ephemeral=True
        )
        
class PollInputModal(ui.Modal, title="Create Poll"):
    question = ui.TextInput(label="Question", placeholder="What's the poll about?", required=True, max_length=200)
    opt1 = ui.TextInput(label="Option 1 (required)", placeholder="First option (required)", required=True, max_length=100)
    opt2 = ui.TextInput(label="Option 2 (required)", placeholder="Second option (required)", required=True, max_length=100)
    opt3 = ui.TextInput(label="Option 3 (optional)", placeholder="Third option (optional)", required=False, max_length=100)
    opt4 = ui.TextInput(label="Option 4 (optional)", placeholder="Fourth option (optional)", required=False, max_length=100)

    def __init__(self, ctx: commands.Context, timeout_seconds: Optional[int] = None):
        super().__init__()
        self.ctx = ctx
        self.timeout_seconds = timeout_seconds
        
    async def on_submit(self, interaction: discord.Interaction):
        raw_opts = [
            self.opt1.value.strip(),
            self.opt2.value.strip(),
            self.opt3.value.strip(),
            self.opt4.value.strip()
        ]
        opts = [o for o in raw_opts if o]

        if len(opts) < 2:
            return await interaction.response.send_message(
                "⚠️ Please provide at least two options (Option 1 and Option 2 are required).",
                ephemeral=True
            )

        normalized = [o.strip().lower() for o in opts]
        if len(set(normalized)) != len(normalized):
            return await interaction.response.send_message(
                "<:MinoriConfused:1415707082988060874> You cant make same options",
                ephemeral=True
            )
        try:
            view = PollView(self.question.value, opts, self.ctx.author, timeout=self.timeout_seconds)
            embed = view.make_poll_embed()
            msg = await interaction.channel.send(embed=embed, view=view)
            view.message = msg
            end_time = (datetime.now(timezone.utc) + timedelta(seconds=self.timeout_seconds)) if self.timeout_seconds else None
            await save_active_poll(
                message_id=msg.id,
                guild_id=interaction.guild.id,
                channel_id=interaction.channel.id,
                author_id=interaction.user.id,             
                question=self.question.value,
                options=opts,
                votes=view.votes,
                end_time=end_time
            )

            try:
                await interaction.response.send_message("<:VERIFIED:1418921885692989532> Poll successfully created!", ephemeral=True)
            except discord.errors.InteractionResponded:
                await interaction.followup.send("<:VERIFIED:1418921885692989532> Poll successfully created!", ephemeral=True)
        except aiosqlite.Error as e:
            print(f"[Poll Create Error] {e}")
            try:
                await interaction.response.send_message(f"⚠️ Failed to create poll: {e}", ephemeral=True)
            except discord.errors.InteractionResponded:
                await interaction.followup.send(f"⚠️ Failed to create poll: {e}", ephemeral=True)
                
