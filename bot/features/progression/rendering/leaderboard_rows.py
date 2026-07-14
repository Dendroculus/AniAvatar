"""Drawing operations for individual leaderboard rows."""

from __future__ import annotations

from PIL import Image, ImageDraw

from bot.config.configs import AssetPaths as AP
from bot.features.progression.rendering.layouts import (
    LeaderboardLayout,
)
from bot.features.progression.rendering.text import (
    format_number,
    split_into_runs,
    strip_emojis,
    truncate_to_width,
)


class LeaderboardRowsMixin:
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
