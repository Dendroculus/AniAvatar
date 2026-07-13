"""Profile-card rendering orchestration."""

from __future__ import annotations

import io
import traceback
from typing import Optional

from PIL import Image

from bot.features.progression.rendering.layouts import (
    ProfileCardLayout,
)
from bot.features.progression.rendering.profile_canvas import (
    ProfileCanvasMixin,
)
from bot.features.progression.rendering.profile_components import (
    ProfileComponentsMixin,
)
from bot.features.progression.rendering.profile_text import (
    ProfileTextMixin,
)


class ProfileRendererMixin(
    ProfileTextMixin,
    ProfileCanvasMixin,
    ProfileComponentsMixin,
):
    """Coordinate profile-card resources and visual components."""

    def render_profile_image(
        self,
        avatar_bytes: bytes,
        display_name: str,
        title_name: str,
        level: int,
        exp: int,
        next_exp: int,
        fonts: dict,
        title_emoji_files: dict,
        bg_file: str = None,
        theme_name: str = "default",
        font_color: tuple = None,
        user_rank: int = None,
    ) -> Optional[bytes]:
        """Render a complete profile card as PNG bytes."""

        try:
            fonts_pack = self.fonts.prepare_profile_fonts(
                fonts
            )

            width = ProfileCardLayout.WIDTH
            height = ProfileCardLayout.HEIGHT

            img, draw = self._profile_setup_canvas(
                theme_name,
                bg_file,
                width,
                height,
                ProfileCardLayout.CORNER_RADIUS,
            )

            resolved_color = (
                self._profile_resolve_font_color(
                    font_color,
                    theme_name,
                    bg_file,
                )
            )

            left_margin = ProfileCardLayout.LEFT_MARGIN
            top_margin = ProfileCardLayout.TOP_MARGIN

            name_x = left_margin + 130
            name_y = top_margin

            self._profile_draw_avatar(
                img,
                avatar_bytes,
                left_margin,
                top_margin,
            )

            normalized_name = (
                self._profile_prepare_display_name(
                    display_name
                )
            )

            self._profile_draw_name_and_rank(
                draw,
                display_name=normalized_name,
                name_x=name_x,
                name_y=name_y,
                fonts_pack=fonts_pack,
                font_color=resolved_color,
                user_rank=user_rank,
            )

            y = name_y + 40

            y = self._profile_draw_labels_values(
                draw,
                img,
                name_x,
                y,
                title_name,
                level,
                exp,
                next_exp,
                fonts_pack["font_medium"],
                fonts_pack["cjk_font_medium"],
                resolved_color,
                title_emoji_files,
            )

            y = self._profile_draw_next_level_line(
                draw,
                x=name_x,
                y=y,
                exp=exp,
                next_exp=next_exp,
                fonts_pack=fonts_pack,
            )

            bar_width = (
                width
                - name_x
                - left_margin
            )

            self._profile_draw_progress_bar(
                img,
                draw,
                x=name_x,
                y=y,
                width=bar_width,
                height=(
                    ProfileCardLayout.PROGRESS_BAR_HEIGHT
                ),
                exp=exp,
                next_exp=next_exp,
            )

            final_image = img.resize(
                (360, 155),
                Image.Resampling.LANCZOS,
            )

            output = io.BytesIO()
            final_image.save(output, format="PNG")

            return output.getvalue()

        except Exception:
            traceback.print_exc()
            return None
