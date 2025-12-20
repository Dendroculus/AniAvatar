from discord.ext import commands
from discord import app_commands, Interaction
import discord
import aiohttp
import traceback

from utils.emojis import CustomEmojis

"""
Errors module - centralized command and slash-command error handling.

Design goals and behavior:
- Provide consistent, user-friendly messages for common failures (cooldowns, permission
  issues, invalid arguments) while avoiding leaking internal state or stack traces to users.
- Differentiate between "context" (prefix/legacy commands) and "interaction" (slash commands)
  when replying so that responses integrate with both invocation styles cleanly.
- Favor ephemeral replies for user-visible error messages when possible to avoid cluttering
  channels with diagnostic text.
- Surface network-related issues and report them to bot-level logger if available to aid
  in debugging transient external failures without failing silently.
- Keep exception handling narrow and explicit for predictable UX; fallback to logging and a
  generic user-facing message for unexpected errors.

Notes for maintainers:
- _respond_ctx/_respond_interaction implement the minimal logic required to handle whether an
  interaction response has already been sent (response.is_done()). This prevents errors when
  trying to send multiple responses for the same interaction.
- When extending this handler, prefer adding specific exception branches above the generic
  logging block so that the user gets the most helpful message possible.
"""

class ErrorHandler(commands.Cog):
    """
    Cog responsible for global command error handling.

    Responsibilities:
    - Normalize responses for both Context-based commands and Interaction-based commands.
    - Map common exception types to clear, actionable messages.
    - Log unexpected errors to the bot's logger if present, otherwise print stack traces.
    """

    def __init__(self, bot):
        self.bot = bot

    async def _respond_ctx(self, ctx, message: str, ephemeral: bool = True):
        # Respond to a Context invocation; prefer the underlying interaction when present.
        interaction = getattr(ctx, "interaction", None)
        try:
            if interaction is not None:
                # If the interaction hasn't been replied to, use response.send_message
                # else use followup so we don't cause "already responded" errors.
                if not interaction.response.is_done():
                    await interaction.response.send_message(message, ephemeral=ephemeral)
                else:
                    await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                # Fallback for legacy prefix commands: plain ctx.send
                await ctx.send(message)
        except (discord.Forbidden, discord.HTTPException):
            # Suppress delivery failures: we cannot reliably inform the user, and attempting
            # to do so often raises the same error (e.g., missing channel send perms).
            pass

    async def _respond_interaction(self, interaction: Interaction, message: str, ephemeral: bool = True):
        """
        Respond to a pure Interaction (slash command) error.

        Behavior:
        - Use response.send_message for the initial reply and followup for subsequent replies.
        - Suppress Forbidden/HTTPException for the same reasons as _respond_ctx.
        """
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(message, ephemeral=ephemeral)
            else:
                await interaction.followup.send(message, ephemeral=ephemeral)
        except (discord.Forbidden, discord.HTTPException):
            # Silently ignore inability to deliver error messages.
            pass

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """
        Handle errors raised by prefix/hybrid commands.

        Order of checks is deliberate:
        1. Unwrap original exception if command was invoked through `commands` wrappers.
        2. Ignore HybridCommandError because hybrid-specific handling may occur elsewhere.
        3. Provide formatted feedback for common, user-actionable errors (cooldowns, permissions,
           missing args, bad args).
        4. Handle network-related aiohttp errors specially to encourage retrying later.
        5. For unknown errors, log full traceback and send a generic user-facing message.

        Logging expectations:
        - If `bot.logger` exists, use it with appropriate severity (warning/exception).
        - Otherwise fall back to printing the traceback which is useful during development.
        """
        err = getattr(error, "original", error)

        # HybridCommandError is a wrapper for application errors; skip here to avoid duplicates.
        if isinstance(error, commands.HybridCommandError):
            return

        if isinstance(err, commands.CommandOnCooldown):
            # Provide a precise retry delay with one decimal place to help users time retries.
            retry = err.retry_after
            msg = f"{CustomEmojis['TIME']} Please wait for {retry:.1f}s before using that command again."
            await self._respond_ctx(ctx, msg, ephemeral=True)
            return

        if isinstance(err, (aiohttp.ClientOSError, aiohttp.ServerDisconnectedError, aiohttp.ClientPayloadError)):
            # These errors often indicate upstream network instability; surface a retry suggestion.
            await self._respond_ctx(ctx, "⚠️ Network hiccup — couldn’t complete your request. Try again in a moment.", ephemeral=True)
            if hasattr(self.bot, "logger"):
                # Use warning level because the failure is external and often transient.
                self.bot.logger.warning(f"Network-related error in '{ctx.command}': {err}")
            else:
                print(f"Network-related error in '{ctx.command}': {err}")
            return

        if isinstance(err, commands.MissingPermissions):
            # Inform the invoking user they lack the required guild-level permissions.
            await self._respond_ctx(ctx, "🚫 You don't have permission to use this command.", ephemeral=True)
            return

        if isinstance(err, commands.BotMissingPermissions):
            # Inform the user that the bot lacks permissions required to complete the action.
            await self._respond_ctx(ctx, "🚫 I don’t have the required permissions for that.", ephemeral=True)
            return

        if isinstance(err, commands.MissingRequiredArgument):
            # Show which argument is missing to help the user correct their invocation.
            await self._respond_ctx(ctx, f"❌ Missing argument: `{err.param.name}`.", ephemeral=True)
            return

        if isinstance(err, commands.BadArgument):
            # Generic invalid argument response; converters or explicit parsing failed.
            await self._respond_ctx(ctx, "❌ Invalid argument. Check your input.", ephemeral=True)
            return

        if isinstance(err, commands.CommandNotFound):
            # Silently ignore command-not-found to emulate Discord's default behavior for unknown commands.
            return

        # Unhandled exceptions: log full traceback and inform the user generically.
        if hasattr(self.bot, "logger"):
            self.bot.logger.exception(f"Unhandled error in '{ctx.command}': {error}")
        else:
            print(f"Unhandled error in '{ctx.command}': {error}")
            traceback.print_exception(type(error), error, error.__traceback__)

        await self._respond_ctx(ctx, "❌ An unexpected error occurred while processing that command.", ephemeral=True)

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: Interaction, error: app_commands.AppCommandError):
        """
        Handle errors raised by application slash commands.

        This handler maps specific app command errors to user-friendly messages:
        - MissingPermissions: user lacks permissions to invoke the command.
        - CommandInvokeError: the command raised an exception during execution; log the original.
        - TransformerError: user provided an argument that failed app command type conversion.

        For any other error types, a generic message is sent and the error is logged for debugging.
        """
        if isinstance(error, app_commands.MissingPermissions):
            await self._respond_interaction(interaction, "🚫 You don't have permission to use this command.", ephemeral=True)
            return

        if isinstance(error, app_commands.CommandInvokeError):
            # Surface a simple failure message to the user but log the detailed exception.
            await self._respond_interaction(interaction, "❌ Something went wrong with this slash command.", ephemeral=True)
            if hasattr(self.bot, "logger"):
                # Log the original exception to preserve stack and context for debugging.
                self.bot.logger.error("Slash command error", exc_info=getattr(error, "original", error))
            else:
                orig = getattr(error, "original", error)
                traceback.print_exception(type(orig), orig, orig.__traceback__)
            return

        if isinstance(error, app_commands.TransformerError):
            # The app command's automatic argument parsing failed (e.g., invalid integer).
            await self._respond_interaction(interaction, "❌ Invalid argument. Check your input.", ephemeral=True)
            return

        # Fallback for any other unhandled app command errors.
        await self._respond_interaction(interaction, "❌ An unexpected slash command error occurred.", ephemeral=True)
        if hasattr(self.bot, "logger"):
            self.bot.logger.error("Unhandled slash error", exc_info=error)
        else:
            traceback.print_exception(type(error), error, error.__traceback__)

async def setup(bot):
    await bot.add_cog(ErrorHandler(bot))