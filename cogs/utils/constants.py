import os

COG_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # points to ...\AniAvatar\cogs
ROOT_PATH = os.path.dirname(COG_PATH)                                   # points to ...\AniAvatar

FONT_DIR = os.path.join(ROOT_PATH, "assets", "fonts")
EMOJI_PATH = os.path.join(ROOT_PATH, "assets", "RANK ICONS")
BG_PATH = os.path.join(ROOT_PATH, "assets", "background")  # singular

FONTS = {
    "bold": os.path.join(FONT_DIR, "gg sans Bold.ttf"),
    "medium": os.path.join(FONT_DIR, "gg sans Medium.ttf"),
    "regular": os.path.join(FONT_DIR, "gg sans Regular.ttf"),
    "semibold": os.path.join(FONT_DIR, "gg sans Semibold.ttf"),
    "cjk": os.path.join(FONT_DIR, "NotoSerifCJK.ttc"),
}

TITLE_EMOJI_FILES = {
    "Novice": os.path.join(EMOJI_PATH, "NOVICE.png"),
    "Warrior": os.path.join(EMOJI_PATH, "WARRIOR.png"),
    "Elite": os.path.join(EMOJI_PATH, "ELITE.png"),
    "Champion": os.path.join(EMOJI_PATH, "CHAMPION.png"),
    "Hero": os.path.join(EMOJI_PATH, "HERO.png"),
    "Legend": os.path.join(EMOJI_PATH, "LEGEND.png"),
    "Mythic": os.path.join(EMOJI_PATH, "MYTHIC.png"),
    "Ascendant": os.path.join(EMOJI_PATH, "ASCENDANT.png"),
    "Immortal": os.path.join(EMOJI_PATH, "IMMORTAL.png"),
    "Celestial": os.path.join(EMOJI_PATH, "CELESTIAL.png"),
    "Transcendent": os.path.join(EMOJI_PATH, "TRANSCENDENT.png"),
    "Aetherborn": os.path.join(EMOJI_PATH, "AETHERBORN.png"),  
    "Cosmic": os.path.join(EMOJI_PATH, "COSMIC.png"),
    "Divine": os.path.join(EMOJI_PATH, "DIVINE.png"),
    "Eternal": os.path.join(EMOJI_PATH, "ETERNAL.png"),
    "Enlightened": os.path.join(EMOJI_PATH, "ENLIGHTENED.png"),
}

print("📦 Loaded utils.constants cog.")