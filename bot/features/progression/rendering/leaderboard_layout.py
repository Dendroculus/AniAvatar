"""Leaderboard resource preparation and layout calculation."""

from __future__ import annotations

from bot.features.progression.rendering.layouts import (
    LeaderboardLayout,
)


class LeaderboardLayoutMixin:
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
