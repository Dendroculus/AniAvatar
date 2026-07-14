"""Cached font and image resource loaders used by renderers."""

from __future__ import annotations

import colorsys
import io
import os
import random
from typing import Optional

from PIL import Image, ImageFont


class FontManager:
    """
    Manages loading and caching of TrueType fonts.
    """

    def __init__(self):
        self._font_cache = {}

    def get_font(self, path: str, size: float) -> ImageFont.FreeTypeFont:
        """
        Load a font from path with the specified size.
        Returns a default font if loading fails.
        """
        key = (path, int(size))
        if key in self._font_cache:
            return self._font_cache[key]

        try:
            f = ImageFont.truetype(path, int(size))
        except (OSError, ValueError):
            # Fallback for missing file or bad format
            f = ImageFont.load_default()

        self._font_cache[key] = f
        return f

    def prepare_profile_fonts(self, fonts_config: dict) -> dict:
        """
        Pre-load standard profile fonts based on configuration.
        """
        font_username = self.get_font(fonts_config.get("bold"), 32.5)
        font_medium = self.get_font(fonts_config.get("medium"), 25.5)
        font_small = self.get_font(fonts_config.get("regular"), 21.5)

        cjk_font_username = None
        cjk_font_medium = None
        cjk_font_small = None

        if fonts_config.get("cjk"):
            # We attempt to load CJK fonts, but treat failure gracefully (None)
            # unlike main fonts which fallback to default.
            try:
                cjk_path = fonts_config.get("cjk")
                cjk_font_username = self.get_font(cjk_path, 32.5)
                cjk_font_medium = self.get_font(cjk_path, 25.5)
                cjk_font_small = self.get_font(cjk_path, 21.5)
            except (OSError, ValueError):
                pass

        return {
            "font_username": font_username,
            "font_medium": font_medium,
            "font_small": font_small,
            "cjk_font_username": cjk_font_username,
            "cjk_font_medium": cjk_font_medium,
            "cjk_font_small": cjk_font_small,
        }


class AssetLoader:
    """
    Manages loading, caching, and generation of image assets (avatars, icons, gradients).
    """

    def __init__(self):
        self._avatar_cache = {}
        self._icon_cache = {}
        self._panel_grad_cache = {}

    def _avatar_cache_key(self, avatar_bytes, size, quick_hash_len=64):
        if not avatar_bytes:
            return None
        return (len(avatar_bytes), avatar_bytes[:quick_hash_len], int(size))

    def get_avatar(self, avatar_bytes: bytes, size: int) -> Optional[Image.Image]:
        """
        Load an avatar from bytes, resize it, and cache the result.
        """
        key = self._avatar_cache_key(avatar_bytes, size)
        if not key:
            return None

        if key in self._avatar_cache:
            return self._avatar_cache[key]

        try:
            avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar = avatar.resize((int(size), int(size)), Image.Resampling.LANCZOS)
            self._avatar_cache[key] = avatar
            return avatar
        except (OSError, ValueError):
            return None

    def get_icon(self, path: str, size: int) -> Optional[Image.Image]:
        """
        Load an icon from disk, resize it, and cache the result.
        """
        if not path or not os.path.exists(path):
            return None

        key = (path, int(size))
        if key in self._icon_cache:
            return self._icon_cache[key]

        try:
            img = (
                Image.open(path)
                .convert("RGBA")
                .resize((int(size), int(size)), Image.Resampling.LANCZOS)
            )
            self._icon_cache[key] = img
            return img
        except (OSError, ValueError):
            return None

    @staticmethod
    def _lerp(a, b, t):
        return int(round(a + (b - a) * t))

    def _interpolate_color(self, c1, c2, t):
        return (
            self._lerp(c1[0], c2[0], t),
            self._lerp(c1[1], c2[1], t),
            self._lerp(c1[2], c2[2], t),
            self._lerp(c1[3] if len(c1) > 3 else 255, c2[3] if len(c2) > 3 else 255, t),
        )

    @staticmethod
    def _random_color(hue=None, sat=None, val=None, alpha=255):
        h = hue if hue is not None else random.random()
        s = sat if sat is not None else random.uniform(0.5, 0.9)
        v = val if val is not None else random.uniform(0.6, 0.95)
        r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(h, s, v)]
        return (r, g, b, alpha)

    def get_linear_gradient(self, size, colors, direction="horizontal") -> Image.Image:
        """
        Get or generate a cached linear gradient.
        """
        key = (tuple(tuple(c) for c in colors), size, direction)
        if key in self._panel_grad_cache:
            return self._panel_grad_cache[key]

        w, h = size
        if not colors or len(colors) < 2:
            colors = [(0, 0, 0, 255), (255, 255, 255, 255)]

        c1, c2 = colors[0], colors[1]
        ramp_len = 256

        if direction == "horizontal":
            ramp = Image.new("RGBA", (ramp_len, 1))
            rp = ramp.load()
            for x in range(ramp_len):
                t = x / (ramp_len - 1)
                rp[x, 0] = (
                    int(c1[0] * (1 - t) + c2[0] * t),
                    int(c1[1] * (1 - t) + c2[1] * t),
                    int(c1[2] * (1 - t) + c2[2] * t),
                    255,
                )
            img = ramp.resize((w, h), resample=Image.Resampling.BICUBIC)
        else:
            ramp = Image.new("RGBA", (1, ramp_len))
            rp = ramp.load()
            for y in range(ramp_len):
                t = y / (ramp_len - 1)
                rp[0, y] = (
                    int(c1[0] * (1 - t) + c2[0] * t),
                    int(c1[1] * (1 - t) + c2[1] * t),
                    int(c1[2] * (1 - t) + c2[2] * t),
                    255,
                )
            img = ramp.resize((w, h), resample=Image.Resampling.BICUBIC)

        self._panel_grad_cache[key] = img
        return img

    def generate_random_gradient(
        self, size, direction=None, colors=None, noise=False, seed=None
    ) -> Image.Image:
        """
        Generates a gradient on the fly. Not cached due to high variance of parameters (seeds).
        """
        if seed is not None:
            random.seed(seed)

        w, h = size
        if direction is None:
            direction = random.choice(["vertical", "horizontal", "diagonal"])

        if not colors:
            if random.random() < 0.3:
                colors = [
                    self._random_color(),
                    self._random_color(),
                    self._random_color(),
                ]
            else:
                colors = [self._random_color(), self._random_color()]

        colors = [tuple(c if len(c) == 4 else (c[0], c[1], c[2], 255)) for c in colors]

        small_w, small_h = (2, 2)
        tiny_img = Image.new("RGBA", (small_w, small_h))

        c0 = colors[0]
        c1 = colors[1]

        if direction == "vertical":
            tiny_img.putpixel((0, 0), c0)
            tiny_img.putpixel((1, 0), c0)
            tiny_img.putpixel((0, 1), c1)
            tiny_img.putpixel((1, 1), c1)
        elif direction == "horizontal":
            tiny_img.putpixel((0, 0), c0)
            tiny_img.putpixel((0, 1), c0)
            tiny_img.putpixel((1, 0), c1)
            tiny_img.putpixel((1, 1), c1)
        else:
            tiny_img.putpixel((0, 0), c0)
            tiny_img.putpixel((1, 1), c1)
            tiny_img.putpixel((0, 1), self._interpolate_color(c0, c1, 0.5))
            tiny_img.putpixel((1, 0), self._interpolate_color(c0, c1, 0.5))

        img = tiny_img.resize((w, h), resample=Image.Resampling.BICUBIC)

        if noise:
            noise_w, noise_h = w // 4, h // 4
            noise_img = Image.effect_noise((noise_w, noise_h), sigma=10).convert("RGBA")
            noise_img.putalpha(20)
            noise_img = noise_img.resize((w, h), Image.Resampling.NEAREST)
            img = Image.alpha_composite(img, noise_img)

        return img
