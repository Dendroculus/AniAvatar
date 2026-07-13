"""Text normalization and measurement helpers for image rendering."""

from __future__ import annotations

import unicodedata

from bot.config.constants.profile import ProfileCardConstants as PCC


def format_number(num: int) -> str:
    """Format a large integer into a short human-friendly string."""
    if num < 1_000:
        return str(num)
    elif num < 1_000_000:
        return f"{num / 1_000:.2f}K".rstrip("0").rstrip(".")
    elif num < 1_000_000_000:
        return f"{num / 1_000_000:.2f}M".rstrip("0").rstrip(".")
    else:
        return f"{num / 1_000_000_000:.2f}B".rstrip("0").rstrip(".")


def strip_emojis(s: str) -> str:
    """Remove invisible joiner/variation characters and pictographic emoji runs."""
    if not s:
        return s
    s = PCC._INVISIBLE_RE.sub("", s)
    out_chars = []
    for ch in s:
        cat = unicodedata.category(ch)
        if cat.startswith("So") or cat.startswith("Sk"):
            continue
        out_chars.append(ch)
    s = "".join(out_chars)
    s = PCC._CTRL_RE.sub("", s)
    s = PCC._space_collapse_re.sub(" ", s).strip()
    return s


def is_cjk_char(ch: str) -> bool:
    """Return True when the given character is in a CJK (or related) Unicode block."""
    if not ch:
        return False
    try:
        cp = ord(ch)
    except TypeError:
        return False
    if 0x4E00 <= cp <= 0x9FFF:
        return True
    if 0x3400 <= cp <= 0x4DBF:
        return True
    if 0x20000 <= cp <= 0x2CEAF:
        return True
    if 0xF900 <= cp <= 0xFAFF:
        return True
    if 0x2F800 <= cp <= 0x2FA1F:
        return True
    if 0xAC00 <= cp <= 0xD7AF:
        return True
    if 0x3040 <= cp <= 0x30FF:
        return True
    return False


def split_into_runs(text: str):
    """Split text into consecutive runs of CJK vs non-CJK characters."""
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


def truncate_to_width(text, font, max_w, draw):
    """Truncate a string by binary-searching the maximum prefix that fits within max_w."""
    if draw.textlength(text, font=font) <= max_w:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        if draw.textlength(text[:mid] + ". .", font=font) <= max_w:
            lo = mid + 1
        else:
            hi = mid
    return text[: max(0, lo - 1)] + ". ."
