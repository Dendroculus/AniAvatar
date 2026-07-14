"""Discord views for selecting and previewing profile-card themes."""

from __future__ import annotations

import io
import discord

from bot.config.assets import AssetCatalog, asset_catalog
from bot.config.configs import ProgressionConstants as PC
from bot.config.emojis import MinoriEmojis
from bot.features.progression.profile_workflow import ProfileWorkflow
from bot.core.repositories.user_repository import UserRepository


class MainThemeSelect(discord.ui.Select):
    """Select the main profile-card theme."""

    def __init__(
        self,
        user_id: int,
        repository: UserRepository,
        profile_workflow: ProfileWorkflow,
        catalog: AssetCatalog = asset_catalog,
    ) -> None:
        self.user_id = user_id
        self.repository = repository
        self.profile_workflow = profile_workflow
        self.catalog = catalog
        self.themes = catalog.list_themes()

        options = [
            discord.SelectOption(
                label=theme.label,
                value=theme.id,
                description=(f"Choose the {theme.label} theme"),
            )
            for theme in self.themes[:25]
        ]

        if not options:
            options = [
                discord.SelectOption(
                    label="No themes available",
                    value="__none__",
                    description=("No background folders were found."),
                )
            ]

        super().__init__(
            placeholder="Select a theme...",
            min_values=1,
            max_values=1,
            options=options,
            disabled=not self.themes,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Show backgrounds for the selected theme."""

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                ("⚠️ You can only select a background for yourself."),
                ephemeral=True,
            )
            return

        selected_theme = self.values[0]
        self.disabled = True

        await interaction.response.edit_message(
            content=(
                "You selected "
                f"**{selected_theme.replace('_', ' ').title()}**. "
                "Now choose a background:"
            ),
            view=SubThemeView(
                user_id=self.user_id,
                theme=selected_theme,
                repository=self.repository,
                profile_workflow=(self.profile_workflow),
                catalog=self.catalog,
            ),
        )


class MainThemeView(discord.ui.View):
    """Display the main profile-theme selector."""

    def __init__(
        self,
        user_id: int,
        repository: UserRepository,
        profile_workflow: ProfileWorkflow,
        catalog: AssetCatalog = asset_catalog,
    ) -> None:
        super().__init__(timeout=120)

        self.add_item(
            MainThemeSelect(
                user_id=user_id,
                repository=repository,
                profile_workflow=(profile_workflow),
                catalog=catalog,
            )
        )


class SubThemeSelect(discord.ui.Select):
    """Select a background inside a profile theme."""

    def __init__(
        self,
        user_id: int,
        theme: str,
        repository: UserRepository,
        profile_workflow: ProfileWorkflow,
        catalog: AssetCatalog = asset_catalog,
    ) -> None:
        self.user_id = user_id
        self.theme = theme
        self.repository = repository
        self.profile_workflow = profile_workflow
        self.catalog = catalog

        self.backgrounds = catalog.list_backgrounds(theme)

        self.file_map = {
            background.id: background for background in self.backgrounds[:25]
        }

        options = [
            discord.SelectOption(
                label=background.label,
                value=background.id,
                description=(f"Select {background.label}"),
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

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Persist the background and render its preview."""

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                ("⚠️ You can only select a background for yourself."),
                ephemeral=True,
            )
            return

        background = self.file_map.get(self.values[0])

        if background is None:
            await interaction.response.send_message(
                ("❌ That background is no longer available."),
                ephemeral=True,
            )
            return

        font_color = "white"

        (
            current_theme,
            current_file,
            current_color,
        ) = await self.repository.get_user_theme(self.user_id)

        if (
            current_theme.casefold() == self.theme.casefold()
            and (current_file or "").casefold() == background.filename.casefold()
            and current_color == font_color
        ):
            await interaction.response.send_message(
                (
                    f"{MinoriEmojis['MinoriSmile']} "
                    "You already use this "
                    "profile background."
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        await self.repository.set_user_theme(
            self.user_id,
            self.theme,
            background.filename,
            font_color,
        )

        for item in self.view.children:
            if isinstance(
                item,
                discord.ui.Select,
            ):
                item.disabled = True

        if interaction.guild is None:
            await interaction.followup.send(
                ("⚠️ Profile themes can only be changed inside a server."),
                ephemeral=True,
            )
            return

        result = await self.profile_workflow.render(
            interaction.user,
            interaction.guild.id,
        )

        embed = discord.Embed(
            title=("Your profile card theme has been updated!"),
            description=(
                "Your selection has been saved.\n"
                "Theme: "
                f"`{self.theme.replace('_', ' ').title()}`\n"
                "Background: "
                f"`{background.label}`"
            ),
        )

        await interaction.edit_original_response(
            content="",
            embed=embed,
            view=self.view,
        )

        if not result.image_bytes:
            await interaction.followup.send(
                ("⚠️ The theme was saved, but the preview could not be rendered."),
                ephemeral=True,
            )
            return

        file = discord.File(
            io.BytesIO(result.image_bytes),
            filename=PC.PROFILE_PNG,
        )

        await interaction.followup.send(
            content=(
                f"{interaction.user.mention}, "
                "here is your updated profile! "
                f"{MinoriEmojis['MinoriSmile']}"
            ),
            file=file,
        )


class SubThemeView(discord.ui.View):
    """Display backgrounds for one profile theme."""

    def __init__(
        self,
        user_id: int,
        theme: str,
        repository: UserRepository,
        profile_workflow: ProfileWorkflow,
        catalog: AssetCatalog = asset_catalog,
    ) -> None:
        super().__init__(timeout=120)

        self.add_item(
            SubThemeSelect(
                user_id=user_id,
                theme=theme,
                repository=repository,
                profile_workflow=(profile_workflow),
                catalog=catalog,
            )
        )
