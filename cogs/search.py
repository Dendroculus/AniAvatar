import discord
from discord.ext import commands
from discord.ui import View, Select
import aiohttp
import os
from dotenv import load_dotenv
from collections import OrderedDict

from cogs.utils.anime_api import (
    fetch_character_by_name,
    char_has_anime_media,
    is_image_url_ok,
    google_image_search,
    first_reachable_image,
)

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")

ANILIST_API = "https://graphql.anilist.co"

class Search(commands.Cog):
    NOISE_WORDS = {"pfp", "pfps", "hd", "avatar", "icon", "anime", "wallpaper", "image", "picture", "pic", "profile"}
    CACHE_MAX_KEYS = 200

    def __init__(self, bot):
        self.bot = bot
        self._anilist_cache: OrderedDict[str, dict] = OrderedDict()

    def _cache_get(self, key: str) -> dict:
        entry = self._anilist_cache.get(key)
        if entry is None:
            entry = {"anilist_images": [], "google": []}
            self._anilist_cache[key] = entry
        self._anilist_cache.move_to_end(key, last=True)
        if len(self._anilist_cache) > self.CACHE_MAX_KEYS:
            self._anilist_cache.popitem(last=False)
        return entry

    def _cache_add_google(self, key: str, url: str):
        entry = self._cache_get(key)
        if url not in entry["google"]:
            entry["google"].append(url)

    def _cache_add_anilist(self, key: str, url: str):
        entry = self._cache_get(key)
        if url not in entry["anilist_images"]:
            entry["anilist_images"].append(url)

    def _strip_noise(self, query: str) -> str:
        words = [w for w in (query or "").split() if w.lower() not in self.NOISE_WORDS]
        return " ".join(words).strip() or (query or "").strip()

    async def _find_official_image(self, original_query: str, timeout: aiohttp.ClientTimeout):
        cleaned_query = self._strip_noise(original_query)

        char = await fetch_character_by_name(original_query, prefer="AniList")
        if char and char.get("source") == "AniList" and not char_has_anime_media(char) and cleaned_query != original_query:
            alt = await fetch_character_by_name(cleaned_query, prefer="AniList")
            if alt and char_has_anime_media(alt):
                char = alt

        if char and char.get("source") == "AniList" and not char_has_anime_media(char):
            return char, None

        official_image = None
        if char:
            candidate = (char.get("image") or {}).get("large") or (char.get("image") or {}).get("medium")
            if candidate:
                try:
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        ok = await is_image_url_ok(session, candidate, timeout)
                    if ok:
                        official_image = candidate
                except Exception:
                    official_image = None

        if not char or not official_image:
            jikan_char = await fetch_character_by_name(original_query, prefer="Jikan")
            if jikan_char and not official_image:
                candidate = (jikan_char.get("image") or {}).get("large") or (jikan_char.get("image") or {}).get("medium")
                if candidate:
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        ok = await is_image_url_ok(session, candidate, timeout)
                    if ok:
                        char = jikan_char
                        official_image = candidate

        return char, official_image

    async def _find_google_image(self, character_name: str, cache_key: str | None, timeout: aiohttp.ClientTimeout):
        if not GOOGLE_API_KEY or not SEARCH_ENGINE_ID:
            return None

        links = await google_image_search(f"{character_name} anime pfp", GOOGLE_API_KEY, SEARCH_ENGINE_ID)
        if not links:
            return None

        candidates = links
        if cache_key:
            entry = self._cache_get(cache_key)
            unsent = [l for l in links if l not in entry["google"] and l not in entry["anilist_images"]]
            candidates = unsent or [l for l in links if l not in entry["anilist_images"]]

        chosen = await first_reachable_image(candidates, timeout)
        if chosen and cache_key:
            self._cache_add_google(cache_key, chosen)
        return chosen

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
            options.append(discord.SelectOption(
                label=title[:100],
                description=f"Episodes: {episodes} | Season: {season}"[:100],
                value=str(anime["id"])
            ))

        async def select_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            anime_id = int(interaction.data["values"][0])
            anime_data = next(a for a in results if a["id"] == anime_id)

            title = anime_data["title"]["english"] or anime_data["title"]["romaji"]
            url = anime_data.get("siteUrl")
            description = anime_data.get("description") or "No description available."
            description = description.replace("<br>", "\n").replace("<i>", "").replace("</i>", "")
            if len(description) > 4096:
                description = description[:4093] + "..."

            embed = discord.Embed(
                title=title,
                url=url,
                description=description,
                color=discord.Color.blurple()
            )
            if anime_data.get("coverImage", {}).get("medium"):
                embed.set_thumbnail(url=anime_data["coverImage"]["medium"])
            if anime_data.get("bannerImage"):
                embed.set_image(url=anime_data["bannerImage"])

            embed.add_field(name="Episodes", value=anime_data.get("episodes", "N/A"), inline=True)
            embed.add_field(name="Status", value=anime_data.get("status", "N/A").title(), inline=True)

            start = anime_data.get("startDate", {})
            end = anime_data.get("endDate", {})
            start_str = f"{start.get('year','N/A')}-{start.get('month','??')}-{start.get('day','??')}" if start.get("year") else "N/A"
            end_str = f"{end.get('year','N/A')}-{end.get('month','??')}-{end.get('day','??')}" if end.get("year") else "N/A"
            embed.add_field(name="Start Date", value=start_str, inline=True)
            embed.add_field(name="End Date", value=end_str, inline=True)

            embed.add_field(name="Duration", value=f"{anime_data.get('duration', 'N/A')} min/ep", inline=True)
            embed.add_field(name="Studio", value=anime_data["studios"]["nodes"][0]["name"] if anime_data["studios"]["nodes"] else "N/A", inline=True)
            embed.add_field(name="Source", value=anime_data.get("source", "N/A"), inline=True)

            embed.add_field(name="Score", value=f"{anime_data.get('averageScore', 'N/A')}%", inline=True)
            embed.add_field(name="Popularity", value=str(anime_data.get("popularity", "N/A")), inline=True)
            embed.add_field(name="Favourites", value=str(anime_data.get("favourites", "N/A")), inline=True)

            genres = anime_data.get("genres", [])
            genres_str = " ".join(f"`{g}`" for g in genres) if genres else "N/A"
            embed.add_field(name="Genres", value=genres_str, inline=False)

            embed.set_footer(
                text="Provided by AniList",
                icon_url="https://anilist.co/img/icons/android-chrome-512x512.png"
            )
            await interaction.edit_original_response(embed=embed, view=None)

        select = Select(placeholder="Choose an anime...", options=options)
        select.callback = select_callback
        view = View()
        view.add_item(select)
        await ctx.send("Select an anime from the search results:", view=view)

    @commands.hybrid_command(name="animepfp", description="Fetch an anime character PFP (use the full character name for best results)")
    @commands.guild_only()
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def animepfp(self, ctx: commands.Context, *, name: str):
        name = (name or "").strip()
        if not name:
            return await ctx.send("❌ Please provide a character name.")

        per_call_timeout = aiohttp.ClientTimeout(total=10)

        interaction = getattr(ctx, "interaction", None)
        deferred = False
        if interaction is not None:
            try:
                await interaction.response.defer()
                deferred = True
            except Exception:
                deferred = False

        async def reply(content: str = None, *, embed: discord.Embed = None, ephemeral: bool = False):
            if deferred and interaction is not None:
                if content is not None:
                    return await interaction.followup.send(content, ephemeral=ephemeral)
                else:
                    return await interaction.followup.send(embed=embed, ephemeral=ephemeral)
            else:
                if content is not None:
                    return await ctx.send(content)
                else:
                    return await ctx.send(embed=embed)

        char, official_image = await self._find_official_image(name, per_call_timeout)

        if char and char.get("source") == "AniList" and not char_has_anime_media(char):
            return await reply("❌ Could not find an anime character matching your query. Try a full character name (e.g. `Kaoruko Waguri`).")

        cache_key = None
        selected_image = None
        source = None

        if official_image:
            char_id = char.get("id") if char else None
            character_name = (char.get("name") or {}).get("full") if char else name
            cache_key = f"al_{char_id}" if char_id is not None else None

            if cache_key:
                entry = self._cache_get(cache_key)
                if official_image not in entry["anilist_images"]:
                    self._cache_add_anilist(cache_key, official_image)
            selected_image = official_image
            source = char.get("source") or "AniList"
        else:
            character_name = (char.get("name") or {}).get("full") if char else name
            char_id = char.get("id") if char else None
            cache_key = f"al_{char_id}" if char_id is not None else None

            selected_image = await self._find_google_image(character_name, cache_key, per_call_timeout)
            if not selected_image:
                return await reply(f"❌ No reachable images found for **{character_name}** via Google.")
            source = "Google API"

        char_display = (char.get("name") or {}).get("full") if char else name
        embed = discord.Embed(title=f"Anime PFP for {char_display}", color=discord.Color.purple())
        embed.set_image(url=selected_image)
        embed.set_footer(text=f"Source: {source}")
        return await reply(embed=embed)

async def setup(bot):
    await bot.add_cog(Search(bot))
