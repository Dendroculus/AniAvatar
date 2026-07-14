"""Leaderboard rendering orchestration."""

from __future__ import annotations

import io
import logging
import traceback
from typing import Optional

from PIL import Image, ImageDraw

from bot.config.configs import AssetPaths as AP
from bot.features.progression.rendering.layouts import (
    LeaderboardLayout,
)
from bot.features.progression.rendering.leaderboard_cache import (
    LeaderboardCacheMixin,
)
from bot.features.progression.rendering.leaderboard_layout import (
    LeaderboardLayoutMixin,
)
from bot.features.progression.rendering.leaderboard_rows import (
    LeaderboardRowsMixin,
)


class LeaderboardRendererMixin(
    LeaderboardCacheMixin,
    LeaderboardLayoutMixin,
    LeaderboardRowsMixin,
):
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
