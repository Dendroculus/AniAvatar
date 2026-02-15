import discord
from discord.ext import commands
from discord.ui import View, Select
import logging

from utils.anime_api import search_anime, fetch_character_by_name, char_has_anime_media
from search_engine.config import settings
from search_engine.database.connection import DatabasePool
from search_engine.database.queries import INSERT_SEARCH_HISTORY
from search_engine.services.cache_service import CacheService
from search_engine.services.orchestrator import SearchOrchestrator
from search_engine.workers.pinterest import PinterestWorker
from search_engine.workers.google import GoogleWorker
from search_engine.utils.rate_limiter import TokenBucketRateLimiter
from search_engine.utils.http_validator import HTTPValidator

logger = logging.getLogger(__name__)

class Search(commands.Cog):
    """
    Cog providing anime metadata search and the smart Pinterest PFP Search Engine.
    """
    def __init__(self, bot):
        self.bot = bot
        self.db = None
        self.orchestrator = None
        self.pinterest_worker = None
        self.google_worker = None

    async def cog_load(self):
        """Initialize the Search Engine services."""
        logger.info("⚙️ Loading Search Engine components...")
        
        if not self.bot.session:
            logger.error("Bot session is not initialized. Search engine may fail.")
        
        self.db = await DatabasePool.get_instance(
            settings.database_url, 
            settings.min_pool_size, 
            settings.max_pool_size
        )
        
        cache = CacheService(self.db)
        validator = HTTPValidator()
        limiter = TokenBucketRateLimiter(rate=2.0, burst=5)
        
        self.pinterest_worker = PinterestWorker(limiter)
        await self.pinterest_worker.initialize()
        
        self.google_worker = GoogleWorker(
            session=self.bot.session,
            api_key=settings.google_api_key,
            cx=settings.google_search_engine_id
        )

        self.orchestrator = SearchOrchestrator(
            cache, 
            self.pinterest_worker, 
            self.google_worker, 
            validator
        )
        logger.info("✅ Search Engine Ready.")

    async def cog_unload(self):
        if self.pinterest_worker:
            await self.pinterest_worker.close()

    @commands.hybrid_command(
        name="animepfp",
        description="Fetch an anime character PFP (Powered by Pinterest Engine)",
    )
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def animepfp(self, ctx: commands.Context, name: str, count: int = 1):
        """
        Fetch anime profile pictures. Returns unique images per user history.
        """
        name = (name or "").strip()
        count = max(1, min(5, count))

        if not name:
            return await ctx.send("❌ Please provide a character name.")

        if self.db:
            await self.db.execute(INSERT_SEARCH_HISTORY, ctx.author.id, name)

        await ctx.defer()

        search_query = await self._validate_character(ctx, name)
        if search_query is None:
            return

        response = await self.orchestrator.search(
            query=search_query,
            user_id=ctx.author.id,
            count=count
        )

        error_message = self._get_empty_response_message(response, search_query)
        if error_message:
            return await ctx.send(error_message)

        embeds = self._build_image_embeds(response, search_query, count)
        await ctx.send(embeds=embeds)


    async def _validate_character(self, ctx: commands.Context, name: str) -> str | None:
        """Validate character exists on AniList and is from an anime. Returns search query or None."""
        try:
            char = await fetch_character_by_name(name, session=self.bot.session, prefer="AniList")

            if not char:
                await ctx.send(f"❌ Could not find character **{name}** on AniList.")
                return None

            if not char_has_anime_media(char):
                full_name = char.get("name", {}).get("full", name)
                await ctx.send(f"❌ **{full_name}** is not associated with an Anime.")
                return None

            return char.get("name", {}).get("full", name)

        except Exception as e:
            logger.error(f"Validation error: {e}")
            return name


    def _get_empty_response_message(self, response, search_query: str) -> str | None:
        """Return error message if response has no images, or None if images exist."""
        if response.images:
            return None

        if response.exhausted:
            return (
                f"⚠️ **You have seen all available images for {search_query}!**\n"
                "I couldn't find any new ones right now. Try again later or search for a different character."
            )

        return f"❌ No images found for **{search_query}**."


    def _build_image_embeds(self, response, search_query: str, count: int) -> list:
        """Build embed objects for the image response."""
        embeds = []
        for i, img in enumerate(response.images[:count]):
            embed = discord.Embed(color=discord.Color.purple())

            if i == 0:
                embed.set_author(name=f"Anime PFP: {search_query}")

            embed.set_image(url=img.image_url)
            embed.set_footer(text=self._build_source_text(img, response.from_cache))
            embeds.append(embed)

        return embeds


    def _build_source_text(self, img, from_cache: bool) -> str:
        """Build the footer source text for an image embed."""
        cache_status = " • Cached (New for you)" if from_cache else " • Freshly Scraped"
        return f"Source: {img.source.capitalize()}{cache_status}"

    def _create_anime_embed(self, anime_data: dict) -> discord.Embed:
        """Helper to build a Discord Embed for anime metadata."""
        # Safe title extraction with fallbacks
        title_dict = anime_data.get("title", {})
        title = title_dict.get("english") or title_dict.get("romaji") or "Unknown Title"
        url = anime_data.get("siteUrl", "")
        
        description = anime_data.get("description") or "No description available."
        description = description.replace("<br>", "\n").replace("<i>", "").replace("</i>", "")
        if len(description) > 4096:
            description = description[:4093] + "..."

        embed = discord.Embed(title=title, url=url, description=description, color=discord.Color.blurple())
        
        if anime_data.get("coverImage", {}).get("medium"):
            embed.set_thumbnail(url=anime_data["coverImage"]["medium"])
        if anime_data.get("bannerImage"):
            embed.set_image(url=anime_data["bannerImage"])

        embed.add_field(name="Episodes", value=str(anime_data.get("episodes", "N/A")), inline=True)
        embed.add_field(name="Status", value=anime_data.get("status", "N/A").title(), inline=True)

        start = anime_data.get("startDate", {})
        end = anime_data.get("endDate", {})
        start_str = f"{start.get('year','N/A')}-{start.get('month','??')}-{start.get('day','??')}" if start.get("year") else "N/A"
        end_str = f"{end.get('year','N/A')}-{end.get('month','??')}-{end.get('day','??')}" if end.get("year") else "N/A"
        
        embed.add_field(name="Start Date", value=start_str, inline=True)
        embed.add_field(name="End Date", value=end_str, inline=True)
        embed.add_field(name="Duration", value=f"{anime_data.get('duration', 'N/A')} min/ep", inline=True)
        
        studios = anime_data.get("studios", {}).get("nodes", [])
        studio_name = studios[0]["name"] if studios else "N/A"
        embed.add_field(name="Studio", value=studio_name, inline=True)
        
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
        return embed

    @commands.hybrid_command(name="anime", description="Search for an anime by name")
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def anime(self, ctx: commands.Context, *, query: str):
        """Interactive search for anime metadata using AniList."""
        results = await search_anime(self.bot.session, query)

        if not results:
            return await ctx.send(f"❌ No results found for `{query}`.")

        options = [
            discord.SelectOption(
                label=(a.get("title", {}).get("english") or a.get("title", {}).get("romaji") or "Unknown")[:100],
                description=f"Episodes: {a.get('episodes', 'N/A')} | Season: {a.get('season', 'N/A')}"[:100],
                value=str(a["id"]),
            )
            for a in results
        ]

        async def select_callback(interaction: discord.Interaction):
            if interaction.user != ctx.author:
                await interaction.response.send_message("This is not your command!", ephemeral=True)
                return

            await interaction.response.defer()
            try:
                anime_id = int(interaction.data["values"][0])
                anime_data = next(a for a in results if a["id"] == anime_id)
                embed = self._create_anime_embed(anime_data)
                await interaction.edit_original_response(content=None, embed=embed, view=None)
            except Exception:
                await interaction.edit_original_response(content="❌ Failed to load anime data.", view=None)

        select = Select(placeholder="Choose an anime...", options=options)
        select.callback = select_callback
        view = View()
        view.add_item(select)
        await ctx.send("Select an anime from the search results:", view=view)

async def setup(bot):
    await bot.add_cog(Search(bot))