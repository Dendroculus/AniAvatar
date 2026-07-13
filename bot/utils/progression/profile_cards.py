from PIL import Image, ImageDraw
import traceback
import os
import io
import time
import logging
from typing import Optional, Dict, Tuple
from bot.config.configs import AssetPaths as AP
from bot.config.assets import resolve_background_path
from bot.features.progression.domain.levels import (
    get_title as _get_title,
    get_title_emoji as _get_title_emoji,
)
from bot.features.progression.rendering.layouts import (
    LeaderboardLayout,
    ProfileCardLayout,
)
from bot.features.progression.rendering.resources import AssetLoader, FontManager
from bot.features.progression.rendering.text import (
    format_number,
    split_into_runs,
    strip_emojis,
    truncate_to_width,
)

"""
PERSONAL NOTE : 
────────────────────────────
COLUMN_SHIFT = -8      # move LVL column & bullet left/right
BADGE_SHIFT = +12      # move title badge right/left
LVL_Y = -4             # move LVL text value column up/down neg is up otherwise
────────────────────────────
"""


class AvatarError(Exception):
    """Base exception for avatar-related issues."""


class AvatarLoadError(AvatarError):
    """Raised when avatar bytes are present but cannot be decoded/loaded."""


class AvatarBytesMissing(AvatarError):
    """Raised when avatar bytes are missing."""


#  Resource Managers (SRP Refactor)


#  Main Card Logic


def get_title(level: int) -> str:
    """Return the progression title for backward compatibility."""

    return _get_title(level)


def get_title_emoji(level: int):
    """Return the title emoji for backward compatibility."""

    return _get_title_emoji(level)


class CardDrawer:
    """
    Coordinates rendering logic using FontManager and AssetLoader.
    """

    def __init__(self, cache_size=200):
        self.fonts = FontManager()
        self.assets = AssetLoader()
        self._cache_size = cache_size
        self._leaderboard_cache: Dict[str, Tuple[float, bytes]] = {}

    def _get_cached_leaderboard(
        self, cache_key: Optional[str], ttl_seconds: int
    ) -> Optional[bytes]:
        if not cache_key or ttl_seconds <= 0:
            return None
        entry = self._leaderboard_cache.get(cache_key)
        if not entry:
            return None
        ts, payload = entry
        if (time.monotonic() - ts) <= ttl_seconds:
            return payload
        self._leaderboard_cache.pop(cache_key, None)
        return None

    def _set_cached_leaderboard(self, cache_key: Optional[str], payload: bytes) -> None:
        if not cache_key:
            return
        self._leaderboard_cache[cache_key] = (time.monotonic(), payload)
        if len(self._leaderboard_cache) > self._cache_size:
            oldest_key = min(self._leaderboard_cache.items(), key=lambda kv: kv[1][0])[
                0
            ]
            self._leaderboard_cache.pop(oldest_key, None)

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

            CardDrawer._draw_run_styled(
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

    @staticmethod
    def _draw_lb_cjk(
        draw_obj,
        pos,
        text,
        primary_font,
        cjk_font,
        fill,
        stroke_width=1,
        stroke_fill=(255, 255, 255, 255),
    ):
        x0, y0 = int(pos[0]), int(pos[1])
        runs = split_into_runs(text)
        for run_text, is_cjk in runs:
            font_to_use = cjk_font if is_cjk and cjk_font else primary_font
            if is_cjk and cjk_font:
                draw_obj.text(
                    (x0, y0),
                    run_text,
                    font=font_to_use,
                    fill=fill,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_fill,
                )
            else:
                draw_obj.text((x0, y0), run_text, font=font_to_use, fill=fill)
            try:
                w = draw_obj.textlength(run_text, font=font_to_use)
            except Exception:
                w, _ = font_to_use.getsize(run_text)
            x0 += int(w)

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

    def _prepare_leaderboard_resources(self, row_height, fonts, exp_icon_path):
        font_rank = self.fonts.get_font(
            fonts.get("bold"), max(12, int(row_height * 0.65))
        )
        font_name = self.fonts.get_font(
            fonts.get("bold"), max(12, int(row_height * 0.65))
        )
        # font_medium unused in original prep but kept for symmetry if needed
        # font_medium = self.fonts.get_font(fonts.get("medium"), max(10, int(row_height * 0.45)))
        font_bold = self.fonts.get_font(
            fonts.get("bold"), max(11, int(row_height * 0.55))
        )

        # Pre-calc heights
        font_rank_height = font_rank.getbbox("Ay")[3] - font_rank.getbbox("Ay")[1]
        font_bold_height = font_bold.getbbox("Ay")[3] - font_bold.getbbox("Ay")[1]
        font_lvl = self.fonts.get_font(
            fonts.get("medium"), max(10, int(row_height * 0.45))
        )
        font_medium_height = font_lvl.getbbox("Ay")[3] - font_lvl.getbbox("Ay")[1]

        cjk_font_name = cjk_font_medium = cjk_font_bold = None
        if fonts.get("cjk"):
            cjk_path = fonts.get("cjk")
            cjk_font_name = self.fonts.get_font(
                cjk_path, max(12, int(row_height * 0.65))
            )
            cjk_font_medium = self.fonts.get_font(
                cjk_path, max(10, int(row_height * 0.45))
            )
            cjk_font_bold = self.fonts.get_font(
                cjk_path, max(11, int(row_height * 0.55))
            )

        icon_sz = max(12, int(row_height * 0.65))
        exp_icon = self.assets.get_icon(exp_icon_path, icon_sz)

        return {
            "font_rank": font_rank,
            "font_name": font_name,
            "font_medium": font_lvl,  # Mapped correctly to medium font
            "font_bold": font_bold,
            "font_rank_height": font_rank_height,
            "font_medium_height": font_medium_height,
            "font_bold_height": font_bold_height,
            "cjk_font_name": cjk_font_name,
            "cjk_font_medium": cjk_font_medium,
            "cjk_font_bold": cjk_font_bold,
            "exp_icon": exp_icon,
        }

    def _compute_leaderboard_layout(
        self,
        rows,
        width,
        row_height,
        padding,
        header_height,
        panel_color,
        gradient_direction,
        draw,
        res,
    ):
        left_x = padding
        right_x = width - padding
        start_y = padding + header_height
        panel_radius = max(6, int(row_height * 0.25))
        avatar_gap_left = max(8, int(row_height * 0.25))
        avatar_size = max(16, int(row_height - max(6, row_height * 0.2)))
        avatar_x_offset = avatar_gap_left
        between_avatar_and_rank = max(8, int(row_height * 0.25))
        after_rank_gap = max(10, int(row_height * 0.3))
        bullet_spacing = max(8, int(row_height * 0.2))
        bullet_r = max(2, int(row_height * 0.12))
        bullet_vertical_nudge = max(1, int(row_height * 0.12))
        name_min_w = max(80, int(width * 0.18))
        extra_edge_margin = max(20, int(width * 0.05))

        try:
            max_rank_val = max((int(r.get("rank", 0)) for r in rows), default=1)
        except (ValueError, TypeError):
            max_rank_val = 99

        rank_placeholder = "#999" if max_rank_val > 99 else "#99"
        max_rank_w = draw.textlength(rank_placeholder, font=res["font_rank"])
        level_placeholder = "LVL 100"
        fixed_level_w = draw.textlength(level_placeholder, font=res["font_medium"])

        max_total_exp_w = 0
        for r in rows:
            try:
                exp_text = (
                    "MAXED"
                    if r.get("next_exp") is None
                    else f"{int(r.get('exp', 0)):,}/{int(r.get('next_exp', 0)):,}"
                )
            except (ValueError, TypeError):
                exp_text = "0/0"
            w = draw.textlength(exp_text, font=res["font_bold"])
            icon_gap = (res["exp_icon"].width + 6) if res["exp_icon"] else 0
            total_w = w + icon_gap
            if total_w > max_total_exp_w:
                max_total_exp_w = total_w

        exp_center_x = right_x - extra_edge_margin - max_total_exp_w // 2
        badge_size = max(14, int(row_height * 0.75))

        right_reserved = (
            (bullet_r * 2 + 12)
            + fixed_level_w
            + 8
            + badge_size
            + 8
            + max_total_exp_w
            + extra_edge_margin
        )
        left_reserved = (
            left_x
            + avatar_x_offset
            + avatar_size
            + between_avatar_and_rank
            + max_rank_w
            + after_rank_gap
            + (bullet_r * 2 + 12)
        )

        name_area_width = int(right_x - right_reserved - left_reserved)
        if name_area_width < name_min_w:
            delta = name_min_w - name_area_width
            right_reserved = max(0, right_reserved - delta)
            name_area_width = int(right_x - right_reserved - left_reserved)
            if name_area_width < 40:
                name_area_width = 40

        column_shift = LeaderboardLayout.COLUMN_SHIFT
        level_col_start = (
            right_x
            - extra_edge_margin
            - max_total_exp_w
            - 8
            - badge_size
            - 8
            - fixed_level_w
            - (bullet_r * 2 + 12)
        )
        level_col_start += column_shift
        min_allowed = left_reserved + name_min_w + 16
        if level_col_start < min_allowed:
            level_col_start = min_allowed

        return {
            "left_x": left_x,
            "right_x": right_x,
            "start_y": start_y,
            "row_height": row_height,
            "panel_radius": panel_radius,
            "panel_color": panel_color,
            "gradient_direction": gradient_direction,
            "extra_edge_margin": extra_edge_margin,
            "max_rank_w": max_rank_w,
            "fixed_level_w": fixed_level_w,
            "exp_center_x": exp_center_x,
            "badge_size": badge_size,
            "avatar_x_offset": avatar_x_offset,
            "avatar_size": avatar_size,
            "between_avatar_and_rank": between_avatar_and_rank,
            "after_rank_gap": after_rank_gap,
            "bullet_spacing": bullet_spacing,
            "bullet_r": bullet_r,
            "bullet_vertical_nudge": bullet_vertical_nudge,
            "level_col_start": level_col_start,
            "name_area_width": name_area_width,
        }

    def _draw_row_background(self, im, draw, x, y, w, h, rank_idx, i, layout):
        """
         Helper to render the row background (gradient for top 3, solid for others).

        Args:
             im (PIL.Image.Image): The image to draw on.
             draw (PIL.ImageDraw.Draw): The drawing context.
             x (int): The x-coordinate for the panel.
             y (int): The y-coordinate for the panel.
             w (int): The width of the panel.
             h (int): The height of the panel.
             rank_idx (int): The rank index (1-based).
             i (int): The row index (0-based).
             layout (dict): The precomputed layout parameters.

         Returns:
             None
        """
        rank_colors = {
            1: [(255, 223, 0), (255, 140, 0)],
            2: [(220, 220, 220), (169, 169, 169)],
            3: [(205, 127, 50), (139, 69, 19)],
        }
        colors = rank_colors.get(rank_idx)

        if colors:
            grad_panel = self.assets.get_linear_gradient(
                (w, h), colors, direction=layout["gradient_direction"] or "horizontal"
            )
            mask = Image.new("L", (w, h), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, w, h), radius=layout["panel_radius"], fill=255
            )
            im.paste(grad_panel, (x, y), mask)
        else:
            panel_color = layout["panel_color"]
            panel_fill = (
                panel_color if i % 2 == 0 else tuple(max(0, c - 6) for c in panel_color)
            )
            draw.rounded_rectangle(
                (x, y, x + w, y + h), radius=layout["panel_radius"], fill=panel_fill
            )

    def _draw_row_avatar(self, im, draw, avatar_bytes, x, y, size) -> None:
        """
        Helper to render the user avatar or a fallback placeholder.

        Args:
            im (PIL.Image.Image): The image to draw on.
            draw (PIL.ImageDraw.Draw): The drawing context.
            avatar_bytes (bytes): The avatar image bytes.
            x (int): The x-coordinate for the avatar.
            y (int): The y-coordinate for the avatar.
            size (int): The size of the avatar.

        Returns:
            None
        """
        avatar_loaded = False
        if avatar_bytes:
            avatar = self.assets.get_avatar(avatar_bytes, size)
            if avatar:
                mask = Image.new("L", (size, size), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
                im.paste(avatar, (x, y), mask)
                avatar_loaded = True

        if not avatar_loaded:
            draw.ellipse((x, y, x + size, y + size), fill=(100, 100, 100))

    def _draw_row_exp(self, im, draw, r, center_y, layout, res) -> None:
        """
        Helper to calculate and render the Experience points text and icon.

        Args:
            im (PIL.Image.Image): The image to draw on.
            draw (PIL.ImageDraw.Draw): The drawing context.
            r (dict): The row data.
            center_y (int): The vertical center position for the row.
            layout (dict): The precomputed layout parameters.
            res (dict): The preloaded resources (fonts, icons).

        Returns:
            None
        """
        try:
            exp_val = int(r.get("exp", 0) or 0)
            next_val = int(r.get("next_exp")) if r.get("next_exp") is not None else None
        except (ValueError, TypeError):
            exp_val, next_val = 0, None

        exp_text = (
            "MAXED"
            if next_val is None
            else f"{format_number(exp_val)}/{format_number(next_val)}"
        )

        font_bold = res["font_bold"]
        exp_icon = res["exp_icon"]

        exp_text_w = draw.textlength(exp_text, font=font_bold)
        icon_gap = (exp_icon.width + 6) if exp_icon else 0
        exp_block_w = exp_text_w + icon_gap
        exp_start = int(layout["exp_center_x"] - exp_block_w // 2) + 12

        if exp_icon:
            icon_y = int(center_y - exp_icon.height / 2)
            im.paste(exp_icon, (int(exp_start), icon_y), exp_icon)
            text_x = exp_start + exp_icon.width + 6
        else:
            text_x = exp_start

        text_y = int(center_y - res["font_bold_height"] / 2) - 4
        self._draw_lb_cjk(
            draw,
            (text_x, text_y),
            exp_text,
            font_bold,
            res["cjk_font_bold"],
            (255, 255, 255),
        )

    def _draw_leaderboard_row(self, im, draw, r, i, layout, res, rank_offset) -> None:
        """
        Renders a single row on the leaderboard image.
        Refactored to reduce Cognitive Complexity.

        Args:
            im (PIL.Image.Image): The image to draw on.
            draw (PIL.ImageDraw.Draw): The drawing context.
            r (dict): The row data.
            i (int): The row index.
            layout (dict): The precomputed layout parameters.
            res (dict): The preloaded resources (fonts, icons).
            rank_offset (int): Vertical offset for the rank text.

        Returns:
            None
        """
        # Layout Calculations
        left_x = layout["left_x"]
        row_height = layout["row_height"]
        y = layout["start_y"] + i * (row_height + max(8, int(row_height * 0.2)))
        panel_w = layout["right_x"] - left_x
        center_y = y + row_height // 2

        try:
            rank_idx = int(r.get("rank", i + 1))
        except (ValueError, TypeError):
            rank_idx = i + 1

        # 1. Draw Panel Background
        self._draw_row_background(
            im, draw, left_x, y, panel_w, row_height, rank_idx, i, layout
        )

        # 2. Draw Avatar
        av_x = left_x + layout["avatar_x_offset"]
        av_y = int(center_y - layout["avatar_size"] / 2)
        self._draw_row_avatar(
            im, draw, r.get("avatar_bytes"), av_x, av_y, layout["avatar_size"]
        )

        # 3. Draw Rank
        font_rank = res["font_rank"]
        rank_color = {1: (255, 255, 255), 2: (255, 255, 255), 3: (255, 255, 255)}.get(
            rank_idx, (200, 200, 200)
        )
        rank_str = f"#{rank_idx}"
        rank_box_x = av_x + layout["avatar_size"] + layout["between_avatar_and_rank"]
        rx = int(
            rank_box_x
            + (layout["max_rank_w"] - draw.textlength(rank_str, font=font_rank)) / 2
        )
        ry = int(center_y - res["font_rank_height"] / 2) + rank_offset
        draw.text((rx, ry), rank_str, font=font_rank, fill=rank_color)

        # 4. Draw Name (with bullet separators)
        bullet_r = layout["bullet_r"]
        bullet1_x = rank_box_x + layout["max_rank_w"] + layout["after_rank_gap"]
        bullet1_y = int(center_y - bullet_r + layout["bullet_vertical_nudge"])
        draw.ellipse(
            (bullet1_x, bullet1_y, bullet1_x + bullet_r * 2, bullet1_y + bullet_r * 2),
            fill=(255, 255, 255),
        )

        name_raw = str(r.get("name") or "Unknown")
        nm = strip_emojis(name_raw) or name_raw.strip()
        if len(nm) > LeaderboardLayout.NAME_MAX_CHARS:
            nm = nm[: LeaderboardLayout.NAME_MAX_CHARS - 3] + "..."
        if draw.textlength(nm, font=res["font_name"]) > layout["name_area_width"]:
            nm = truncate_to_width(
                nm, font=res["font_name"], max_w=layout["name_area_width"], draw=draw
            )

        name_start_x = bullet1_x + bullet_r * 2 + 12
        self._draw_lb_cjk(
            draw,
            (name_start_x, ry),
            nm,
            res["font_name"],
            res["cjk_font_name"],
            (255, 255, 255),
        )

        # 5. Draw Level & Badge
        bullet2_x = int(
            layout["level_col_start"] - layout["bullet_spacing"] - bullet_r * 2
        )
        draw.ellipse(
            (
                bullet2_x,
                int(center_y - bullet_r + layout["bullet_vertical_nudge"]) - 2,
                bullet2_x + bullet_r * 2,
                int(center_y - bullet_r + layout["bullet_vertical_nudge"])
                - 2
                + bullet_r * 2,
            ),
            fill=(255, 255, 255),
        )

        lvl_x = int(layout["level_col_start"]) + 2
        lvl_y = int(center_y - (res["font_medium_height"]) / 2) - 4
        level_text = f"LVL {int(r.get('level', 0))}"
        self._draw_lb_cjk(
            draw,
            (lvl_x, lvl_y),
            level_text,
            res["font_medium"],
            res["cjk_font_medium"],
            (255, 255, 255),
        )

        badge_path = (
            AP.TITLE_EMOJI_FILES.get((r.get("title") or "").strip())
            if isinstance(AP.TITLE_EMOJI_FILES, dict)
            else None
        )
        badge_img = self.assets.get_icon(badge_path, layout["badge_size"])
        if badge_img:
            bx = lvl_x + layout["fixed_level_w"] + LeaderboardLayout.BADGE_SHIFT
            by = int(center_y - layout["badge_size"] / 2)
            im.paste(badge_img, (int(bx), int(by)), badge_img)

        # 6. Draw EXP
        self._draw_row_exp(im, draw, r, center_y, layout, res)

    def create_leaderboard_image(
        self,
        rows,
        width=820,
        row_height=48,
        padding=12,
        fonts=None,
        exp_icon_path=None,
        background_color=(38, 40, 43),
        panel_color=(55, 58, 61),
        header_height=0,
        gradient=True,
        gradient_colors=None,
        gradient_direction=None,
        gradient_noise=True,
        gradient_seed=None,
        debug_save_path: str = None,
        rank_offset: int = LeaderboardLayout.RANK_OFFSET_DEFAULT,
        cache_key: Optional[str] = None,
        cache_ttl: int = 120,
    ) -> bytes:
        try:
            cached = self._get_cached_leaderboard(cache_key, cache_ttl)
            if cached is not None:
                return cached

            fonts = fonts or AP.FONTS
            rows = list(rows or [])
            n = len(rows)

            gap_between_rows = max(8, int(row_height * 0.2))
            height = padding * 2 + header_height + n * (row_height + gap_between_rows)

            # Draw background
            if gradient:
                im = self.assets.generate_random_gradient(
                    (width, height),
                    direction=gradient_direction,
                    colors=gradient_colors,
                    noise=gradient_noise,
                    seed=gradient_seed,
                ).convert("RGBA")
            else:
                im = Image.new("RGBA", (width, height), background_color)
            draw = ImageDraw.Draw(im)

            res = self._prepare_leaderboard_resources(row_height, fonts, exp_icon_path)
            layout = self._compute_leaderboard_layout(
                rows,
                width,
                row_height,
                padding,
                header_height,
                panel_color,
                gradient_direction,
                draw,
                res,
            )

            for i, r in enumerate(rows):
                self._draw_leaderboard_row(im, draw, r, i, layout, res, rank_offset)

            out = io.BytesIO()
            im.save(out, format="PNG")
            out.seek(0)
            payload = out.getvalue()

            self._set_cached_leaderboard(cache_key, payload)
            if debug_save_path:
                try:
                    with open(debug_save_path, "wb") as fh:
                        fh.write(payload)
                except OSError as e:
                    logging.getLogger("profile_cards").warning(
                        f"Failed to save debug leaderboard image to {debug_save_path}: {e}"
                    )

            return payload

        except Exception:
            traceback.print_exc()
            fallback = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
            b = io.BytesIO()
            fallback.save(b, format="PNG")
            return b.getvalue()


class ImageRenderer(CardDrawer):
    """
    Compatibility wrapper for CardDrawer to maintain public API.
    """

    pass
