"""Discord views for selecting and previewing profile-card themes."""

from __future__ import annotations

import io
import discord

from bot.config.assets import AssetCatalog, asset_catalog
from bot.config.configs import ProgressionConstants as PC
from bot.config.emojis import MinoriEmojis
from bot.features.progression.domain.levels import get_title, required_exp
from bot.services.render_manager import RenderContext


def _require_repository(cog):
    repository = getattr(cog, "repo", None)
    if repository is None:
        raise RuntimeError("Progression repository is not initialized.")
    return repository


class MainThemeSelect(discord.ui.Select):
    def __init__(
        self,
        user_id: int,
        cog,
        catalog: AssetCatalog = asset_catalog,
    ) -> None:
        self.user_id = user_id
        self.cog = cog
        self.catalog = catalog
        self.themes = catalog.list_themes()
        options = [
            discord.SelectOption(
                label=theme.label,
                value=theme.id,
                description=f"Choose the {theme.label} theme",
            )
            for theme in self.themes[:25]
        ]
        if not options:
            options = [
                discord.SelectOption(
                    label="No themes available",
                    value="__none__",
                    description="No background folders were found.",
                )
            ]
        super().__init__(
            placeholder="Select a theme...",
            min_values=1,
            max_values=1,
            options=options,
            disabled=not self.themes,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "⚠️ You can only select a background for yourself.",
                ephemeral=True,
            )
            return
        selected_theme = self.values[0]
        self.disabled = True
        await interaction.response.edit_message(
            content=(
                f"You selected **{selected_theme.replace('_', ' ').title()}**. "
                "Now choose a background:"
            ),
            view=SubThemeView(
                self.user_id,
                selected_theme,
                self.cog,
                catalog=self.catalog,
            ),
        )


class MainThemeView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        cog,
        catalog: AssetCatalog = asset_catalog,
    ) -> None:
        super().__init__(timeout=120)
        self.add_item(MainThemeSelect(user_id, cog, catalog=catalog))


class SubThemeSelect(discord.ui.Select):
    def __init__(
        self,
        user_id: int,
        theme: str,
        cog,
        catalog: AssetCatalog = asset_catalog,
    ) -> None:
        self.user_id = user_id
        self.theme = theme
        self.cog = cog
        self.catalog = catalog
        self.backgrounds = catalog.list_backgrounds(theme)
        self.file_map = {
            background.id: background for background in self.backgrounds[:25]
        }
        options = [
            discord.SelectOption(
                label=background.label,
                value=background.id,
                description=f"Select {background.label}",
            )
            for background in self.backgrounds[:25]
        ]
        if not options:
            options = [
                discord.SelectOption(
                    label="No backgrounds available",
                    value="__none__",
                )
            ]
        super().__init__(
            placeholder="Select a background...",
            min_values=1,
            max_values=1,
            options=options,
            disabled=not self.backgrounds,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "⚠️ You can only select a background for yourself.",
                ephemeral=True,
            )
            return
        background = self.file_map.get(self.values[0])
        if background is None:
            await interaction.response.send_message(
                "❌ That background is no longer available.",
                ephemeral=True,
            )
            return

        repository = _require_repository(self.cog)
        font_color = "white"
        current_theme, current_file, current_color = await repository.get_user_theme(
            self.user_id
        )
        if (
            current_theme.casefold() == self.theme.casefold()
            and (current_file or "").casefold() == background.filename.casefold()
            and current_color == font_color
        ):
            await interaction.response.send_message(
                f"{MinoriEmojis['MinoriSmile']} "
                "You already use this profile background.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        await repository.set_user_theme(
            self.user_id,
            self.theme,
            background.filename,
            font_color,
        )
        for item in self.view.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True

        if interaction.guild is None:
            await interaction.followup.send(
                "❌ Profile themes can only be changed inside a server.",
                ephemeral=True,
            )
            return

        member = interaction.user
        exp, level = await repository.get_user(member.id, interaction.guild.id)
        next_exp = None if level >= PC.MAX_LEVEL else required_exp(level)
        avatar_bytes = await member.display_avatar.with_size(128).read()
        render_context = RenderContext(
            avatar_bytes=avatar_bytes,
            display_name=member.display_name,
            title_name=get_title(level),
            level=level,
            exp=exp,
            next_exp=next_exp,
            bg_file=background.filename,
            theme_name=self.theme,
            font_color=font_color,
        )
        image_bytes = await self.cog.render_manager.render_profile(render_context)
        embed = discord.Embed(
            title="Your profile card theme has been updated!",
            description=(
                "Your selection has been saved.\n"
                f"Theme: `{self.theme.replace('_', ' ').title()}`\n"
                f"Background: `{background.label}`"
            ),
        )
        await interaction.edit_original_response(
            content="",
            embed=embed,
            view=self.view,
        )
        if not image_bytes:
            await interaction.followup.send(
                "⚠️ The theme was saved, but the preview could not be rendered.",
                ephemeral=True,
            )
            return
        file = discord.File(io.BytesIO(image_bytes), filename=PC.PROFILE_PNG)
        await interaction.followup.send(
            content=(
                f"{member.mention}, here is your updated profile! "
                f"{MinoriEmojis['MinoriSmile']}"
            ),
            file=file,
        )


class SubThemeView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        theme: str,
        cog,
        catalog: AssetCatalog = asset_catalog,
    ) -> None:
        super().__init__(timeout=120)
        self.add_item(SubThemeSelect(user_id, theme, cog, catalog=catalog))
