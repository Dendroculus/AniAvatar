import discord
from discord.ext import commands
from discord.ui import View, Button
from .config import settings
from .database.connection import DatabasePool
from .database.queries import INSERT_SEARCH_HISTORY
from .services.cache_service import CacheService
from .services.orchestrator import SearchOrchestrator
from .workers.pinterest import PinterestWorker
from .utils.rate_limiter import TokenBucketRateLimiter
from .utils.http_validator import HTTPValidator

class PaginationView(View):
    def __init__(self, images, query, from_cache):
        super().__init__(timeout=180)
        self.images = images
        self.query = query
        self.from_cache = from_cache
        self.index = 0
        self.update_buttons()

    def update_buttons(self):
        self.prev.disabled = self.index == 0
        self.next.disabled = self.index == len(self.images) - 1

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: Button):
        self.index -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: Button):
        self.index += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def build_embed(self):
        img = self.images[self.index]
        embed = discord.Embed(title=f"Anime PFP: {self.query}", color=0xffc0cb)
        embed.set_image(url=img.image_url)
        embed.set_footer(text=f"Image {self.index + 1}/{len(self.images)} • {'Cached' if self.from_cache else 'Fresh'}")
        return embed

class AnimePFP(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = None
        self.orchestrator = None
        self.worker = None

    async def cog_load(self):
        print("Initializing AnimePFP Engine...")
        
        self.db = await DatabasePool.get_instance(
            settings.database_url, 
            settings.min_pool_size, 
            settings.max_pool_size
        )
        
        cache = CacheService(self.db)
        validator = HTTPValidator()
        limiter = TokenBucketRateLimiter(rate=2.0, burst=5)
        
        self.worker = PinterestWorker(limiter)
        await self.worker.initialize()
        
        self.orchestrator = SearchOrchestrator(cache, self.worker, validator)
        print("AnimePFP Engine Ready.")

    async def cog_unload(self):
        if self.worker:
            await self.worker.close()
        if self.db:
            await self.db.close()

    @commands.command(name="animepfp")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def animepfp(self, ctx, *, query: str):
        """Search for anime profile pictures."""
        async with ctx.typing():
            await self.db.execute(INSERT_SEARCH_HISTORY, ctx.author.id, query)
            
            res = await self.orchestrator.search(query)
            
        if not res.images:
            return await ctx.send(f"No images found for **{query}**.")
            
        view = PaginationView(res.images, query, res.from_cache)
        await ctx.send(embed=view.build_embed(), view=view)

async def setup(bot):
    await bot.add_cog(AnimePFP(bot))