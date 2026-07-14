"""Profile title rules and Discord presentation constants."""

import re
import discord


class ProfileCardConstants:
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
    _INVISIBLE_RE = re.compile(
        r"[\u200D\uFE0F\u200E\u200F\u2060-\u2064\uFEFF]",
        flags=re.UNICODE,
    )
    _CTRL_RE = re.compile(r"[\x00-\x1F\x7F]", flags=re.UNICODE)
    _space_collapse_re = re.compile(r"\s+", flags=re.UNICODE)
    _TITLE_THRESHOLDS = [
        (5, "Novice"),
        (10, "Warrior"),
        (15, "Elite"),
        (20, "Champion"),
        (25, "Hero"),
        (30, "Legend"),
        (35, "Mythic"),
        (40, "Ascendant"),
        (50, "Immortal"),
        (60, "Celestial"),
        (70, "Transcendent"),
        (80, "Aetherborn"),
        (90, "Cosmic"),
        (100, "Divine"),
        (125, "Eternal"),
    ]
