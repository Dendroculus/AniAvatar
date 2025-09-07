from discord.ext import commands
from discord import app_commands, Interaction

handled_errors = set()

class ErrorHandler(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        key = (ctx.guild.id if ctx.guild else 0, ctx.author.id, str(ctx.command))
        if key in handled_errors:
            return
        handled_errors.add(key)

        if isinstance(error, commands.HybridCommandError):
            return  # let slash error handle it

        if isinstance(error, commands.MissingPermissions):
            await ctx.send("🚫 You don't have permission to use this command.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing argument: `{error.param.name}`.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Invalid argument. Check your input.")
        elif isinstance(error, commands.CommandNotFound):
            if not ctx.message.content.startswith("/"):
                await ctx.send("❌ Unknown command. Use `!commands` to see available commands.")
        else:
            print(f"Unhandled error in '{ctx.command}': {error}")
            await ctx.send("❌ An unexpected error occurred.")

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: Interaction, error: app_commands.AppCommandError):
        key = (interaction.guild.id if interaction.guild else 0, interaction.user.id, str(interaction.command))
        if key in handled_errors:
            return
        handled_errors.add(key)

        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("🚫 You don't have permission to use this command.", ephemeral=True)
        elif isinstance(error, app_commands.CommandInvokeError):
            await interaction.response.send_message("❌ Something went wrong with this slash command.", ephemeral=True)
            print(error.original)
        elif isinstance(error, app_commands.TransformerError):
            await interaction.response.send_message("❌ Invalid argument. Check your input.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ An unexpected slash command error occurred.", ephemeral=True)
            print(error)

async def setup(bot):
    await bot.add_cog(ErrorHandler(bot))
    print("📦 Loaded error handler cog.")