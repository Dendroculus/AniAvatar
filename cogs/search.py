import discord
from discord.ext import commands
from discord.ui import View, Select
import aiohttp
from collections import OrderedDict, deque

from utils.anime_api import (
    fetch_character_by_name,
    char_has_anime_media,
    is_image_url_ok,
    google_image_search,
    first_reachable_image,
)
from constants.configs import GOOGLE_API, GOOGLE_SEARCH_ENGINE


ANILIST_API = "https://graphql.anilist.co"


class Search(commands.Cog):
    """Cog providing anime and character avatar utilities.

    Commands:
    - /anime: search for anime metadata (interactive select).
    - /animepfp: fetch 1-4 anime character profile pictures (AniList preferred, Google as fallback).

    PERSONAL NOTE: Google image results require GOOGLE_API_KEY and SEARCH_ENGINE_ID environment variables.
    """
    NOISE_WORDS = {
        "pfp", "pfps", "hd", "avatar", "icon", "anime", "wallpaper",
        "image", "picture", "pic", "profile"
    }
    CACHE_MAX_KEYS = 200

    def __init__(self, bot):
        self.bot = bot
        self._anilist_cache: OrderedDict[str, dict] = OrderedDict()
        # Track sent images per user per character using deque for efficient FIFO: {user_id: {character_id: deque(image_urls)}}
        self._sent_images: dict[int, dict[int, deque]] = {}

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

    def _get_sent_images(self, user_id: int, char_id: int) -> deque:
        """Get the deque of images already sent to this user for this character."""
        if user_id not in self._sent_images:
            self._sent_images[user_id] = {}
        if char_id not in self._sent_images[user_id]:
            self._sent_images[user_id][char_id] = deque(maxlen=100)  # Auto-removes oldest when full
        return self._sent_images[user_id][char_id]

    def _mark_images_as_sent(self, user_id: int, char_id: int, image_urls: list[str]):
        """Mark images as sent to this user for this character."""
        sent_deque = self._get_sent_images(user_id, char_id)
        for url in image_urls:
            sent_deque.append(url)  # deque with maxlen automatically pops from left when full

    def _strip_noise(self, query: str) -> str:
        words = [w for w in (query or "").split() if w.lower() not in self.NOISE_WORDS]
        return " ".join(words).strip() or (query or "").strip()

    async def _find_official_image(self, original_query: str, timeout: aiohttp.ClientTimeout):
        cleaned_query = self._strip_noise(original_query)

        char = await fetch_character_by_name(original_query, prefer="AniList")
        if (
            char
            and char.get("source") == "AniList"
            and not char_has_anime_media(char)
            and cleaned_query != original_query
        ):
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
        if not GOOGLE_API or not GOOGLE_SEARCH_ENGINE:
            return None

        links = await google_image_search(f"{character_name} anime pfp", GOOGLE_API, GOOGLE_SEARCH_ENGINE)
        if not links:
            return None

        candidates = links
        if cache_key:
            entry = self._cache_get(cache_key)
            unsent = [link for link in links if link not in entry["google"] and link not in entry["anilist_images"]]
            candidates = unsent or [link for link in links if link not in entry["anilist_images"]]

        chosen = await first_reachable_image(candidates)
        if chosen and cache_key:
            self._cache_add_google(cache_key, chosen)
        return chosen

    async def _find_multiple_google_images(
        self,
        character_name: str,
        cache_key: str | None,
        timeout: aiohttp.ClientTimeout,
        count: int,
        exclude: set[str],
        search_variation: int = 0,
    ) -> list[str]:
        """Fetch multiple unique Google images for a character.

        Args:
            character_name: Name of the character to search for
            cache_key: Cache key for storing results
            timeout: HTTP timeout for requests
            count: Number of images to fetch
            exclude: Set of image URLs to exclude
            search_variation: Search variation number (0-2) to try different queries
        """
        if not GOOGLE_API or not GOOGLE_SEARCH_ENGINE:
            return []

        # Try different search queries to get more variety
        search_queries = [
            f"{character_name} anime pfp",
            f"{character_name} anime character",
            f"{character_name} anime art",
        ]

        search_query = search_queries[min(search_variation, len(search_queries) - 1)]
        links = await google_image_search(search_query, GOOGLE_API, GOOGLE_SEARCH_ENGINE)
        if not links:
            return []

        # Filter out excluded images first
        candidates = [link for link in links if link not in exclude]

        found_images = []
        for candidate in candidates:
            if len(found_images) >= count:
                break
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    ok = await is_image_url_ok(session, candidate, timeout)
                if ok:
                    found_images.append(candidate)
                    if cache_key:
                        self._cache_add_google(cache_key, candidate)
            except Exception:
                continue

        return found_images

    async def _process_character_selection(self, ctx: commands.Context, char: dict, count: int, count_was_clamped: bool, original_count: int, interaction_deferred: bool):
        """Process the selected character and send the PFP embeds."""
        per_call_timeout = aiohttp.ClientTimeout(total=10)

        interaction = getattr(ctx, "interaction", None)
        user_id = ctx.author.id
        char_id = char.get("id")

        async def send_message(content: str = None, *, embeds: list[discord.Embed] = None, embed: discord.Embed = None, ephemeral: bool = False):
            if embeds is None and embed is not None:
                embeds = [embed]
            if interaction_deferred and interaction is not None:
                if content is not None:
                    return await interaction.followup.send(content, ephemeral=ephemeral)
                else:
                    return await interaction.followup.send(embeds=embeds, ephemeral=ephemeral)
            else:
                if content is not None:
                    return await ctx.send(content)
                else:
                    return await ctx.send(embeds=embeds)

        async def reply(content: str = None, *, embeds: list[discord.Embed] = None, embed: discord.Embed = None, ephemeral: bool = False):
            return await send_message(content, embeds=embeds, embed=embed, ephemeral=ephemeral)

        if not char_has_anime_media(char):
            char_name = (char.get("name") or {}).get("full", "Unknown")
            return await reply(f"`{char_name}` is not an anime character. Please search for anime characters only.")

        char_name = (char.get("name") or {}).get("full", "")
        cache_key = f"al_{char.get('id')}" if char.get("id") else None

        # Get images already sent to this user for this character (as a set for fast lookup)
        sent_deque = self._get_sent_images(user_id, char_id) if char_id else deque()
        sent_images = set(sent_deque)  # Convert to set for O(1) lookup

        # Get official image
        official_image = None
        candidate = (char.get("image") or {}).get("large") or (char.get("image") or {}).get("medium")
        if candidate:
            try:
                async with aiohttp.ClientSession(timeout=per_call_timeout) as session:
                    ok = await is_image_url_ok(session, candidate, per_call_timeout)
                if ok:
                    official_image = candidate
            except Exception:
                official_image = None

        collected_images: list[tuple[str, str]] = []  # (url, source)

        # Add official image if not sent before
        if official_image and official_image not in sent_images:
            if cache_key:
                self._cache_add_anilist(cache_key, official_image)
            collected_images.append((official_image, char.get("source") or "AniList"))

        # Build exclusion set: already sent images + currently collected images
        exclude = sent_images.copy()
        exclude.update({img[0] for img in collected_images})

        # Fetch Google images if needed - try multiple search variations
        if len(collected_images) < count:
            remaining = count - len(collected_images)

            # Try up to 3 different search variations to find enough images
            for variation in range(3):
                if len(collected_images) >= count:
                    break

                google_images = await self._find_multiple_google_images(
                    char_name, cache_key, per_call_timeout, remaining, exclude, search_variation=variation
                )

                for img_url in google_images:
                    if len(collected_images) >= count:
                        break
                    collected_images.append((img_url, "Google API"))
                    exclude.add(img_url)  # Add to exclusion for next variation

                remaining = count - len(collected_images)

        # If still no images, inform user
        if not collected_images:
            return await reply(f"❌ No new images found for **{char_name}**. Try again later for fresh results!")

        # Mark these images as sent (deque will auto-remove oldest if > maxlen)
        if char_id:
            self._mark_images_as_sent(user_id, char_id, [img[0] for img in collected_images])

        # Send clamp warning if needed
        if count_was_clamped:
            await send_message(f"⚠️ You requested {original_count} images, but the maximum is 4. Sending {len(collected_images)} image(s) instead.")

        embeds = []
        for i, (img_url, source) in enumerate(collected_images):
            embed = discord.Embed(
                title=(
                    f"Anime PFP for {char_name}"
                    if len(collected_images) == 1
                    else f"Anime PFP for {char_name} ({i + 1}/{len(collected_images)})"
                ),
                color=discord.Color.purple(),
            )
            embed.set_image(url=img_url)
            embed.set_footer(text=f"Source: {source}")
            embeds.append(embed)

        return await reply(embeds=embeds)

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
            start_str = f"{start.get('year','N/A')}-{start.get('month','??')}-{start.get('day','??')}" if start.get("year") else "N/A"
            end_str = f"{end.get('year','N/A')}-{end.get('month','??')}-{end.get('day','??')}" if end.get("year") else "N/A"
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
                text="Provided by AniList",
                icon_url="https://anilist.co/img/icons/android-chrome-512x512.png",
            )
            await interaction.edit_original_response(embed=embed, view=None)

        select = Select(placeholder="Choose an anime...", options=options)
        select.callback = select_callback
        view = View()
        view.add_item(select)
        await ctx.send("Select an anime from the search results:", view=view)

    @commands.hybrid_command(
        name="animepfp",
        description="Fetch an anime character PFP (use the full character name for best results)",
    )
    @commands.guild_only()
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def animepfp(self, ctx: commands.Context, name: str, count: int = 1):
        """
        Fetch an anime character profile picture.

        Parameters:
        - name: full character name (string). Use exact names for best matches.
        - count: number of images to return (int). Defaults to 1. Values greater than 4 will be clamped to 4 and a warning sent.

        Behavior:
        - Prefers official AniList image when available and not previously served.
        - Falls back to Google Image search (requires GOOGLE_API_KEY and SEARCH_ENGINE_ID).
        - Returns up to `count` unique images (1-4).
        - Tracks sent images per user to avoid duplicates.
        """
        name = (name or "").strip()
        if not name:
            return await ctx.send("❌ Please provide a character name.")

        count_was_clamped = count > 4
        original_count = count
        count = min(4, count)
        if count < 1:
            count = 1

        interaction = getattr(ctx, "interaction", None)
        deferred = False
        if interaction is not None:
            try:
                await interaction.response.defer()
                deferred = True
            except Exception:
                deferred = False

        # Search for multiple characters
        query_str = """
        query ($search: String) {
            Page(perPage: 5) {
                characters(search: $search) {
                    id
                    name { full native alternative }
                    image { large medium }
                    media(type: ANIME, perPage: 1) {
                        nodes { id type }
                    }
                }
            }
        }
        """
        variables = {"search": name}

        async with aiohttp.ClientSession() as session:
            async with session.post(ANILIST_API, json={"query": query_str, "variables": variables}) as resp:
                if resp.status != 200:
                    return await ctx.send("❌ Could not fetch character info right now.")
                data = await resp.json()

        characters = data.get("data", {}).get("Page", {}).get("characters", [])

        # Filter to only anime characters
        anime_characters = [c for c in characters if c.get("media", {}).get("nodes")]

        if not anime_characters:
            return await ctx.send(f"❌ No anime characters found for `{name}`.")

        # If only one character found, process directly
        if len(anime_characters) == 1:
            char = anime_characters[0]
            char["source"] = "AniList"
            return await self._process_character_selection(ctx, char, count, count_was_clamped, original_count, deferred)

        # Multiple characters found - show dropdown
        options = []
        for char in anime_characters[:25]:  # Discord limit is 25 options
            char_name = char["name"]["full"]
            native_name = char["name"].get("native", "")
            description = f"{native_name}" if native_name else "No additional info"
            options.append(
                discord.SelectOption(
                    label=char_name[:100],
                    description=description[:100],
                    value=str(char["id"]),
                )
            )

        async def select_callback(select_interaction: discord.Interaction):
            if select_interaction.user != ctx.author:
                await select_interaction.response.send_message("This is not your command!", ephemeral=True)
                return


            try:
                if not select_interaction.response.is_done():
                    await select_interaction.response.defer()
                await select_interaction.edit_original_response(
                    content="Minori is fetching images for you...",
                    view=None,
                )
            except (discord.NotFound, discord.HTTPException):
                # stale/unknown interaction or already responded or other HTTP issue
                return None
            
            char_id = int(select_interaction.data["values"][0])
            selected_char = next(c for c in anime_characters if c["id"] == char_id)
            selected_char["source"] = "AniList"

            # Update the original message to remove the dropdown
            await select_interaction.edit_original_response(content="Processing your selection...", view=None)

            # Process the selected character
            await self._process_character_selection(ctx, selected_char, count, count_was_clamped, original_count, deferred)

        select = Select(placeholder="Choose the exact character...", options=options)
        select.callback = select_callback
        view = View()
        view.add_item(select)

        if deferred and interaction is not None:
            await interaction.followup.send("Multiple characters found. Please pick one:", view=view)
        else:
            await ctx.send("Multiple characters found. Please pick one:", view=view)


async def setup(bot):
    await bot.add_cog(Search(bot))