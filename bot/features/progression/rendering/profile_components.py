"""Reusable visual components for profile cards."""

from __future__ import annotations

from PIL import Image, ImageDraw

from bot.features.progression.rendering.layouts import (
    ProfileCardLayout,
)
from bot.features.progression.rendering.text import (
    strip_emojis,
)


class ProfileComponentsMixin:
    def _profile_draw_avatar(self, img, avatar_bytes, left_margin, top_margin):
        avatar = self.assets.get_avatar(avatar_bytes, ProfileCardLayout.AVATAR_SIZE)
        if not avatar:
            return

        mask = Image.new("L", avatar.size, 0)
        ImageDraw.Draw(mask).ellipse([0, 0, avatar.size[0], avatar.size[1]], fill=255)
        avatar_circle = Image.new("RGBA", avatar.size, (0, 0, 0, 0))
        avatar_circle.paste(avatar, (0, 0), mask)

        glow_size = (
            avatar.size[0] + ProfileCardLayout.AVATAR_GLOW_EXTRA,
            avatar.size[1] + ProfileCardLayout.AVATAR_GLOW_EXTRA,
        )
        glow = Image.new("RGBA", glow_size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse(
            [0, 0, glow_size[0], glow_size[1]], fill=(255, 255, 255, 80)
        )

        avatar_offset = ProfileCardLayout.AVATAR_OFFSET_X
        img.paste(glow, (left_margin + avatar_offset, top_margin + 5), glow)
        img.paste(
            avatar_circle,
            (left_margin + 6 + avatar_offset, top_margin + 11),
            avatar_circle,
        )

    def _profile_draw_labels_values(
        self,
        draw,
        img,
        x,
        y,
        title_name,
        level,
        exp,
        next_exp,
        font_medium,
        cjk_font_medium,
        font_color,
        title_emoji_files,
    ):
        labels = ["Title ", "Level ", "EXP "]
        values = [
            title_name,
            str(level),
            f"{exp:,} / {next_exp:,}" if next_exp else "∞",
        ]
        label_width = max(draw.textlength(lbl, font=font_medium) for lbl in labels)
        for label, value in zip(labels, values):
            self._draw_cjk_profile(
                draw, (x, y), label, font_medium, cjk_font_medium, font_color
            )
            colon_x = x + label_width + 8
            self._draw_cjk_profile(
                draw, (colon_x, y), ":", font_medium, cjk_font_medium, font_color
            )
            value_x = colon_x + 12
            self._draw_cjk_profile(
                draw, (value_x, y), value, font_medium, cjk_font_medium, font_color
            )
            if label.strip() == "Title":
                emoji_path = title_emoji_files.get(title_name)
                badge = self.assets.get_icon(
                    emoji_path, ProfileCardLayout.TITLE_BADGE_W
                )
                if badge:
                    # Resize is handled by asset loader to width, we need specific dim if strictly required,
                    # but asset loader maintains aspect square generally or we can resize here.
                    # Original code forced W/H. AssetLoader takes size as square dim.
                    # Let's trust AssetLoader for now or resize if needed.
                    if badge.size != (
                        ProfileCardLayout.TITLE_BADGE_W,
                        ProfileCardLayout.TITLE_BADGE_H,
                    ):
                        badge = badge.resize(
                            (
                                ProfileCardLayout.TITLE_BADGE_W,
                                ProfileCardLayout.TITLE_BADGE_H,
                            )
                        )

                    bx = int(value_x + draw.textlength(value, font=font_medium) + 10)
                    bbox = font_medium.getbbox(value)
                    text_height = bbox[3] - bbox[1]
                    by = int(y + text_height / 2 - badge.height / 2 + 8)
                    img.paste(badge, (bx, by), badge)
            y += 32
        return y

    @staticmethod
    def _profile_prepare_display_name(
        display_name: str,
    ) -> str:
        """Normalize and truncate a profile display name."""

        normalized = strip_emojis(display_name) or display_name

        if len(normalized) > ProfileCardLayout.USERNAME_TRUNCATE:
            normalized = (
                normalized[: ProfileCardLayout.USERNAME_TRUNCATE]
                + "..."
            )

        return normalized

    def _profile_draw_name_and_rank(
        self,
        draw,
        *,
        display_name: str,
        name_x: int,
        name_y: int,
        fonts_pack: dict,
        font_color,
        user_rank: int | None,
    ) -> None:
        """Draw the user's display name and optional rank."""

        self._draw_cjk_profile(
            draw,
            (name_x, name_y),
            display_name,
            fonts_pack["font_username"],
            fonts_pack["cjk_font_username"],
            font_color,
            small=True,
        )

        if user_rank is None:
            return

        rank_text = f"  #{user_rank}"

        name_width = self._meas_mwidth(
            draw,
            display_name,
            fonts_pack["font_username"],
            fonts_pack["cjk_font_username"],
        )

        rank_x = name_x + name_width

        draw.text(
            (rank_x + 1, name_y),
            rank_text,
            font=fonts_pack["font_username"],
            fill=(0, 0, 0, 100),
        )

        draw.text(
            (rank_x, name_y),
            rank_text,
            font=fonts_pack["font_username"],
            fill=font_color,
        )

    def _profile_draw_next_level_line(
        self,
        draw,
        *,
        x: int,
        y: int,
        exp: int,
        next_exp: int | None,
        fonts_pack: dict,
    ) -> int:
        """Draw the EXP remaining or maximum-level message."""

        if next_exp is not None:
            text = (
                f"Gain {max(0, next_exp - exp):,} "
                "more EXP to level up!"
            )
        else:
            text = "You are at max level!"

        self._draw_cjk_profile(
            draw,
            (x, y),
            text,
            fonts_pack["font_small"],
            fonts_pack["cjk_font_small"],
            (255, 255, 255),
            stroke_width=2.6,
            stroke_fill=(0, 0, 0, 255),
        )

        return y + 40

    @staticmethod
    def _profile_draw_progress_bar(
        img,
        draw,
        *,
        x: int,
        y: int,
        width: int,
        height: int,
        exp: int,
        next_exp: int | None,
    ) -> None:
        """Draw the segmented profile EXP progress bar."""

        progress = (
            exp / next_exp
            if next_exp is not None
            else 1
        )

        draw.rounded_rectangle(
            [x, y, x + width, y + height],
            radius=12,
            fill=(30, 30, 30),
        )

        if progress <= 0:
            return

        progress_width = int(width * progress)

        gradient = Image.new(
            "RGBA",
            (progress_width, height),
            (0, 0, 0, 0),
        )

        gradient_draw = ImageDraw.Draw(gradient)

        for index in range(progress_width):
            ratio = index / max(1, progress_width)

            red = int(80 * ratio)
            green = int(180 + 75 * ratio)
            blue = int(120 - 60 * ratio)

            gradient_draw.line(
                [(index, 0), (index, height)],
                fill=(red, green, blue, 255),
            )

        mask = Image.new(
            "L",
            (progress_width, height),
            0,
        )

        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, progress_width, height],
            radius=12,
            fill=255,
        )

        img.paste(
            gradient,
            (x, y),
            mask,
        )

        segment_width = width // 10

        for index in range(1, 10):
            line_x = x + index * segment_width

            if line_x >= x + progress_width:
                continue

            draw.line(
                [
                    (line_x, y + 2),
                    (line_x, y + height - 2),
                ],
                fill=(255, 255, 255, 100),
                width=1,
            )
