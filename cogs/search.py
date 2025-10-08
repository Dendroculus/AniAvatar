import discord
from discord.ext import commands
from discord.ui import View, Select
import aiohttp
import random
from urllib.parse import quote
import os
from dotenv import load_dotenv

sent_image_cache = {}
anilist_cache = {} 
load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")

ANILIST_API = "https://graphql.anilist.co"

sent_media_cache = {}   

class Search(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="anime", description="Search for an anime by name")
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def anime(self, ctx: commands.Context, *, query: str):

        query_str = """
        query ($search: String) {
        Page(perPage: 5) {
            media(search: $search, type: ANIME) {
            id
            title {
                romaji
                english
                native
            }
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
            studios(isMain: true) {
                nodes {
                name
                }
            }
            genres
            coverImage {
                large
                medium
            }
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
            if genres:
                genres = " ".join(f"`{g}`" for g in genres)
            else:
                genres = "N/A"

            embed.add_field(name="Genres", value=genres, inline=False)

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

        NOISE_WORDS = {"pfp", "pfps", "hd", "avatar", "icon", "anime", "wallpaper", "image", "picture", "pic", "profile"}
        per_call_timeout = aiohttp.ClientTimeout(total=10)


        async def fetch_anilist_character(query_name: str):
            query_str = """
            query ($search: String) {
                Character(search: $search) {
                    id
                    name { full }
                    image { large medium }
                    media { nodes { id type format } }
                }
            }"""
            variables = {"search": query_name}
            try:
                async with aiohttp.ClientSession(timeout=per_call_timeout) as session:
                    async with session.post(ANILIST_API, json={"query": query_str, "variables": variables}) as resp:
                        if resp.status != 200:
                            return None
                        try:
                            data = await resp.json()
                        except Exception:
                            return None
            except Exception:
                return None
            return data.get("data", {}).get("Character")

        async def fetch_jikan_character(query_name: str):
            url = f"https://api.jikan.moe/v4/characters?q={quote(query_name)}&limit=1"
            try:
                async with aiohttp.ClientSession(timeout=per_call_timeout) as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            return None
                        try:
                            data = await resp.json()
                        except Exception:
                            return None
            except Exception:
                return None

            results = data.get("data") or []
            if not results:
                return None

            c = results[0]
            image = (c.get("images") or {}).get("jpg", {}).get("image_url")
            return {"id": c.get("mal_id"), "name": {"full": c.get("name")}, "image": {"large": image, "medium": image}}

        async def is_image_url_ok(session: aiohttp.ClientSession, url: str, timeout_obj: aiohttp.ClientTimeout) -> bool:
            if not url:
                return False
            try:
                async with session.head(url, timeout=timeout_obj) as resp:
                    ct = resp.headers.get("Content-Type", "")
                    if resp.status == 200 and ct and ct.startswith("image"):
                        return True
            except Exception:
                pass
            try:
                async with session.get(url, timeout=timeout_obj) as resp:
                    ct = resp.headers.get("Content-Type", "")
                    return resp.status == 200 and ct and ct.startswith("image")
            except Exception:
                return False

        def char_has_anime_media(char_obj):
            if not char_obj:
                return False
            media = char_obj.get("media") or {}
            nodes = media.get("nodes") or []
            for n in nodes:
                if (n.get("type") or "").upper() == "ANIME":
                    return True
            return False

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

        original_query = name
        cleaned_words = [w for w in original_query.split() if w.lower() not in NOISE_WORDS]
        cleaned_query = " ".join(cleaned_words).strip() or original_query

        char = await fetch_anilist_character(original_query)

        if char and not char_has_anime_media(char):
            if cleaned_query != original_query:
                alt_char = await fetch_anilist_character(cleaned_query)
                if alt_char and char_has_anime_media(alt_char):
                    char = alt_char

        if char and not char_has_anime_media(char):
            return await reply("❌ Could not find an anime character matching your query. Try a full character name (e.g. `Kaoruko Waguri`).")

        official_image = None
        if char:
            official_image = (char.get("image") or {}).get("large") or (char.get("image") or {}).get("medium")
            if official_image:
                try:
                    async with aiohttp.ClientSession(timeout=per_call_timeout) as session:
                        ok = await is_image_url_ok(session, official_image, per_call_timeout)
                    if not ok:
                        official_image = None
                except Exception:
                    official_image = None

        if not char:
            jikan_char = await fetch_jikan_character(original_query)
            if not jikan_char:
                return await reply("❌ Could not find an anime character matching your query. Try a full character name (e.g. `Kaoruko Waguri`).")
            char = jikan_char
            candidate = (char.get("image") or {}).get("large") or (char.get("image") or {}).get("medium")
            if candidate:
                try:
                    async with aiohttp.ClientSession(timeout=per_call_timeout) as session:
                        ok = await is_image_url_ok(session, candidate, per_call_timeout)
                    if ok:
                        official_image = candidate
                    else:
                        official_image = None
                except Exception:
                    official_image = None
        else:
            if not official_image:
                jikan_char = await fetch_jikan_character(original_query)
                if jikan_char:
                    candidate = (jikan_char.get("image") or {}).get("large") or (jikan_char.get("image") or {}).get("medium")
                    if candidate:
                        try:
                            async with aiohttp.ClientSession(timeout=per_call_timeout) as session:
                                ok = await is_image_url_ok(session, candidate, per_call_timeout)
                            if ok:
                                official_image = candidate
                            else:
                                official_image = official_image  
                        except Exception:
                            pass

        cache_key = None
        selected_image = None
        source = None

        if not official_image:
            character_display_name = char["name"]["full"] if char else original_query
            if not GOOGLE_API_KEY or not SEARCH_ENGINE_ID:
                return await reply("❌ Could not find an anime character matching your query. Try a full character name (e.g. `Kaoruko Waguri`).")

            search_query = f"{character_display_name} anime pfp"
            query = quote(search_query)
            url = (
                f"https://www.googleapis.com/customsearch/v1?"
                f"key={GOOGLE_API_KEY}&cx={SEARCH_ENGINE_ID}&searchType=image&q={query}"
            )
            try:
                async with aiohttp.ClientSession(timeout=per_call_timeout) as session:
                    async with session.get(url) as resp:
                        try:
                            data = await resp.json()
                        except Exception:
                            data = {}
            except Exception:
                return await reply("❌ Failed to fetch images from Google API. Try again later.")

            items = data.get("items") or []
            valid_items = [
                item.get("link") for item in items
                if isinstance(item.get("link"), str) and item["link"].lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            ]
            if not valid_items:
                return await reply(f"❌ No valid images found for **{character_display_name}** via Google.")

            async with aiohttp.ClientSession(timeout=per_call_timeout) as session:
                random.shuffle(valid_items)
                chosen = None
                for link in valid_items:
                    try:
                        ok = await is_image_url_ok(session, link, per_call_timeout)
                        if ok:
                            chosen = link
                            break
                    except Exception:
                        continue

            if not chosen:
                return await reply(f"❌ No reachable images found for **{character_display_name}** via Google.")
            selected_image = chosen
            source = "Google API"

        else:
            character_name = char["name"]["full"]
            cache_key = f"al_{char['id']}"
            if cache_key not in anilist_cache:
                anilist_cache[cache_key] = {"anilist_images": [], "google": []}

            if official_image and official_image not in anilist_cache[cache_key]["anilist_images"]:
                selected_image = official_image
                anilist_cache[cache_key]["anilist_images"].append(official_image)
                source = "AniList"
            else:
                if not GOOGLE_API_KEY or not SEARCH_ENGINE_ID:
                    return await reply(f"❌ No new images available for **{character_name}** (Google API not configured).")

                search_query = f"{character_name} anime pfp"
                query = quote(search_query)
                url = (
                    f"https://www.googleapis.com/customsearch/v1?"
                    f"key={GOOGLE_API_KEY}&cx={SEARCH_ENGINE_ID}&searchType=image&q={query}"
                )

                try:
                    async with aiohttp.ClientSession(timeout=per_call_timeout) as session:
                        async with session.get(url) as resp:
                            try:
                                data = await resp.json()
                            except Exception:
                                data = {}
                except Exception:
                    return await reply("❌ Failed to fetch images from Google API. Try again later.")

                items = data.get("items") or []
                valid_items = [
                    item.get("link") for item in items
                    if isinstance(item.get("link"), str) and item["link"].lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
                ]

                if not valid_items:
                    return await reply(f"❌ No valid images found for **{character_name}** via Google.")

                unsent = [
                    img for img in valid_items
                    if img not in anilist_cache[cache_key]["google"] and img not in anilist_cache[cache_key]["anilist_images"]
                ]

                if not unsent:
                    anilist_cache[cache_key]["google"] = []
                    unsent = [img for img in valid_items if img not in anilist_cache[cache_key]["anilist_images"]]

                if not unsent:
                    return await reply(f"❌ No new images available for **{character_name}** right now.")

                async with aiohttp.ClientSession(timeout=per_call_timeout) as session:
                    random.shuffle(unsent)
                    chosen = None
                    for link in unsent:
                        try:
                            ok = await is_image_url_ok(session, link, per_call_timeout)
                            if ok:
                                chosen = link
                                break
                        except Exception:
                            continue

                if not chosen:
                    return await reply(f"❌ No reachable images found for **{character_name}** via Google.")
                selected_image = chosen
                anilist_cache[cache_key]["google"].append(selected_image)
                source = "Google API"

        if not selected_image:
            return await reply("❌ Could not find an anime character matching your query. Try a full character name (e.g. `Kaoruko Waguri`).")

        char_display = char["name"]["full"] if char else name
        embed = discord.Embed(title=f"Anime PFP for {char_display}", color=discord.Color.purple())
        embed.set_image(url=selected_image)
        embed.set_footer(text=f"Source: {source}")
        return await reply(embed=embed)

async def setup(bot):
    await bot.add_cog(Search(bot))
    print("📦 Loaded search cog.")

