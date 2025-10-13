from discord.ext import commands
from discord import app_commands, Interaction
import discord
import aiohttp
import traceback

class ErrorHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _respond_ctx(self, ctx, message: str, ephemeral: bool = True):
        interaction = getattr(ctx, "interaction", None)
        try:
            if interaction is not None:
                if not interaction.response.is_done():
                    await interaction.response.send_message(message, ephemeral=ephemeral)
                else:
                    await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                await ctx.send(message)
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _respond_interaction(self, interaction: Interaction, message: str, ephemeral: bool = True):
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(message, ephemeral=ephemeral)
            else:
                await interaction.followup.send(message, ephemeral=ephemeral)
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        err = getattr(error, "original", error)

        if isinstance(error, commands.HybridCommandError):
            return

        if isinstance(err, commands.CommandOnCooldown):
            retry = err.retry_after
            msg = f"<:TIME:1415961777912545341> Please wait for {retry:.1f}s before using that command again."
            await self._respond_ctx(ctx, msg, ephemeral=True)
            return

        if isinstance(err, (aiohttp.ClientOSError, aiohttp.ServerDisconnectedError, aiohttp.ClientPayloadError)):
            await self._respond_ctx(ctx, "⚠️ Network hiccup — couldn’t complete your request. Try again in a moment.", ephemeral=True)
            if hasattr(self.bot, "logger"):
                self.bot.logger.warning(f"Network-related error in '{ctx.command}': {err}")
            else:
                print(f"Network-related error in '{ctx.command}': {err}")
            return

        if isinstance(err, commands.MissingPermissions):
            await self._respond_ctx(ctx, "🚫 You don't have permission to use this command.", ephemeral=True)
            return

        if isinstance(err, commands.BotMissingPermissions):
            await self._respond_ctx(ctx, "🚫 I don’t have the required permissions for that.", ephemeral=True)
            return

        if isinstance(err, commands.MissingRequiredArgument):
            await self._respond_ctx(ctx, f"❌ Missing argument: `{err.param.name}`.", ephemeral=True)
            return

        if isinstance(err, commands.BadArgument):
            await self._respond_ctx(ctx, "❌ Invalid argument. Check your input.", ephemeral=True)
            return

        if isinstance(err, commands.CommandNotFound):
            return

        if hasattr(self.bot, "logger"):
            self.bot.logger.exception(f"Unhandled error in '{ctx.command}': {error}")
        else:
            print(f"Unhandled error in '{ctx.command}': {error}")
            traceback.print_exception(type(error), error, error.__traceback__)

        await self._respond_ctx(ctx, "❌ An unexpected error occurred while processing that command.", ephemeral=True)

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await self._respond_interaction(interaction, "🚫 You don't have permission to use this command.", ephemeral=True)
            return

        if isinstance(error, app_commands.CommandInvokeError):
            await self._respond_interaction(interaction, "❌ Something went wrong with this slash command.", ephemeral=True)
            if hasattr(self.bot, "logger"):
                self.bot.logger.error("Slash command error", exc_info=getattr(error, "original", error))
            else:
                orig = getattr(error, "original", error)
                traceback.print_exception(type(orig), orig, orig.__traceback__)
            return

        if isinstance(error, app_commands.TransformerError):
            await self._respond_interaction(interaction, "❌ Invalid argument. Check your input.", ephemeral=True)
            return

        await self._respond_interaction(interaction, "❌ An unexpected slash command error occurred.", ephemeral=True)
        if hasattr(self.bot, "logger"):
            self.bot.logger.error("Unhandled slash error", exc_info=error)
        else:
            traceback.print_exception(type(error), error, error.__traceback__)

async def setup(bot):
    await bot.add_cog(ErrorHandler(bot))
