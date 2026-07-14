import random
from typing import Optional, Tuple
from bot.config.emojis import ShopEmojis, MinoriEmojis, CustomEmojis

# EXP IS CustomEmojis["EXP"]
# COINS IS ShopEmojis["Coins"]

WIN_TEMPLATES = [
    f"Correct! You earned +{{exp}} {CustomEmojis['EXP']} and +{{coins}} {ShopEmojis['Coins']}!",
    f"Nice work! Rewards: +{{exp}} {CustomEmojis['EXP']} | +{{coins}} {ShopEmojis['Coins']}",
    f"Correct answer! +{{exp}} {CustomEmojis['EXP']}, +{{coins}} {ShopEmojis['Coins']} gained.",
    f"Yatta! +{{exp}} {CustomEmojis['EXP']} EXP and +{{coins}} {ShopEmojis['Coins']} Coins! Keep it up!",
    f"Kyaa~! Rewards incoming! +{{exp}} {CustomEmojis['EXP']}, +{{coins}} {ShopEmojis['Coins']}!",
    f"Woohoo! Your efforts shine! +{{exp}} {CustomEmojis['EXP']} | +{{coins}} {ShopEmojis['Coins']}",
    f"Yosh! You’ve done it! +{{exp}} {CustomEmojis['EXP']} EXP and +{{coins}} {ShopEmojis['Coins']} Coins!",
    f"Otsukaresama! Your hard work paid off: +{{exp}} {CustomEmojis['EXP']} and +{{coins}} {ShopEmojis['Coins']}",
]

LOSE_TEMPLATES_NO_ANIME = [
    f"{MinoriEmojis['MinoriDissapointed']} Oops… {{name}} slipped away!",
    f"{MinoriEmojis['MinoriDissapointed']} Ahh! The answer was {{name}}…",
    f"{MinoriEmojis['MinoriConfused']} Huh?! The correct one was {{name}}!",
    f"{MinoriEmojis['MinoriDissapointed']} Not quite… {{name}} got past you!",
    f"{MinoriEmojis['MinoriConfused']} Eh?! You missed {{name}}!",
    f"{MinoriEmojis['MinoriDissapointed']} Whoops! {{name}} was the right one!",
    f"{MinoriEmojis['MinoriConfused']} Hmm… the answer was {{name}}.",
]

LOSE_TEMPLATES_WITH_ANIME = [
    f"{MinoriEmojis['MinoriDissapointed']} Oops… {{name}} from {{anime}} slipped away!",
    f"{MinoriEmojis['MinoriDissapointed']} Ahh! The answer was {{name}} from {{anime}}…",
    f"{MinoriEmojis['MinoriConfused']} Huh?! The correct one was {{name}} from {{anime}}!",
    f"{MinoriEmojis['MinoriDissapointed']} Not quite… {{name}} from {{anime}} got past you!",
    f"{MinoriEmojis['MinoriConfused']} Eh?! You missed {{name}} from {{anime}}!",
    f"{MinoriEmojis['MinoriDissapointed']} Whoops! {{name}} from {{anime}} was the right one!",
    f"{MinoriEmojis['MinoriConfused']} Hmm… the answer was {{name}} from {{anime}}.",
]


def random_win_message(exp: int, coins: int) -> str:
    return random.choice(WIN_TEMPLATES).format(exp=exp, coins=coins)


def random_lose_message(correct_name: str, anime_title: Optional[str] = None) -> str:
    if anime_title:
        return random.choice(LOSE_TEMPLATES_WITH_ANIME).format(
            name=correct_name, anime=anime_title
        )
    return random.choice(LOSE_TEMPLATES_NO_ANIME).format(name=correct_name)


def compute_rewards(
    level: int,
    exp_mul: Tuple[int, int] = (2, 3),
    exp_base: Tuple[int, int] = (5, 10),
    coin_range: Tuple[int, int] = (5, 20),
) -> Tuple[int, int]:
    exp_min = exp_base[0] + level * exp_mul[0]
    exp_max = exp_base[1] + level * exp_mul[1]
    exp_reward = random.randint(exp_min, exp_max)
    coins_reward = random.randint(*coin_range)
    return exp_reward, coins_reward


async def award_rewards(
    progression_cog, user_id: int, guild_id: int, exp: int, coins: int
):
    if not progression_cog:
        return None, None, False
    level, new_exp, leveled_up = await progression_cog.add_exp(user_id, guild_id, exp)
    await progression_cog.add_coins(user_id, guild_id, coins)
    return level, new_exp, leveled_up
