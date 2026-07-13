"""Pure progression level and title rules."""

from bot.config.constants.profile import ProfileCardConstants as PCC
from bot.config.emojis import TitleEmojis


def get_title(level: int) -> str:
    """
    Map a numeric level to a human-friendly title string.
    Args:
        level (int): The user's level.
    Returns:
        str: The corresponding title.
    """
    for threshold, title in PCC._TITLE_THRESHOLDS:
        if level < threshold:
            return title
    return "Enlightened"


def get_title_emoji(level: int):
    """
    Return a compact emoji token representing the title tier.
    Args:
        level (int): The user's level.
    Returns:
        str: The corresponding emoji.
    """
    title_key = get_title(level).upper()
    return TitleEmojis.get(title_key, TitleEmojis["NOVICE"])


def required_exp(level: int) -> int:
    """Return the EXP required to advance from level."""
    if level < 1:
        raise ValueError("level must be at least 1")
    return 50 * level + 20 * level**2
