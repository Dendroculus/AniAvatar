"""Profile-card canvas, background, and color handling."""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

from bot.config.assets import resolve_background_path


class ProfileCanvasMixin:
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
