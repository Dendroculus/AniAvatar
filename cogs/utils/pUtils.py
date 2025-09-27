from PIL import Image, ImageDraw, ImageFont
from cogs.utils.constants import *
import traceback
import discord
import os
import io


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
) -> bytes:
    try:
        def _load_font(path, size):
            try:
                return ImageFont.truetype(path, size)
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
            # Create vertical purple gradient
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
        
        font_username = _load_font(fonts["bold"], 32.5)
        font_medium = _load_font(fonts["medium"], 25.5)
        font_small = _load_font(fonts["regular"], 21.5)

        width, height = 600, 260
        corner_radius = 40

        img = Image.new("RGBA", (width, height), (0,0,0,0))
        mask = Image.new("L", (width, height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([0,0,width,height], radius=corner_radius, fill=255)

        # Background selection
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

        def draw_text(pos, text, font, fill, small=False, stroke_width=2, stroke_fill=(0,0,0,255)):
            if small:
                draw.text((pos[0]+1, pos[1]+1), text, font=font, fill=(0,0,0,100))
                draw.text(pos, text, font=font, fill=fill)
            else:
                draw.text((pos[0]+2, pos[1]+2), text, font=font, fill=(0,0,0,180))
                draw.text(
                    pos,
                    text,
                    font=font,
                    fill=fill,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_fill
                )


        draw_text((x, y), display_name, font_username, font_color, small=True)
        y += 40

        labels = ["Title ", "Level ", "EXP "]
        values = [
            title_name,
            str(level),
            f"{exp:,} / {next_exp:,}" if next_exp else "∞"
        ]

        label_width = max(draw.textlength(lbl, font=font_medium) for lbl in labels)

        for label, value in zip(labels, values):
            draw_text((x, y), label, font_medium, font_color)
            colon_x = x + label_width + 8
            draw_text((colon_x, y), ":", font_medium, font_color)
            value_x = colon_x + 12
            draw_text((value_x, y), value, font_medium, font_color)

            if label.strip() == "Title":
                emoji_path = title_emoji_files.get(title_name)
                if emoji_path and os.path.exists(emoji_path):
                    try:
                        badge = Image.open(emoji_path).convert("RGBA").resize((51, 46))
                        bx = int(value_x + draw.textlength(value, font=font_medium) + 10)
                        bbox = font_medium.getbbox(value)
                        text_height = bbox[3] - bbox[1]
                        by = int(y + text_height / 2 - badge.height / 2 + 7)
                        img.paste(badge, (bx, by), badge)
                    except:
                        pass
            y += 32

        if next_exp is not None:
            next_line = f"Gain {max(0, next_exp - exp):,} more EXP to level up!"
        else:
            next_line = "You are at max level!"
        draw_text(
                (x, y),
                next_line,
                font_small,
                (255,255,255),           
                stroke_width=3.15,          
                stroke_fill=(0,0,0,255)  
            )
        y += 40

        # === EXP Bar ===
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
                r = int(0 + (80 - 0) * (i / progress_width))
                g = int(180 + (255 - 180) * (i / progress_width))
                b = int(120 + (60 - 120) * (i / progress_width))
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

def load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception as e:
        print(f"Font load failed for {path}: {e}")
        return ImageFont.load_default()
    
def _safe_load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

def create_leaderboard_image(
    rows,
    width: int = 820,
    row_height: int = 96,
    padding: int = 12,
    fonts: dict = None,
    exp_icon_path: str = None,
    background_color=(38,40,43),
    panel_color=(55,58,61),
    header_height: int = 0
):
    fonts = fonts or FONTS
    rows = list(rows)
    n = len(rows)

    height = padding * 2 + header_height + (n * (row_height + 10))
    im = Image.new("RGBA", (width, height), background_color)
    draw = ImageDraw.Draw(im)

    # fonts (kept)
    font_bold = _safe_load_font(fonts.get("bold"), 30)
    font_medium = _safe_load_font(fonts.get("medium"), 24)
    font_small = _safe_load_font(fonts.get("regular"), 20)
    font_rank = _safe_load_font(fonts.get("bold"), 36)

    # EXP icon (optional)
    exp_icon = None
    if exp_icon_path and os.path.exists(exp_icon_path):
        try:
            exp_icon = Image.open(exp_icon_path).convert("RGBA").resize((32,32), Image.Resampling.LANCZOS)
        except:
            exp_icon = None

    left_x = padding
    right_x = width - padding
    panel_radius = 12

    header_y = padding
    start_y = header_y + header_height

    if header_height > 0:
        draw.rounded_rectangle((left_x, header_y, width - left_x, header_y + header_height - 8),
                               radius=12, fill=tuple(max(0, c - 8) for c in panel_color))


    fixed_name_width = 288   
    badge_size = 60         
    extra_edge_margin = 60   
    bullet2_extra = 5       
    title_gap = 12           
    bullet_vertical_nudge = 7
    min_badge_shrink = 20   

    max_rank_w = 0
    for r in rows:
        rank_test = f"#{int(r.get('rank', 0))}"
        w = draw.textlength(rank_test, font=font_rank)
        if w > max_rank_w:
            max_rank_w = w

    max_total_exp_w = 0
    for r in rows:
        exp_text_test = "MAX" if r.get("next_exp") is None else f"{r.get('exp',0):,}/{r.get('next_exp',0):,}"
        exp_w = draw.textlength(exp_text_test, font=font_bold)
        icon_gap = (exp_icon.width + 8) if exp_icon else 0
        total_w = exp_w + icon_gap
        if total_w > max_total_exp_w:
            max_total_exp_w = total_w

    exp_center_x = right_x - extra_edge_margin - (max_total_exp_w // 2)

    for i, r in enumerate(rows):
        y = start_y + i * (row_height + 10)
        panel_w = width - padding * 2
        panel_h = row_height
        panel_xy = (left_x, y, left_x + panel_w, y + panel_h)
        panel_fill = panel_color if i % 2 == 0 else tuple(max(0, c - 6) for c in panel_color)
        draw.rounded_rectangle(panel_xy, radius=panel_radius, fill=panel_fill)

        avatar_size = panel_h - 22
        av_x = left_x + 14
        center_y = y + panel_h // 2
        av_y = int(center_y - avatar_size / 2)
        try:
            avatar_bytes = r.get("avatar_bytes") or b""
            if avatar_bytes:
                avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
                mask = Image.new("L", (avatar_size, avatar_size), 0)
                ImageDraw.Draw(mask).ellipse((0,0,avatar_size,avatar_size), fill=255)
                im.paste(avatar, (av_x, av_y), mask)
            else:
                raise Exception("no avatar bytes")
        except Exception:
            draw.ellipse((av_x, av_y, av_x + avatar_size, av_y + avatar_size), fill=(100,100,100))

        rank_idx = int(r.get("rank", 0))
        if rank_idx == 1:
            rank_color = (255,215,0)
        elif rank_idx == 2:
            rank_color = (192,192,192)
        elif rank_idx == 3:
            rank_color = (205,127,50)
        else:
            rank_color = (200,200,200)

        rank_str = f"#{rank_idx}"
        rbbox = font_rank.getbbox(rank_str)
        r_h = rbbox[3] - rbbox[1]
        rx = av_x + avatar_size + 14
        ry = int(center_y - r_h / 2)
        draw.text((rx, ry), rank_str, font=font_rank, fill=rank_color)

        rank_w_actual = draw.textlength(rank_str, font=font_rank)
        bullet_r = 4
        bullet1_x = rx + rank_w_actual + 18
        bullet1_y = int(center_y - bullet_r + bullet_vertical_nudge)
        draw.ellipse((bullet1_x, bullet1_y, bullet1_x + bullet_r*2, bullet1_y + bullet_r*2), fill=(150,150,150))

        name_start_x = av_x + avatar_size + 14 + max_rank_w + 18 + (bullet_r*2) + 12
        nx = name_start_x

        name = r.get("name", "Unknown") or "Unknown"
        if len(name) > 15:
            nm = name[:13] + ".."
        else:
            nm = name

        nbbox = font_bold.getbbox(nm)
        n_h = nbbox[3] - nbbox[1]
        ny = int(center_y - n_h / 2)
        draw.text((nx, ny), nm, font=font_bold, fill=(255,255,255))

        bullet2_x = nx + fixed_name_width + bullet2_extra
        bullet2_y = int(center_y - bullet_r + bullet_vertical_nudge)
        draw.ellipse((bullet2_x, bullet2_y, bullet2_x + bullet_r*2, bullet2_y + bullet_r*2), fill=(150,150,150))

        level_text = f"LVL {r.get('level')}"
        lbbox = font_medium.getbbox(level_text)
        l_h = lbbox[3] - lbbox[1]
        lvl_x = bullet2_x + bullet_r*2 + 12
        lvl_y = int(center_y - l_h / 2)
        draw.text((lvl_x, lvl_y), level_text, font=font_medium, fill=(180,180,180))


        level_placeholder = "LVL 100" 
        fixed_level_w = draw.textlength(level_placeholder, font=font_medium)

        title_name = (r.get("title") or "").strip()
        badge_path = TITLE_EMOJI_FILES.get(title_name)
        badge_right_x = None
        if badge_path and os.path.exists(badge_path):
            try:
                initial_bx = int(lvl_x + fixed_level_w + 8)

                exp_block_start = int(exp_center_x - (max_total_exp_w // 2))
                space_right = exp_block_start - initial_bx - 12

                badge_draw_size = badge_size
                bx = initial_bx
                if space_right >= badge_size:
                    badge_draw_size = badge_size
                    bx = initial_bx
                elif space_right >= 24:
                    badge_draw_size = max(min_badge_shrink, int(space_right))
                    bx = initial_bx
                else:
                    badge_draw_size = min(badge_size, max(min_badge_shrink, int(badge_size * 0.6)))
                    bx_candidate = int(lvl_x - badge_draw_size - 12)
                    min_left = int(nx + draw.textlength(nm, font=font_bold) + 8)
                    bx = max(min_left, bx_candidate)

                badge_img = Image.open(badge_path).convert("RGBA")
                badge_img = badge_img.resize((int(badge_draw_size), int(badge_draw_size)), Image.Resampling.LANCZOS)
                by = int(center_y - badge_draw_size / 2 + 6)
                im.paste(badge_img, (int(bx), int(by)), badge_img)
                badge_right_x = int(bx + badge_draw_size)
            except Exception:
                badge_right_x = None

        exp_text = "MAX" if r.get("next_exp") is None else f"{r.get('exp', 0):,}/{r.get('next_exp', 0):,}"
        exp_w = draw.textlength(exp_text, font=font_bold)
        icon_gap = (exp_icon.width + 8) if exp_icon else 0
        total_w = exp_w + icon_gap
        start_x = int(exp_center_x - total_w / 2 + 10)

        if badge_right_x is not None:
            min_start = badge_right_x + 8
            if start_x < min_start:
                shift_left = (min_start - start_x)
                new_bx = int((badge_right_x - (badge_right_x - bx)) - shift_left)
                min_bx = int(lvl_x + draw.textlength(level_text, font=font_medium) + 6)
                if new_bx < min_bx:
                    new_bx = min_bx
                try:
                    badge_img2 = Image.open(badge_path).convert("RGBA")
                    bsize = int(min(badge_size, max(min_badge_shrink, badge_img2.size[0] * 0.6)))
                    badge_img2 = badge_img2.resize((bsize, bsize), Image.Resampling.LANCZOS)
                    im.paste(badge_img2, (int(new_bx), int(center_y - bsize/2 + 6)), badge_img2)
                    badge_right_x = int(new_bx + bsize)
                except Exception:
                    pass

        if exp_icon:
            icon_y = int(center_y - exp_icon.height / 2)
            im.paste(exp_icon, (int(start_x), icon_y), exp_icon)
            text_x = start_x + exp_icon.width + 8
        else:
            text_x = start_x

        tbbox = font_bold.getbbox("Ay")
        t_h = tbbox[3] - tbbox[1]
        text_y = int(center_y - t_h / 2)
        draw.text((text_x, text_y), exp_text, font=font_bold, fill=(255,255,255))

    out = io.BytesIO()
    im.save(out, format="PNG")
    out.seek(0)
    return out.getvalue()