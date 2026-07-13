"""Mixed-language text drawing for profile cards."""

from __future__ import annotations

from bot.features.progression.rendering.text import (
    split_into_runs,
)


class ProfileTextMixin:
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

            ProfileTextMixin._draw_run_styled(
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
