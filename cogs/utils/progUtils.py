from PIL import Image, ImageDraw, ImageFont
from cogs.utils.constants import *
import traceback
import discord
import os
import io
import random
import sqlite3
import colorsys
import re
import unicodedata

"""
PERSONAL NOTE : 
────────────────────────────
column_shift = -8      # move LVL column & bullet left/right   # IF YOU ARE USING THIS BOT YOU CAN IGNORE THIS
badge_shift = +12      # move title badge right/left
lvl_y = -4             # move LVL text value column up/down neg is up otherwise
────────────────────────────

"""

_INVISIBLE_RE = re.compile(r'[\u200D\uFE0F\u200E\u200F\u2060-\u2064\uFEFF]', flags=re.UNICODE)
_CTRL_RE = re.compile(r'[\x00-\x1F\x7F]', flags=re.UNICODE)

_space_collapse_re = re.compile(r'\s+', flags=re.UNICODE)

def format_number(num: int) -> str:
    if num < 1_000:
        return str(num)
    elif num < 1_000_000:
        return f"{num / 1_000:.2f}K".rstrip("0").rstrip(".")
    elif num < 1_000_000_000:
        return f"{num / 1_000_000:.2f}M".rstrip("0").rstrip(".")
    else:
        return f"{num / 1_000_000_000:.2f}B".rstrip("0").rstrip(".")
    
def strip_emojis(s: str) -> str:
    if not s:
        return s
    s = _INVISIBLE_RE.sub("", s)
    out_chars = []
    for ch in s:
        cat = unicodedata.category(ch)
        if cat.startswith("So") or cat.startswith("Sk"):
            continue
        out_chars.append(ch)
    s = "".join(out_chars)

    s = _CTRL_RE.sub("", s)
    s = _space_collapse_re.sub(" ", s).strip()
    return s

_AVATAR_CACHE = {}
_PANEL_GRAD_CACHE = {}
_ICON_CACHE = {}
_FONT_CACHE = {}

TITLE_COLORS = {
    "Novice": discord.Color.light_gray(),
    "Warrior": discord.Color.red(),
    "Elite": discord.Color.orange(),
    "Champion": discord.Color.gold(),
    "Hero": discord.Color.green(),
    "Legend": discord.Color.blue(),
    "Mythic": discord.Color.purple(),
    "Ascendant": discord.Color.teal(),
    "Immortal": discord.Color.dark_red(),
    "Celestial": discord.Color.dark_blue(),
    "Transcendent": discord.Color.dark_purple(),
    "Aetherborn": discord.Color.dark_teal(),
    "Cosmic": discord.Color.dark_magenta(),
    "Divine": discord.Color.green(),
    "Eternal": discord.Color.red(),
    "Enlightened": discord.Color.blue(),
}


def is_cjk_char(ch: str) -> bool: 
    if not ch:
        return False
    try:
        cp = ord(ch)
    except TypeError:
        return False
    # CJK Unified Ideographs
    if 0x4E00 <= cp <= 0x9FFF: 
        return True
    # CJK Unified Ideographs Extension A
    if 0x3400 <= cp <= 0x4DBF: 
        return True
    # CJK Unified Ideographs Extension B..E 
    if 0x20000 <= cp <= 0x2CEAF: 
        return True
    # CJK Compatibility Ideographs
    if 0xF900 <= cp <= 0xFAFF: 
        return True
    # CJK Compatibility Ideographs Supplement
    if 0x2F800 <= cp <= 0x2FA1F: 
        return True
    # Hangul Syllables
    if 0xAC00 <= cp <= 0xD7AF: 
        return True
    # Hiragana / Katakana
    if 0x3040 <= cp <= 0x30FF: 
        return True
    return False


def split_into_runs(text: str):
    if not text:
        return []
    runs = []
    current_run = text[0]
    current_is_cjk = is_cjk_char(text[0])
    for ch in text[1:]:
        is_cjk = is_cjk_char(ch)
        if is_cjk == current_is_cjk:
            current_run += ch
        else:
            runs.append((current_run, current_is_cjk))
            current_run = ch
            current_is_cjk = is_cjk
    runs.append((current_run, current_is_cjk))
    return runs


def get_title(level: int):
    if level < 5: return "Novice"
    elif level < 10: return "Warrior"
    elif level < 15: return "Elite"
    elif level < 20: return "Champion"
    elif level < 25: return "Hero"
    elif level < 30: return "Legend"
    elif level < 35: return "Mythic"
    elif level < 40: return "Ascendant"
    elif level < 50: return "Immortal"
    elif level < 60: return "Celestial"
    elif level < 70: return "Transcendent"
    elif level < 80: return "Aetherborn"
    elif level < 90: return "Cosmic"
    elif level < 100: return "Divine"
    elif level < 125: return "Eternal"
    else: return "Enlightened"

def get_title_emoji(level: int):
    if level < 5: return "<:NOVICE:1414508405002862663>"
    elif level < 10: return "<:WARRIOR:1414508311650242661>"
    elif level < 15: return "<:ELITE:1414508395301699724>"
    elif level < 20: return "<:CHAMPION:1414508304448749568>"
    elif level < 25: return "<:HERO:1414508388812853258>"
    elif level < 30: return "<:LEGEND:1414508296269856768>"
    elif level < 35: return "<:MYTHIC:1414508380172587099>"
    elif level < 40: return "<:ASCENDANT:1414508291341684776>"
    elif level < 50: return "<:IMMORTAL:1414508281543524454>"
    elif level < 60: return "<:CELESTIAL:1414508342520320070>"
    elif level < 70: return "<:TRANSCENDENT:1414508273767288832>"
    elif level < 80: return "<:AETHERBORN:1414508333951483904>"
    elif level < 90: return "<:COSMIC:1414508264695005184>"
    elif level < 100: return "<:DIVINE:1414508323763388446>"
    elif level < 125: return "<:ETERNAL:1414508351676481536>"
    else: return "<:ENLIGHTENED:1414508255744360510>"

DB_PATH = os.path.join(ROOT_PATH, "data", "minori.db")

def get_user_rank(user_id: int, guild_id: int, max_level: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        """
        SELECT user_id
        FROM users
        WHERE guild_id = ?
        AND ((exp > 0 AND level >= 1) OR level = ?)
        ORDER BY level DESC, exp DESC
        """,
        (guild_id, max_level)
    )
    rows = c.fetchall()
    conn.close()

    for i, row in enumerate(rows, start=1):
        if row[0] == user_id:
            return i
    return None


def render_profile_image(
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
    user_rank: int = None
) -> bytes:
    try:
        def _load_font(path, size):
            try:
                return ImageFont.truetype(path, int(size))
            except Exception:
                return ImageFont.load_default()


        def get_adaptive_font_color(bg_path):
            try:
                bg = Image.open(bg_path).convert("RGB")
                small = bg.resize((10, 10))
                pixels = list(small.getdata())
                avg_r = sum(p[0] for p in pixels)/len(pixels)
                avg_g = sum(p[1] for p in pixels)/len(pixels)
                avg_b = sum(p[2] for p in pixels)/len(pixels)

                def lum(c):
                    c = c/255
                    return c/12.92 if c <= 0.03928 else ((c+0.055)/1.055)**2.4

                L_bg = 0.2126*lum(avg_r) + 0.7152*lum(avg_g) + 0.0722*lum(avg_b)
                contrast_white = (max(L_bg, 1)+0.05)/(min(L_bg, 1)+0.05)
                contrast_black = (max(L_bg, 0)+0.05)/(min(L_bg, 0)+0.05)

                return (255,255,255) if contrast_white >= contrast_black else (0,0,0)
            except:
                return (255,255,255)

        def generate_default_bg(width, height):
            bg = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            grad = ImageDraw.Draw(bg)
            for y in range(height):
                r = int(120 + (180 - 120) * (y / height))   # purple gradient
                g = int(60 + (100 - 60) * (y / height))
                b = int(160 + (220 - 160) * (y / height))
                grad.line([(0, y), (width, y)], fill=(r, g, b, 255))

            shape = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            shape_draw = ImageDraw.Draw(shape)
            shape_draw.polygon([(width,0), (width,80), (width-120,0)], fill=(255,255,255,40))
            bg = Image.alpha_composite(bg, shape)

            shape2 = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            shape2_draw = ImageDraw.Draw(shape2)
            shape2_draw.polygon([(0,height), (0,height-80), (120,height)], fill=(0,0,0,60))
            bg = Image.alpha_composite(bg, shape2)

            return bg

        font_username = _load_font(fonts.get("bold"), 32.5)
        font_medium = _load_font(fonts.get("medium"), 25.5)
        font_small = _load_font(fonts.get("regular"), 21.5)

        cjk_font_username = None
        cjk_font_medium = None
        cjk_font_small = None
        if fonts.get("cjk"):
            try:
                cjk_font_username = _load_font(fonts.get("cjk"), 32.5)
                cjk_font_medium = _load_font(fonts.get("cjk"), 25.5)
                cjk_font_small = _load_font(fonts.get("cjk"), 21.5)
            except Exception:
                cjk_font_username = cjk_font_medium = cjk_font_small = None

        width, height = 600, 260
        corner_radius = 40

        img = Image.new("RGBA", (width, height), (0,0,0,0))
        mask = Image.new("L", (width, height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([0,0,width,height], radius=corner_radius, fill=255)

        if theme_name == "default" or not bg_file:
            bg = generate_default_bg(width, height)
        else:
            bg_path = os.path.join(BG_PATH, theme_name.lower(), bg_file)
            if os.path.exists(bg_path):
                bg = Image.open(bg_path).convert("RGBA").resize((width, height))
            else:
                bg = generate_default_bg(width, height)

        overlay = Image.new("RGBA", (width, height), (0,0,0,60))
        bg = Image.alpha_composite(bg, overlay)

        img.paste(bg, (0,0), mask)
        draw = ImageDraw.Draw(img)

        if font_color is None and theme_name != "default" and bg_file:
            bg_path = os.path.join(BG_PATH, theme_name.lower(), bg_file)
            font_color = get_adaptive_font_color(bg_path)
        elif font_color is None:
            font_color = (255,255,255)

        left_margin = 40
        top_margin = 30

        avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((110, 110))

        mask = Image.new("L", avatar.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse([0, 0, avatar.size[0], avatar.size[1]], fill=255)
        avatar_circle = Image.new("RGBA", avatar.size, (0, 0, 0, 0))
        avatar_circle.paste(avatar, (0, 0), mask)

        glow_size = (avatar.size[0] + 12, avatar.size[1] + 12)
        glow = Image.new("RGBA", glow_size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.ellipse([0, 0, glow_size[0], glow_size[1]], fill=(255, 255, 255, 80))

        avatar_offset = -20
        img.paste(glow, (left_margin + avatar_offset, top_margin + 5), glow)
        img.paste(avatar_circle, (left_margin + 6 + avatar_offset, top_margin + 11), avatar_circle)

        x, y = left_margin + 130, top_margin

        def draw_cjk(pos, text, primary_font, cjk_font, fill, small=False, stroke_width=2, stroke_fill=(0,0,0,255)):
            x0, y0 = pos
            runs = split_into_runs(text)
            for run_text, is_cjk in runs:
                font_to_use = cjk_font if (is_cjk and cjk_font) else primary_font
                y_offset = -3 if is_cjk else 0

                if small:
                    draw.text((x0+1, y0 + y_offset), run_text, font=font_to_use, fill=(0,0,0,100))

                    if is_cjk and cjk_font:
                        draw.text(
                            (x0, y0 + y_offset),
                            run_text,
                            font=font_to_use,
                            fill=fill,
                            stroke_width=int(round(1.1)),
                            stroke_fill=(255,255,255,255)
                        )
                    else:
                        draw.text((x0, y0 + y_offset), run_text, font=font_to_use, fill=fill)
                else:
                    draw.text((x0+2, y0+2 + y_offset), run_text, font=font_to_use, fill=(0,0,0,180))
                    draw.text(
                        (x0, y0 + y_offset),
                        run_text,
                        font=font_to_use,
                        fill=fill,
                        stroke_width=stroke_width,
                        stroke_fill=stroke_fill
                    )

                try:
                    w = draw.textlength(run_text, font=font_to_use)
                except Exception:
                    w, _ = font_to_use.getsize(run_text)
                x0 += int(w)


        clean_name = strip_emojis(display_name)
        display_name_only = clean_name if clean_name else display_name
        if len(display_name_only) > 12:
            display_name_only = display_name_only[:12] + "..."

        def meas_mwidth(text, primary_font, cjk_font):
            w = 0
            for run_text, is_cjk in split_into_runs(text):
                font_to_use = cjk_font if (is_cjk and cjk_font) else primary_font
                try:
                    w += draw.textlength(run_text, font=font_to_use)
                except Exception:
                    w += font_to_use.getsize(run_text)[0]
            return int(w)

        draw_cjk((x, y), display_name_only, font_username, cjk_font_username, font_color, small=True)

        if user_rank is not None:
            rank_text = f"  #{user_rank}"
            name_w = meas_mwidth(display_name_only, font_username, cjk_font_username)
            rank_x = x + name_w
            draw.text((rank_x+1, y), rank_text, font=font_username, fill=(0,0,0,100))
            draw.text((rank_x, y), rank_text, font=font_username, fill=font_color)

        y += 40

        labels = ["Title ", "Level ", "EXP "]
        values = [
            title_name,
            str(level),
            f"{exp:,} / {next_exp:,}" if next_exp else "∞"
        ]

        label_width = max(draw.textlength(lbl, font=font_medium) for lbl in labels)

        for label, value in zip(labels, values):
            draw_cjk((x, y), label, font_medium, cjk_font_medium, font_color)
            colon_x = x + label_width + 8
            draw_cjk((colon_x, y), ":", font_medium, cjk_font_medium, font_color)
            value_x = colon_x + 12
            draw_cjk((value_x, y), value, font_medium, cjk_font_medium, font_color)

            if label.strip() == "Title":
                emoji_path = title_emoji_files.get(title_name)
                if emoji_path and os.path.exists(emoji_path):
                    try:
                        badge = Image.open(emoji_path).convert("RGBA").resize((49, 44))
                        bx = int(value_x + draw.textlength(value, font=font_medium) + 10)
                        bbox = font_medium.getbbox(value)
                        text_height = bbox[3] - bbox[1]
                        by = int(y + text_height / 2 - badge.height / 2 + 8)
                        img.paste(badge, (bx, by), badge)
                    except:
                        pass
            y += 32

        if next_exp is not None:
            next_line = f"Gain {max(0, next_exp - exp):,} more EXP to level up!"
        else:
            next_line = "You are at max level!"
        draw_cjk(
                (x, y),
                next_line,
                font_small,
                cjk_font_small,
                (255,255,255),
                stroke_width=2.6,
                stroke_fill=(0,0,0,255)
            )
        y += 40

        # EXP Bar 
        bar_x, bar_y = x, y
        bar_width, bar_height = width - bar_x - left_margin, 24
        progress = (exp / next_exp) if next_exp is not None else 1

        draw.rounded_rectangle(
            [bar_x, bar_y, bar_x + bar_width, bar_y + bar_height],
            radius=12,
            fill=(30, 30, 30)
        )

        if progress > 0:
            progress_width = int(bar_width * progress)
            gradient = Image.new("RGBA", (progress_width, bar_height), (0, 0, 0, 0))
            grad_draw = ImageDraw.Draw(gradient)

            for i in range(progress_width):
                r = int(0 + (80 - 0) * (i / max(1,progress_width)))
                g = int(180 + (255 - 180) * (i / max(1,progress_width)))
                b = int(120 + (60 - 120) * (i / max(1,progress_width)))
                grad_draw.line([(i, 0), (i, bar_height)], fill=(r, g, b, 255))

            mask = Image.new("L", (progress_width, bar_height), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([0, 0, progress_width, bar_height], radius=12, fill=255)
            img.paste(gradient, (bar_x, bar_y), mask)

            num_segments = 10
            segment_width = bar_width // num_segments
            for i in range(1, num_segments):
                line_x = bar_x + i * segment_width
                if line_x < bar_x + progress_width:
                    draw.line(
                        [(line_x, bar_y + 2), (line_x, bar_y + bar_height - 2)],
                        fill=(255, 255, 255, 100),
                        width=1
                    )

        final_img = img.resize((360,155), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        final_img.save(out, format="PNG")
        return out.getvalue()

    except Exception:
        traceback.print_exc()
        return None

def _safe_load_font(path, size):
    key = (path, int(size))
    f = _FONT_CACHE.get(key)
    if f:
        return f
    try:
        f = ImageFont.truetype(path, int(size))
    except Exception as e:
        f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f

def _lerp(a, b, t):
    return int(round(a + (b - a) * t))

def _interpolate_color(c1, c2, t):
    return (
        _lerp(c1[0], c2[0], t),
        _lerp(c1[1], c2[1], t),
        _lerp(c1[2], c2[2], t),
        _lerp(c1[3] if len(c1) > 3 else 255, c2[3] if len(c2) > 3 else 255, t)
    )

def _random_color(hue=None, sat=None, val=None, alpha=255):
    h = hue if hue is not None else random.random()
    s = sat if sat is not None else random.uniform(0.5, 0.9)
    v = val if val is not None else random.uniform(0.6, 0.95)
    r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(h, s, v)]
    return (r, g, b, alpha)

def _random_gradient(size, direction=None, colors=None, noise=False, seed=None):
    if seed is not None:
        random.seed(seed)
    w, h = size
    if direction is None:
        direction = random.choice(['vertical', 'horizontal', 'diagonal'])
    if not colors:
        if random.random() < 0.3:
            colors = [_random_color(), _random_color(), _random_color()]
        else:
            colors = [_random_color(), _random_color()]
    colors = [tuple(c if len(c) == 4 else (c[0], c[1], c[2], 255)) for c in colors]
    img = Image.new("RGBA", (w, h))
    pix = img.load()

    if len(colors) == 2:
        c0, c1 = colors
        for y in range(h):
            for x in range(w):
                if direction == 'vertical':
                    t = y / max(h-1,1)
                elif direction == 'horizontal':
                    t = x / max(w-1,1)
                else:
                    t = (x + y) / max(w + h - 2, 1)
                pix[x, y] = _interpolate_color(c0, c1, t)
    else:
        c0, c1, c2 = colors
        for y in range(h):
            for x in range(w):
                if direction == 'vertical':
                    t = y / max(h-1,1)
                elif direction == 'horizontal':
                    t = x / max(w-1,1)
                else:
                    t = (x + y) / max(w + h - 2, 1)
                if t <= 0.5:
                    pix[x, y] = _interpolate_color(c0, c1, t / 0.5)
                else:
                    pix[x, y] = _interpolate_color(c1, c2, (t-0.5)/0.5)

    if noise:
        noise_img = Image.new("RGBA", (w,h))
        npx = noise_img.load()
        for y in range(h):
            for x in range(w):
                alpha = int(random.uniform(6,18))
                npx[x,y] = (0,0,0,alpha)
        img = Image.alpha_composite(img, noise_img)
    return img

def _make_linear_gradient(size, colors, direction="horizontal"):
    w, h = size
    grad = Image.new("RGBA", (w,h))
    draw = ImageDraw.Draw(grad)
    if direction=="horizontal":
        for x in range(w):
            t = x / max(w-1,1)
            r = int(colors[0][0]*(1-t) + colors[1][0]*t)
            g = int(colors[0][1]*(1-t) + colors[1][1]*t)
            b = int(colors[0][2]*(1-t) + colors[1][2]*t)
            draw.line([(x,0),(x,h)], fill=(r,g,b,255))
    else:
        for y in range(h):
            t = y / max(h-1,1)
            r = int(colors[0][0]*(1-t) + colors[1][0]*t)
            g = int(colors[0][1]*(1-t) + colors[1][1]*t)
            b = int(colors[0][2]*(1-t) + colors[1][2]*t)
            draw.line([(0,y),(w,y)], fill=(r,g,b,255))
    return grad

def _avatar_cache_key_from_bytes(avatar_bytes, size, quick_hash_len=64):
    if not avatar_bytes:
        return None
    return (len(avatar_bytes), avatar_bytes[:quick_hash_len], int(size))

def _load_avatar_cached(avatar_bytes, size):
    key = _avatar_cache_key_from_bytes(avatar_bytes, size)
    if not key:
        return None
    img = _AVATAR_CACHE.get(key)
    if img is None:
        try:
            avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            avatar = avatar.resize((int(size), int(size)), Image.Resampling.LANCZOS)
            _AVATAR_CACHE[key] = avatar
            img = avatar
        except Exception:
            return None
    return img

def load_icon_cached(path, size):
    key = (path, int(size))
    img = _ICON_CACHE.get(key)
    if img is None and path and os.path.exists(path):
        try:
            img = Image.open(path).convert("RGBA").resize((int(size), int(size)), Image.Resampling.LANCZOS)
        except Exception:
            img = None
        _ICON_CACHE[key] = img
    return img

def get_panel_gradient(colors, size, direction):
    key = (tuple(tuple(c) for c in colors), size, direction)
    img = _PANEL_GRAD_CACHE.get(key)
    if img is None:
        img = _make_linear_gradient(size, colors, direction=direction)
        _PANEL_GRAD_CACHE[key] = img
    return img

def draw_text_gradient(im, position, text, font, gradient_colors, direction="vertical"):
    if not text: return
    bbox = font.getbbox(text)
    text_w = bbox[2]-bbox[0]
    text_h = bbox[3]-bbox[1]
    pad_x = max(4,int(0.06*text_w))
    pad_y = max(6,int(0.18*text_h))
    mask_w = text_w+pad_x*2
    mask_h = text_h+pad_y*2
    mask = Image.new("L",(mask_w,mask_h),0)
    md = ImageDraw.Draw(mask)
    md.text((pad_x - bbox[0], pad_y - bbox[1]), text, font=font, fill=255)
    grad = Image.new("RGBA",(mask_w,mask_h),(0,0,0,0))
    gd = grad.load()
    length = mask_w if direction=="horizontal" else mask_h
    for i in range(length):
        t = i/max(1,length-1)
        seg_count = len(gradient_colors)-1
        seg = min(max(0,int(t*seg_count)), seg_count-1) if seg_count>0 else 0
        local_t = (t - seg/seg_count)*seg_count if seg_count>0 else 0
        c1 = gradient_colors[seg]
        c2 = gradient_colors[min(seg+1,len(gradient_colors)-1)]
        col = (int(c1[0]+(c2[0]-c1[0])*local_t),
               int(c1[1]+(c2[1]-c1[1])*local_t),
               int(c1[2]+(c2[2]-c1[2])*local_t),255)
        if direction=="horizontal":
            for y in range(mask_h):
                gd[i,y] = col
        else:
            for x in range(mask_w):
                gd[x,i] = col
    im.paste(grad,(int(position[0]-pad_x),int(position[1]-pad_y)),mask)

def truncate_to_width(text, font, max_w, draw):
    if draw.textlength(text, font=font) <= max_w:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        if draw.textlength(text[:mid] + "..", font=font) <= max_w:
            lo = mid + 1
        else:
            hi = mid
    return text[:max(0, lo-1)] + ".."

def create_leaderboard_image(
    rows,
    width=820,
    row_height=48,
    padding=12,
    fonts=None,
    exp_icon_path=None,
    background_color=(38,40,43),
    panel_color=(55,58,61),
    header_height=0,
    gradient=True,
    gradient_colors=None,
    gradient_direction=None,
    gradient_noise=True,
    gradient_seed=None,
    debug_save_path: str = None,
    rank_offset: int = -8   
) -> bytes:
    try:
        fonts = fonts or FONTS
        rows = list(rows or [])
        n = len(rows)

        print(f"[create_leaderboard_image] rows received: {n}")

        gap_between_rows = max(8, int(row_height * 0.2))
        height = padding*2 + header_height + n * (row_height + gap_between_rows)

        if gradient:
            bg_img = _random_gradient(
                (width, height),
                direction=gradient_direction,
                colors=gradient_colors,
                noise=gradient_noise,
                seed=gradient_seed
            )
            im = bg_img.convert("RGBA")
        else:
            im = Image.new("RGBA", (width, height), background_color)

        draw = ImageDraw.Draw(im)

        font_rank = _safe_load_font(fonts.get("bold"), max(12, int(row_height * 0.65)))
        font_name = _safe_load_font(fonts.get("bold"), max(12, int(row_height * 0.65)))
        font_medium = _safe_load_font(fonts.get("medium"), max(10, int(row_height * 0.45)))
        font_bold = _safe_load_font(fonts.get("bold"), max(11, int(row_height * 0.55)))

        font_rank_height = (font_rank.getbbox("Ay")[3] - font_rank.getbbox("Ay")[1])
        font_medium_height = (font_medium.getbbox("Ay")[3] - font_medium.getbbox("Ay")[1])
        font_bold_height = (font_bold.getbbox("Ay")[3] - font_bold.getbbox("Ay")[1])

        cjk_font_name = cjk_font_medium = cjk_font_bold = None
        if fonts.get("cjk"):
            try:
                cjk_font_name = _safe_load_font(fonts.get("cjk"), max(12, int(row_height * 0.65)))
                cjk_font_medium = _safe_load_font(fonts.get("cjk"), max(10, int(row_height * 0.45)))
                cjk_font_bold = _safe_load_font(fonts.get("cjk"), max(11, int(row_height * 0.55)))
            except Exception:
                cjk_font_name = cjk_font_medium = cjk_font_bold = None

        exp_icon = None
        if exp_icon_path and os.path.exists(exp_icon_path):
            try:
                icon_sz = max(12, int(row_height * 0.65))
                exp_icon = load_icon_cached(exp_icon_path, icon_sz)
            except Exception:
                exp_icon = None

        left_x = padding
        right_x = width - padding
        panel_radius = max(6, int(row_height * 0.25))
        start_y = padding + header_height

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
        except Exception:
            max_rank_val = 99
        rank_placeholder = "#999" if max_rank_val > 99 else "#99"
        max_rank_w = draw.textlength(rank_placeholder, font=font_rank)

        level_placeholder = "LVL 100"
        fixed_level_w = draw.textlength(level_placeholder, font=font_medium)

        max_total_exp_w = 0
        for r in rows:
            try:
                exp_text = "MAXED" if r.get("next_exp") is None else f"{int(r.get('exp',0)):,}/{int(r.get('next_exp',0)):,}"
            except Exception:
                exp_text = "0/0"
            w = draw.textlength(exp_text, font=font_bold)
            icon_gap = (exp_icon.width + 6) if exp_icon else 0
            total_w = w + icon_gap
            if total_w > max_total_exp_w:
                max_total_exp_w = total_w

        exp_center_x = right_x - extra_edge_margin - max_total_exp_w // 2

        badge_size = max(14, int(row_height * 0.75))
        right_reserved = (bullet_r*2 + 12) + fixed_level_w + 8 + badge_size + 8 + max_total_exp_w + extra_edge_margin
        left_reserved = left_x + avatar_x_offset + avatar_size + between_avatar_and_rank + max_rank_w + after_rank_gap + (bullet_r*2 + 12)
        name_area_width = int(right_x - right_reserved - left_reserved)
        if name_area_width < name_min_w:
            delta = name_min_w - name_area_width
            right_reserved = max(0, right_reserved - delta)
            name_area_width = int(right_x - right_reserved - left_reserved)
            if name_area_width < 40:
                name_area_width = 40

        column_shift = - 11  
        level_col_start = right_x - extra_edge_margin \
                          - max_total_exp_w - 8 \
                          - badge_size - 8 \
                          - fixed_level_w \
                          - (bullet_r*2 + 12)
        level_col_start += column_shift


        min_allowed = left_reserved + name_min_w + 16
        if level_col_start < min_allowed:
            level_col_start = min_allowed

        def draw_lb_cjk(draw_obj, pos, text, primary_font, cjk_font, fill, stroke_width=1, stroke_fill=(255,255,255,255)):
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
                        stroke_fill=stroke_fill
                    )
                else:
                    draw_obj.text((x0, y0), run_text, font=font_to_use, fill=fill)
                try:
                    w = draw_obj.textlength(run_text, font=font_to_use)
                except Exception:
                    w, _ = font_to_use.getsize(run_text)
                x0 += int(w)

        for i, r in enumerate(rows):
            try:
                rank_idx = int(r.get("rank", i+1))
            except Exception:
                rank_idx = i+1
            name_raw = (r.get("name") or "Unknown")
            try:
                level_val = int(r.get("level", 0))
            except Exception:
                level_val = 0
            try:
                exp_val = int(r.get("exp", 0) or 0)
            except Exception:
                exp_val = 0
            next_val = r.get("next_exp")
            try:
                next_val = None if next_val is None else int(next_val)
            except Exception:
                next_val = None

            y = start_y + i * (row_height + gap_between_rows)
            panel_w = width - padding*2
            panel_h = row_height
            panel_xy = (left_x, y, left_x + panel_w, y + panel_h)

            colors = None
            if rank_idx == 1:
                colors = [(255,223,0),(255,140,0)]
            elif rank_idx == 2:
                colors = [(220,220,220),(169,169,169)]
            elif rank_idx == 3:
                colors = [(205,127,50),(139,69,19)]

            if colors:
                grad_panel = get_panel_gradient(colors, (panel_w, panel_h), direction=gradient_direction or "horizontal")
                mask = Image.new("L", (panel_w, panel_h), 0)
                ImageDraw.Draw(mask).rounded_rectangle((0,0,panel_w,panel_h), radius=panel_radius, fill=255)
                im.paste(grad_panel, (left_x, y), mask)
            else:
                panel_fill = panel_color if i % 2 == 0 else tuple(max(0, c-6) for c in panel_color)
                draw.rounded_rectangle(panel_xy, radius=panel_radius, fill=panel_fill)

            av_x = left_x + avatar_x_offset
            center_y = y + panel_h // 2
            av_y = int(center_y - avatar_size / 2)
            try:
                avatar_bytes = r.get("avatar_bytes") or b""
                if avatar_bytes:
                    avatar = _load_avatar_cached(avatar_bytes, avatar_size)
                    if avatar is not None:
                        mask = Image.new("L", (avatar_size, avatar_size), 0)
                        ImageDraw.Draw(mask).ellipse((0,0,avatar_size,avatar_size), fill=255)
                        im.paste(avatar, (av_x, av_y), mask)
                    else:
                        raise Exception("avatar None")
                else:
                    raise Exception("no avatar")
            except Exception:
                draw.ellipse((av_x, av_y, av_x + avatar_size, av_y + avatar_size), fill=(100,100,100))

            rank_color = {1:(255,255,255),2:(255,255,255),3:(255,255,255)}.get(rank_idx,(200,200,200))
            rank_str = f"#{rank_idx}"
            rank_w = draw.textlength(rank_str, font=font_rank)
            rank_box_x = av_x + avatar_size + between_avatar_and_rank
            rx = int(rank_box_x + (max_rank_w - rank_w) / 2)
            r_h = font_rank_height
            ry = int(center_y - r_h/2) + rank_offset
            draw.text((rx, ry), rank_str, font=font_rank, fill=rank_color)

            bullet1_x = rank_box_x + max_rank_w + after_rank_gap
            bullet1_y = int(center_y - bullet_r + bullet_vertical_nudge)
            draw.ellipse((bullet1_x, bullet1_y, bullet1_x + bullet_r*2, bullet1_y + bullet_r*2), fill=(255,255,255))

            orig_name = str(name_raw or "Unknown")
            clean_name = strip_emojis(orig_name)
            nm = clean_name if clean_name else orig_name.strip()
            
            max_chars = 15
            if len(nm) > max_chars:
                nm = nm[:max_chars-3]+ "..."

            if draw.textlength(nm, font=font_name) > name_area_width: 
                nm = truncate_to_width(nm, font=font_name, max_width=name_area_width, draw=draw)

            name_start_x = bullet1_x + bullet_r*2 + 12
            draw_lb_cjk(draw, (name_start_x, ry), nm, font_name, cjk_font_name, (255,255,255))

            bullet2_x = int(level_col_start - bullet_spacing - bullet_r*2)
            bullet2_y = int(center_y - bullet_r + bullet_vertical_nudge) - 2
            draw.ellipse((bullet2_x, bullet2_y, bullet2_x + bullet_r*2, bullet2_y + bullet_r*2), fill=(255,255,255))

            lvl_x = int(level_col_start) + 2
            lvl_y = int(center_y - (font_medium_height) / 2) - 4
            level_text = f"LVL {level_val}"
            lvl_font = _safe_load_font(fonts.get("medium"), max(10, int(row_height * 0.50)))
            draw_lb_cjk(draw, (lvl_x, lvl_y), level_text, lvl_font, cjk_font_medium, (255,255,255))

            title_name = (r.get("title") or "").strip()
            badge_path = TITLE_EMOJI_FILES.get(title_name) if isinstance(TITLE_EMOJI_FILES, dict) else None
            badge_shift = 35
            if badge_path and os.path.exists(badge_path):
                try:
                    bx = lvl_x + fixed_level_w + badge_shift
                    by = int(center_y - badge_size/2)
                    badge_img = load_icon_cached(badge_path, badge_size)
                    if badge_img:
                        im.paste(badge_img, (int(bx), int(by)), badge_img)
                except Exception:
                    pass

            exp_text = "MAXED" if next_val is None else f"{format_number(exp_val)}/{format_number(next_val)}"
            exp_text_w = draw.textlength(exp_text, font=font_bold)
            icon_gap = (exp_icon.width + 6) if exp_icon else 0
            exp_block_w = exp_text_w + icon_gap
            exp_start = int(exp_center_x - exp_block_w // 2) + 12
            if exp_icon:
                try:
                    icon_y = int(center_y - exp_icon.height / 2)
                    im.paste(exp_icon, (int(exp_start), icon_y), exp_icon)
                    text_x = exp_start + exp_icon.width + 6
                except Exception:
                    text_x = exp_start
            else:
                text_x = exp_start
            t_h = font_bold_height
            text_y = int(center_y - t_h / 2) - 4
            draw_lb_cjk(draw, (text_x, text_y), exp_text, font_bold, cjk_font_bold, (255,255,255))

        out = io.BytesIO()
        im.save(out, format="PNG")
        out.seek(0)
        if debug_save_path:
            try:
                with open(debug_save_path, "wb") as fh:
                    fh.write(out.getvalue())
            except Exception:
                pass
        return out.getvalue()

    except Exception:
        traceback.print_exc()
        fallback = Image.new("RGBA", (4,4), (255,0,0,255))
        b = io.BytesIO()
        fallback.save(b, format="PNG")
        b.seek(0)
        return b.getvalue()


print("📦 Loaded utils.progUtils cog.")
