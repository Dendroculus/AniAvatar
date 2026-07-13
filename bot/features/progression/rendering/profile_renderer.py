"""Profile-card rendering implementation."""

from __future__ import annotations

import io
import os
import traceback
from typing import Optional

from PIL import Image, ImageDraw

from bot.config.assets import resolve_background_path
from bot.features.progression.rendering.layouts import (
    ProfileCardLayout,
)
from bot.features.progression.rendering.text import (
    split_into_runs,
    strip_emojis,
)


class ProfileRendererMixin:
    @staticmethod
    def _draw_run_styled(
        draw, x, y, text, font, fill, small, is_cjk_mode, stroke_width, stroke_fill
    ) -> None:
        """
        Helper to handle the specific drawing style commands.

        Args:
            draw (ImageDraw.Draw): The drawing context.
            x (int): The x-coordinate.
            y (int): The y-coordinate.
            text (str): The text to draw.
            font (ImageFont.FreeTypeFont): The font to use.
            fill (tuple): The fill color.
            small (bool): Whether to use small text style.
            is_cjk_mode (bool): Whether the current run is CJK.
            stroke_width (int): Stroke width for non-small text.
            stroke_fill (tuple): Stroke fill color for non-small text.

        Returns:
            None
        """
        if small:
            draw.text((x + 1, y), text, font=font, fill=(0, 0, 0, 100))
            if is_cjk_mode:
                draw.text(
                    (x, y),
                    text,
                    font=font,
                    fill=fill,
                    stroke_width=int(round(1.1)),
                    stroke_fill=(255, 255, 255, 255),
                )
            else:
                draw.text((x, y), text, font=font, fill=fill)
        else:
            draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 180))
            draw.text(
                (x, y),
                text,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )

    @staticmethod
    def _draw_cjk_profile(
        draw,
        pos,
        text,
        primary_font,
        cjk_font,
        fill,
        small=False,
        stroke_width=2,
        stroke_fill=(0, 0, 0, 255),
    ) -> None:
        """
        Handle mixed CJK and non-CJK text drawing for profile cards.

        Args:
            draw (ImageDraw.Draw): The drawing context.
            pos (tuple): The (x, y) position to start drawing.
            text (str): The text to draw.
            primary_font (ImageFont.FreeTypeFont): The primary font for non-CJK text.
            cjk_font (ImageFont.FreeTypeFont): The CJK font for CJK text.
            fill (tuple): The fill color.
            small (bool): Whether to use small text style.
            stroke_width (int): Stroke width for non-small text.
            stroke_fill (tuple): Stroke fill color for non-small text.

        Returns:
            None
        """
        x0, y0 = pos
        runs = split_into_runs(text)

        for run_text, is_cjk in runs:
            is_cjk_mode = bool(is_cjk and cjk_font)
            font_to_use = cjk_font if is_cjk_mode else primary_font
            y_offset = -3 if is_cjk else 0

            ProfileRendererMixin._draw_run_styled(
                draw,
                x0,
                y0 + y_offset,
                run_text,
                font_to_use,
                fill,
                small,
                is_cjk_mode,
                stroke_width,
                stroke_fill,
            )

            try:
                w = draw.textlength(run_text, font=font_to_use)
            except Exception:
                w, _ = font_to_use.getsize(run_text)
            x0 += int(w)

    @staticmethod
    def _meas_mwidth(draw, text, primary_font, cjk_font):
        w = 0
        for run_text, is_cjk in split_into_runs(text):
            font_to_use = cjk_font if (is_cjk and cjk_font) else primary_font
            try:
                w += draw.textlength(run_text, font=font_to_use)
            except Exception:
                w += font_to_use.getsize(run_text)[0]
        return int(w)

    def _profile_get_adaptive_font_color(self, bg_path):
        try:
            bg = Image.open(bg_path).convert("RGB")
            small = bg.resize((10, 10))
            pixels = list(small.getdata())
            avg_r = sum(p[0] for p in pixels) / len(pixels)
            avg_g = sum(p[1] for p in pixels) / len(pixels)
            avg_b = sum(p[2] for p in pixels) / len(pixels)

            def lum(c):
                c = c / 255
                return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

            luminance_bg = (
                0.2126 * lum(avg_r) + 0.7152 * lum(avg_g) + 0.0722 * lum(avg_b)
            )
            contrast_white = (max(luminance_bg, 1) + 0.05) / (
                min(luminance_bg, 1) + 0.05
            )
            contrast_black = (max(luminance_bg, 0) + 0.05) / (
                min(luminance_bg, 0) + 0.05
            )

            return (255, 255, 255) if contrast_white >= contrast_black else (0, 0, 0)
        except (OSError, ValueError):
            return (255, 255, 255)

    @staticmethod
    def _profile_generate_default_bg(width, height):
        bg = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        grad = ImageDraw.Draw(bg)
        for y in range(height):
            r = int(120 + (180 - 120) * (y / height))
            g = int(60 + (100 - 60) * (y / height))
            b = int(160 + (220 - 160) * (y / height))
            grad.line([(0, y), (width, y)], fill=(r, g, b, 255))

        shape = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        shape_draw = ImageDraw.Draw(shape)
        shape_draw.polygon(
            [(width, 0), (width, 80), (width - 120, 0)], fill=(255, 255, 255, 40)
        )
        bg = Image.alpha_composite(bg, shape)

        shape2 = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        shape2_draw = ImageDraw.Draw(shape2)
        shape2_draw.polygon(
            [(0, height), (0, height - 80), (120, height)], fill=(0, 0, 0, 60)
        )
        bg = Image.alpha_composite(bg, shape2)
        return bg

    def _profile_setup_canvas(self, theme_name, bg_file, width, height, corner_radius):
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, width, height], radius=corner_radius, fill=255
        )

        if theme_name == "default" or not bg_file:
            bg = self._profile_generate_default_bg(width, height)
        else:
            bg_path = resolve_background_path(theme_name, bg_file)
            if os.path.exists(bg_path):
                try:
                    bg = Image.open(bg_path).convert("RGBA").resize((width, height))
                except OSError:
                    bg = self._profile_generate_default_bg(width, height)
            else:
                bg = self._profile_generate_default_bg(width, height)

        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 60))
        bg = Image.alpha_composite(bg, overlay)
        img.paste(bg, (0, 0), mask)
        draw = ImageDraw.Draw(img)
        return img, draw

    def _profile_resolve_font_color(self, font_color, theme_name, bg_file):
        if font_color is None and theme_name != "default" and bg_file:
            bg_path = resolve_background_path(theme_name, bg_file)
            return self._profile_get_adaptive_font_color(bg_path)
        elif font_color is None:
            return (255, 255, 255)
        return font_color

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
        try:
            fonts_pack = self.fonts.prepare_profile_fonts(fonts)
            width, height = ProfileCardLayout.WIDTH, ProfileCardLayout.HEIGHT
            corner_radius = ProfileCardLayout.CORNER_RADIUS
            img, draw = self._profile_setup_canvas(
                theme_name, bg_file, width, height, corner_radius
            )
            font_color_resolved = self._profile_resolve_font_color(
                font_color, theme_name, bg_file
            )

            # Layout logic inline
            left_margin = ProfileCardLayout.LEFT_MARGIN
            top_margin = ProfileCardLayout.TOP_MARGIN
            name_x = left_margin + 130
            name_y = top_margin

            self._profile_draw_avatar(img, avatar_bytes, left_margin, top_margin)

            display_name_only = strip_emojis(display_name) or display_name
            if len(display_name_only) > ProfileCardLayout.USERNAME_TRUNCATE:
                display_name_only = (
                    display_name_only[: ProfileCardLayout.USERNAME_TRUNCATE] + "..."
                )

            # Draw name and rank
            self._draw_cjk_profile(
                draw,
                (name_x, name_y),
                display_name_only,
                fonts_pack["font_username"],
                fonts_pack["cjk_font_username"],
                font_color_resolved,
                small=True,
            )
            if user_rank is not None:
                rank_text = f"  #{user_rank}"
                name_w = self._meas_mwidth(
                    draw,
                    display_name_only,
                    fonts_pack["font_username"],
                    fonts_pack["cjk_font_username"],
                )
                rank_x = name_x + name_w
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
                    fill=font_color_resolved,
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
                font_color_resolved,
                title_emoji_files,
            )

            # Next line
            if next_exp is not None:
                next_line = f"Gain {max(0, next_exp - exp):,} more EXP to level up!"
            else:
                next_line = "You are at max level!"
            self._draw_cjk_profile(
                draw,
                (name_x, y),
                next_line,
                fonts_pack["font_small"],
                fonts_pack["cjk_font_small"],
                (255, 255, 255),
                stroke_width=2.6,
                stroke_fill=(0, 0, 0, 255),
            )
            y += 40

            # Progress Bar
            bar_x, bar_y = name_x, y
            bar_width, bar_height = (
                width - bar_x - left_margin,
                ProfileCardLayout.PROGRESS_BAR_HEIGHT,
            )
            progress = (exp / next_exp) if next_exp is not None else 1
            draw.rounded_rectangle(
                [bar_x, bar_y, bar_x + bar_width, bar_y + bar_height],
                radius=12,
                fill=(30, 30, 30),
            )
            if progress > 0:
                progress_width = int(bar_width * progress)
                gradient = Image.new("RGBA", (progress_width, bar_height), (0, 0, 0, 0))
                grad_draw = ImageDraw.Draw(gradient)
                for i in range(progress_width):
                    r = int(0 + (80 - 0) * (i / max(1, progress_width)))
                    g = int(180 + (255 - 180) * (i / max(1, progress_width)))
                    b = int(120 + (60 - 120) * (i / max(1, progress_width)))
                    grad_draw.line([(i, 0), (i, bar_height)], fill=(r, g, b, 255))
                mask = Image.new("L", (progress_width, bar_height), 0)
                ImageDraw.Draw(mask).rounded_rectangle(
                    [0, 0, progress_width, bar_height], radius=12, fill=255
                )
                img.paste(gradient, (bar_x, bar_y), mask)

                num_segments = 10
                segment_width = bar_width // num_segments
                for i in range(1, num_segments):
                    line_x = bar_x + i * segment_width
                    if line_x < bar_x + progress_width:
                        draw.line(
                            [(line_x, bar_y + 2), (line_x, bar_y + bar_height - 2)],
                            fill=(255, 255, 255, 100),
                            width=1,
                        )

            final_img = img.resize((360, 155), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            final_img.save(out, format="PNG")
            return out.getvalue()
        except Exception:
            traceback.print_exc()
            return None
