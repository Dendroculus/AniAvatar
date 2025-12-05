import os
from collections import OrderedDict
from typing import List, Optional, Set, Tuple

import aiohttp
import discord
from discord.ext import commands
from discord.ui import Select, View
from dotenv import load_dotenv

from cogs.utils.anime_api import (
    char_has_anime_media,
    fetch_character_by_name,
    first_reachable_image,
    google_image_search,
    is_image_url_ok,
)

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")

ANILIST_API = "https://graphql.anilist.co"


class Search(commands.Cog):
    """
    Search cog:
    - /anime: AniList anime info with select menu
    - /animepfp: Anime character PFPs (AniList first image, then Google), count 1–4, with select menu for disambiguation
    """

    NOISE_WORDS = {"pfp", "pfps", "hd", "avatar", "icon", "anime", "wallpaper", "image", "picture", "pic", "profile"}
    CACHE_MAX_KEYS = 200

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._anilist_cache: OrderedDict[str, dict] = OrderedDict()

    # ---------------- Cache helpers ---------------- #

    def _cache_get(self, key: str | None) -> dict:
        if key is None:
            return {"anilist_images": [], "google": []}
        entry = self._anilist_cache.get(key)
        if entry is None:
            entry = {"anilist_images": [], "google": []}
            self._anilist_cache[key] = entry
        self._anilist_cache.move_to_end(key, last=True)
        if len(self._anilist_cache) > self.CACHE_MAX_KEYS:
            self._anilist_cache.popitem(last=False)
        return entry

    def _cache_add_google(self, key: str | None, url: str):
        if key is None:
            return
        entry = self._cache_get(key)
        if url not in entry["google"]:
            entry["google"].append(url)

    def _cache_add_anilist(self, key: str | None, url: str):
        if key is None:
            return
        entry = self._cache_get(key)
        if url not in entry["anilist_images"]:
            entry["anilist_images"].append(url)

    # ---------------- Small utils ---------------- #

    def _strip_noise(self, query: str) -> str:
        words = [w for w in (query or "").split() if w.lower() not in self.NOISE_WORDS]
        return " ".join(words).strip() or (query or "").strip()

    # ---------------- Character search ---------------- #

    async def _search_characters(self, query: str, limit: int = 10) -> List[dict]:
        """
        Return candidate characters from AniList then Jikan.
        Works even if fetch_character_by_name doesn't support multiple=True.
        """
        candidates: List[dict] = []

        # Try AniList multiple, fallback to single
        try:
            al = await fetch_character_by_name(query, prefer="AniList", multiple=True, limit=limit)
            if isinstance(al, list):
                candidates.extend(al)
            elif al:
                candidates.append(al)
        except TypeError:
            al = await fetch_character_by_name(query, prefer="AniList")
            if al:
                candidates.append(al)

        # Try Jikan multiple, fallback to single
        try:
            jk = await fetch_character_by_name(query, prefer="Jikan", multiple=True, limit=limit)
            if isinstance(jk, list):
                candidates.extend(jk)
            elif jk:
                candidates.append(jk)
        except TypeError:
            jk = await fetch_character_by_name(query, prefer="Jikan")
            if jk:
                candidates.append(jk)

        # De-duplicate by (source, id)
        seen: Set[Tuple[str, int]] = set()
        unique: List[dict] = []
        for c in candidates:
            src = str(c.get("source") or "").lower() or "unknown"
            cid = int(c.get("id") or 0)
            key = (src, cid)
            if key in seen:
                continue
            seen.add(key)
            unique.append(c)

        return unique[:limit]

    # ---------------- Google image lookup ---------------- #

    async def _find_google_image(
        self,
        character_name: str,
        cache_key: str | None,
        timeout: aiohttp.ClientTimeout,
        exclude: Set[str] | None = None,
    ) -> Optional[str]:
        exclude = exclude or set()
        if not GOOGLE_API_KEY or not SEARCH_ENGINE_ID:
            return None

        links = await google_image_search(f"{character_name} anime pfp", GOOGLE_API_KEY, SEARCH_ENGINE_ID)
        if not links:
            return None

        candidates = [l for l in links if l not in exclude]
        if cache_key:
            entry = self._cache_get(cache_key)
            unsent = [l for l in candidates if l not in entry["google"] and l not in entry["anilist_images"]]
            candidates = unsent or [l for l in candidates if l not in entry["anilist_images"]]

        if not candidates:
            return None

        chosen = await first_reachable_image(candidates, timeout)
        if chosen and cache_key:
            self._cache_add_google(cache_key, chosen)
        return chosen

    # ---------------- Pick images with AniList-first, then Google ---------------- #

    async def _pick_images_for_character(
        self,
        char: dict,
        count: int,
        timeout: aiohttp.ClientTimeout,
    ) -> List[Tuple[str, str]]:
        """
        Up to `count` images:
        - First slot: AniList image if not already used before.
        - Remaining slots: Google images (avoiding duplicates per call and cache).
        - If nothing found, fallback to AniList even if reused.
        """
        count = max(1, min(4, count))
        results: List[Tuple[str, str]] = []
        used: Set[str] = set()

        char_name = (char.get("name") or {}).get("full", "") or "Unknown"
        cache_key = f"al_{char.get('id')}" if char.get("source") == "AniList" and char.get("id") else None

        entry = self._cache_get(cache_key)
        official_image = (char.get("image") or {}).get("large") or (char.get("image") or {}).get("medium")
        official_used_before = bool(official_image and official_image in entry["anilist_images"])

        async def maybe_add_official():
            if not official_image or official_image in used:
                return False
            if official_used_before:
                return False
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    ok = await is_image_url_ok(session, official_image, timeout)
                if not ok:
                    return False
            except Exception:
                return False
            results.append((official_image, char.get("source") or "AniList"))
            used.add(official_image)
            self._cache_add_anilist(cache_key, official_image)
            return True

        # 1) First slot: AniList if fresh
        await maybe_add_official()

        # 2) Fill with Google
        while len(results) < count:
            google_img = await self._find_google_image(char_name, cache_key, timeout, exclude=used)
            if google_img:
                results.append((google_img, "Google API"))
                used.add(google_img)
            else:
                break

        # 3) Fallback: if nothing, allow reusing official
        if not results and official_image:
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    ok = await is_image_url_ok(session, official_image, timeout)
                if ok:
                    results.append((official_image, char.get("source") or "AniList"))
                    used.add(official_image)
                    self._cache_add_anilist(cache_key, official_image)
            except Exception:
                pass

        return results

    # ---------------- Anime search command ---------------- #

    @commands.hybrid_command(name="anime", description="Search for an anime by name")
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def anime(self, ctx: commands.Context, *, query: str):
        query_str = """
        query ($search: String) {
        Page(perPage: 5) {
            media(search: $search, type: ANIME) {
            id
            title { romaji english native }
            description(asHtml: false)
            episodes
            status
            duration
            startDate { year month day }
            endDate { year month day }
            season
            averageScore
            popularity
            favourites
            format
            source
            studios(isMain: true) { nodes { name } }
            genres
            coverImage { large medium }
            bannerImage
            siteUrl
            }
        }
        }
        """
        variables = {"search": query}

        async with aiohttp.ClientSession() as session:
            async with session.post(ANILIST_API, json={"query": query_str, "variables": variables}) as resp:
                if resp.status != 200:
                    return await ctx.send("❌ Could not fetch anime info right now.")
                data = await resp.json()

        results = data.get("data", {}).get("Page", {}).get("media", [])
        if not results:
            return await ctx.send(f"❌ No results found for `{query}`.")

        options = []
        for anime in results:
            title = anime["title"]["english"] or anime["title"]["romaji"]
            episodes = anime.get("episodes") or "N/A"
            season = anime.get("season") or "N/A"
            options.append(
                discord.SelectOption(
                    label=title[:100],
                    description=f"Episodes: {episodes} | Season: {season}"[:100],
                    value=str(anime["id"]),
                )
            )

        async def select_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("This is not your command!", ephemeral=True)
                return

            await interaction.response.defer()
            anime_id = int(interaction.data["values"][0])
            anime_data = next(a for a in results if a["id"] == anime_id)

            title = anime_data["title"]["english"] or anime_data["title"]["romaji"]
            url = anime_data.get("siteUrl")
            description = anime_data.get("description") or "No description available."
            description = description.replace("<br>", "\n").replace("<i>", "").replace("</i>", "")
            if len(description) > 4096:
                description = description[:4093] + "..."

            embed = discord.Embed(title=title, url=url, description=description, color=discord.Color.blurple())
            if anime_data.get("coverImage", {}).get("medium"):
                embed.set_thumbnail(url=anime_data["coverImage"]["medium"])
            if anime_data.get("bannerImage"):
                embed.set_image(url=anime_data["bannerImage"])

            embed.add_field(name="Episodes", value=anime_data.get("episodes", "N/A"), inline=True)
            embed.add_field(name="Status", value=anime_data.get("status", "N/A").title(), inline=True)

            start = anime_data.get("startDate", {})
            end = anime_data.get("endDate", {})
            start_str = (
                f"{start.get('year','N/A')}-{start.get('month','??')}-{start.get('day','??')}" if start.get("year") else "N/A"
            )
            end_str = (
                f"{end.get('year','N/A')}-{end.get('month','??')}-{end.get('day','??')}" if end.get("year") else "N/A"
            )
            embed.add_field(name="Start Date", value=start_str, inline=True)
            embed.add_field(name="End Date", value=end_str, inline=True)

            embed.add_field(name="Duration", value=f"{anime_data.get('duration', 'N/A')} min/ep", inline=True)
            embed.add_field(
                name="Studio",
                value=anime_data["studios"]["nodes"][0]["name"] if anime_data["studios"]["nodes"] else "N/A",
                inline=True,
            )
            embed.add_field(name="Source", value=anime_data.get("source", "N/A"), inline=True)

            embed.add_field(name="Score", value=f"{anime_data.get('averageScore', 'N/A')}%", inline=True)
            embed.add_field(name="Popularity", value=str(anime_data.get("popularity", "N/A")), inline=True)
            embed.add_field(name="Favourites", value=str(anime_data.get("favourites", "N/A")), inline=True)

            genres = anime_data.get("genres", [])
            genres_str = " ".join(f"`{g}`" for g in genres) if genres else "N/A"
            embed.add_field(name="Genres", value=genres_str, inline=False)

            embed.set_footer(
                text="Provided by AniList", icon_url="https://anilist.co/img/icons/android-chrome-512x512.png"
            )
            await interaction.edit_original_response(embed=embed, view=None)

        select = Select(placeholder="Choose an anime...", options=options)
        select.callback = select_callback
        view = View()
        view.add_item(select)
        await ctx.send("Select an anime from the search results:", view=view)

    @commands.hybrid_command(
        name="animepfp",
        description="Fetch one or more anime character PFPs (AniList first, then Google). Count: 1–4 (default 1).",
    )
    @commands.guild_only()
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def animepfp(self, ctx: commands.Context, name: str, count: int = 1):
        name = (name or "").strip()
        if not name:
            return await ctx.send("❌ Please provide a character name.")

        count = max(1, min(4, count))
        timeout = aiohttp.ClientTimeout(total=10)
        interaction = getattr(ctx, "interaction", None)
        is_slash = interaction is not None

        if is_slash:
            try:
                await interaction.response.defer()
            except Exception:
                pass

        async def reply(content=None, *, embed=None, view=None):
            if is_slash and interaction is not None:
                return await interaction.followup.send(content=content, embed=embed, view=view)
            else:
                return await ctx.send(content=content, embed=embed, view=view)

        # Search candidates (AniList + Jikan)
        candidates = await self._search_characters(name, limit=10)
        if not candidates:
            return await reply(f"`{name}` was not found in anime databases.")

        # If multiple, show dropdown; if single, go straight to images
        if len(candidates) > 1:
            options = []
            for idx, c in enumerate(candidates[:25]):  # Discord max 25
                cname = (c.get("name") or {}).get("full", "") or "Unknown"
                src = c.get("source") or "Character"
                label = cname[:100]
                desc = str(src)[:100]
                options.append(discord.SelectOption(label=label, description=desc, value=str(idx)))

            view = View(timeout=30)
            select = Select(placeholder="Choose the exact character...", options=options, min_values=1, max_values=1)

            async def on_select(select_interaction: discord.Interaction):
                if select_interaction.user.id != ctx.author.id:
                    await select_interaction.response.send_message("This is not your command!", ephemeral=True)
                    return
                try:
                    await select_interaction.response.defer()
                except Exception:
                    pass

                try:
                    idx = int(select_interaction.data.get("values", [None])[0])
                except Exception:
                    await select_interaction.followup.send("Something went wrong with your selection.", ephemeral=True)
                    return

                if idx < 0 or idx >= len(candidates):
                    await select_interaction.followup.send("Invalid selection.", ephemeral=True)
                    return

                char = candidates[idx]
                char_name = (char.get("name") or {}).get("full", "") or name

                if not char_has_anime_media(char):
                    await select_interaction.edit_original_response(
                        content=f"`{char_name}` is not an anime character. Please search for anime characters only.",
                        view=None,
                        embed=None,
                    )
                    return

                images = await self._pick_images_for_character(char, count, timeout)
                if not images:
                    await select_interaction.edit_original_response(
                        content=f"❌ No reachable images found for **{char_name}**.",
                        view=None,
                        embed=None,
                    )
                    return

                await select_interaction.edit_original_response(
                    content=f"Showing PFPs for **{char_name}**:",
                    view=None,
                    embed=None,
                )
                for url, source in images:
                    embed = discord.Embed(
                        title=f"Anime PFP for {char_name}",
                        color=discord.Color.purple(),
                    )
                    embed.set_image(url=url)
                    embed.set_footer(text=f"Source: {source}")
                    await select_interaction.followup.send(embed=embed)

            select.callback = on_select  # important: assign callback (avoid un-awaited coroutine warning)
            view.add_item(select)
            return await reply("Multiple characters found. Please pick one:", view=view)

        # Single candidate path
        char = candidates[0]
        char_name = (char.get("name") or {}).get("full", "") or name

        if not char_has_anime_media(char):
            return await reply(f"`{char_name}` is not an anime character. Please search for anime characters only.")

        images = await self._pick_images_for_character(char, count, timeout)
        if not images:
            return await reply(f"❌ No reachable images found for **{char_name}**.")

        for url, source in images:
            embed = discord.Embed(
                title=f"Anime PFP for {char_name}",
                color=discord.Color.purple(),
            )
            embed.set_image(url=url)
            embed.set_footer(text=f"Source: {source}")
            await reply(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Search(bot))