from discord.ext import commands
from discord import app_commands, Interaction
import time
import traceback

handled_errors = {}

def is_handled(key, ttl=60):
    now = time.time()
    handled_errors.update({k: v for k, v in handled_errors.items() if now - v < ttl})
    if key in handled_errors and now - handled_errors[key] < ttl:
        return True
    handled_errors[key] = now
    return False

class ErrorHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        key = (ctx.guild.id if ctx.guild else 0, ctx.author.id, str(ctx.command))
        if is_handled(key):
            return

        if isinstance(error, commands.HybridCommandError):
            return  

        if isinstance(error, commands.MissingPermissions):
            await ctx.send("🚫 You don't have permission to use this command.")
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send("🚫 I don’t have the required permissions for that.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing argument: `{error.param.name}`.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Invalid argument. Check your input.")
        elif isinstance(error, commands.CommandNotFound):
            if not ctx.message.content.startswith("/"):
                pass
        else:
            await ctx.send("❌ An unexpected error occurred.")
            self.bot.logger.error(f"Unhandled error in '{ctx.command}': {error}", exc_info=error)

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: Interaction, error: app_commands.AppCommandError):
        key = (interaction.guild.id if interaction.guild else 0, interaction.user.id, str(interaction.command))
        if is_handled(key):
            return

        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "🚫 You don't have permission to use this command.", ephemeral=True
            )
        elif isinstance(error, app_commands.CommandInvokeError):
            await interaction.response.send_message(
                "❌ Something went wrong with this slash command.", ephemeral=True
            )
            self.bot.logger.error("Slash command error", exc_info=error.original)
        elif isinstance(error, app_commands.TransformerError):
            await interaction.response.send_message(
                "❌ Invalid argument. Check your input.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ An unexpected slash command error occurred.", ephemeral=True
            )
            self.bot.logger.error("Unhandled slash error", exc_info=error)
            
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        err = getattr(error, "original", error)

        if isinstance(err, commands.CommandOnCooldown):
            retry = err.retry_after
            msg = f"<:TIME:1415961777912545341> Please wait for {retry:.1f}s before using that command again."

            interaction = getattr(ctx, "interaction", None)
            if interaction is not None:
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(msg, ephemeral=True)
                    else:
                        await interaction.followup.send(msg, ephemeral=True)
                    return
                except Exception:
                    pass

            try:
                await ctx.send(msg)
            except Exception:
                pass
            return
        try:
            if hasattr(self.bot, "logger"):
                self.bot.logger.exception(f"Unhandled error in '{ctx.command}': {error}")
            else:
                print(f"Unhandled error in '{ctx.command}': {error}")
                traceback.print_exception(type(error), error, error.__traceback__)
        except Exception:
            pass

        try:
            msg = "❌ An unexpected error occurred while processing that command."
            interaction = getattr(ctx, "interaction", None)
            if interaction is not None:
                if not interaction.response.is_done():
                    await interaction.response.send_message(msg, ephemeral=True)
                else:
                    await interaction.followup.send(msg, ephemeral=True)
            else:
                await ctx.send(msg)
        except Exception:
            pass

async def setup(bot):
    await bot.add_cog(ErrorHandler(bot))
    print("📦 Loaded error handler cog.")
