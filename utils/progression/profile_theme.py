import discord
import os
import io
from constants.configs import ProgressionConstants as PC, BG_PATH
from constants.emojis import MinoriEmojis
from utils.progression.profile_cards import get_title

class MainThemeSelect(discord.ui.Select):
    """
    Select menu listing top-level theme folders for profile backgrounds.

    Responsibilities:
    - Present available theme folders (derived from BG_PATH) as Select options.
    - Validate that the invoking user owns the selection (protects other users' selections).
    - On selection, transition the interaction to a SubThemeView to pick a specific background.
    """
    def __init__(self, user_id, cog):
        self.user_id = user_id
        self.cog = cog
        self.folders = [folder for folder in os.listdir(BG_PATH) if os.path.isdir(os.path.join(BG_PATH, folder))]
        options = [
            discord.SelectOption(label=folder.capitalize(), description=f"Choose {folder.capitalize()} theme")
            for folder in self.folders
        ]
        super().__init__(placeholder="Select a theme...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("⚠️ You can only select a background for yourself.", ephemeral=True)
            return
        idx = self.values[0].lower()
        selected_theme = next(f for f in self.folders if f.lower() == idx)
        self.disabled = True
        for item in self.view.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True
        await interaction.response.edit_message(
            content=f"You have selected **{selected_theme.capitalize()}**! Now pick a background:",
            view=SubThemeView(self.user_id, selected_theme, self.cog)
        )


class MainThemeView(discord.ui.View):
    """
    Wrapper view that adds a MainThemeSelect for a specific user.

    This view is ephemeral per-invocation and used by the profiletheme command.
    """
    def __init__(self, user_id, cog):
        super().__init__()
        self.cog = cog
        self.add_item(MainThemeSelect(user_id, cog))


class SubThemeSelect(discord.ui.Select):
    """
    Select menu showing concrete background image files within a chosen theme folder.

    Behavior:
    - Maps "Theme N" labels to actual filenames and persists the user's theme choice
      via Progression.set_user_theme.
    - Verifies ownership (only the invoking user may confirm a background).
    - After saving, renders and sends an updated profile image preview to the user.
    """
    def __init__(self, user_id, theme, cog):
        self.theme = theme
        self.cog = cog
        theme_path = os.path.join(BG_PATH, theme)

        files = [f for f in os.listdir(theme_path) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
        self.file_map = {f"Theme {i+1}": file for i, file in enumerate(files)}

        options = [
            discord.SelectOption(label=name, description=f"Select {name}")
            for name in self.file_map.keys()
        ]

        super().__init__(placeholder="Select a background...", min_values=1, max_values=1, options=options)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "⚠️ You can only select a background for yourself.", ephemeral=True
            )
            return

        selected_label = self.values[0]
        bg_file = self.file_map[selected_label]
        theme_name = self.theme
        font_color = "white"

        current_theme_name, current_bg_file, current_font_color = await self.cog.get_user_theme(self.user_id)
        if (
            current_theme_name == theme_name
            and (current_bg_file or "").lower() == bg_file.lower()
            and current_font_color == font_color
        ):
            await interaction.response.send_message(
                f"{MinoriEmojis['MinoriSmile']} You already use this profile theme and background.", ephemeral=True
            )
            return

        await self.cog.set_user_theme(self.user_id, theme_name, bg_file, font_color)

        for item in self.view.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True

        embed = discord.Embed(
            title="Your profile card theme has been updated!",
            description=f"Your selection has been saved!\n You have selected `{theme_name.capitalize()} {selected_label}`."
        )
        embed.set_image(url=PC.ATTACHMENT_PROFILE)
        try:
            await interaction.response.edit_message(embed=embed, view=self.view)
        except discord.errors.InteractionResponded:
            await interaction.followup.send(embed=embed)
        await interaction.message.edit(content="")

        member = interaction.user
        exp, level = await self.cog.get_user(member.id, interaction.guild.id)
        title_name = get_title(level)
        next_exp = None if level >= PC.MAX_LEVEL else 50 * level + 20 * level**2

        avatar_bytes = await member.display_avatar.with_size(128).read()

        img_bytes = await self.cog._render_profile_cached(
            avatar_bytes,
            member.display_name,
            title_name,
            level,
            exp,
            next_exp,
            bg_file=bg_file,
            theme_name=theme_name,
            font_color=font_color
        )

        if img_bytes:
            file = discord.File(io.BytesIO(img_bytes), filename=PC.PROFILE_PNG)
            await interaction.followup.send(
                content=f"{member.mention}, here's your updated profile! {MinoriEmojis['MinoriSmile']}",
                file=file
            )


class SubThemeView(discord.ui.View):
    """
    Simple wrapper view that holds a SubThemeSelect for the chosen theme.
    """
    def __init__(self, user_id, theme, cog):
        super().__init__()
        self.cog = cog
        self.add_item(SubThemeSelect(user_id, theme, cog))