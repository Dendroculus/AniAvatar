import random
from typing import Optional, Tuple

WIN_TEMPLATES = [
    "Correct! You earned +{exp} <:EXP:1415642038589984839> and +{coins} <:Coins:1415353285270966403>!",
    "Nice work! Rewards: +{exp} <:EXP:1415642038589984839> | +{coins} <:Coins:1415353285270966403>",
    "Correct answer! +{exp} <:EXP:1415642038589984839>, +{coins} <:Coins:1415353285270966403> gained.",
    "Yatta! +{exp} <:EXP:1415642038589984839> EXP and +{coins} <:Coins:1415353285270966403> Coins! Keep it up!",
    "Kyaa~! Rewards incoming! +{exp} <:EXP:1415642038589984839>, +{coins} <:Coins:1415353285270966403>!",
    "Woohoo! Your efforts shine! +{exp} <:EXP:1415642038589984839> | +{coins} <:Coins:1415353285270966403>",
    "Yosh! You’ve done it! +{exp} <:EXP:1415642038589984839> EXP and +{coins} <:Coins:1415353285270966403> Coins!",
    "Otsukaresama! Your hard work paid off: +{exp} <:EXP:1415642038589984839> and +{coins} <:Coins:1415353285270966403>!",
]

LOSE_TEMPLATES_NO_ANIME = [
    "<:MinoriDissapointed:1416016691430821958> Oops… {name} slipped away!",
    "<:MinoriDissapointed:1416016691430821958> Ahh! The answer was {name}…",
    "<:MinoriConfused:1415707082988060874> Huh?! The correct one was {name}!",
    "<:MinoriDissapointed:1416016691430821958> Not quite… {name} got past you!",
    "<:MinoriConfused:1415707082988060874> Eh?! You missed {name}!",
    "<:MinoriDissapointed:1416016691430821958> Whoops! {name} was the right one!",
    "<:MinoriConfused:1415707082988060874> Hmm… the answer was {name}.",
]

LOSE_TEMPLATES_WITH_ANIME = [
    "<:MinoriDissapointed:1416016691430821958> Oops… {name} from {anime} slipped away!",
    "<:MinoriDissapointed:1416016691430821958> Ahh! The answer was {name} from {anime}…",
    "<:MinoriConfused:1415707082988060874> Huh?! The correct one was {name} from {anime}!",
    "<:MinoriDissapointed:1416016691430821958> Not quite… {name} from {anime} got past you!",
    "<:MinoriConfused:1415707082988060874> Eh?! You missed {name} from {anime}!",
    "<:MinoriDissapointed:1416016691430821958> Whoops! {name} from {anime} was the right one!",
    "<:MinoriConfused:1415707082988060874> Hmm… the answer was {name} from {anime}.",
]

def random_win_message(exp: int, coins: int) -> str:
    return random.choice(WIN_TEMPLATES).format(exp=exp, coins=coins)

def random_lose_message(correct_name: str, anime_title: Optional[str] = None) -> str:
    if anime_title:
        return random.choice(LOSE_TEMPLATES_WITH_ANIME).format(name=correct_name, anime=anime_title)
    return random.choice(LOSE_TEMPLATES_NO_ANIME).format(name=correct_name)

def compute_rewards(level: int, exp_mul: Tuple[int, int] = (2, 3), exp_base: Tuple[int, int] = (5, 10), coin_range: Tuple[int, int] = (5, 20)) -> Tuple[int, int]:
    exp_min = exp_base[0] + level * exp_mul[0]
    exp_max = exp_base[1] + level * exp_mul[1]
    exp_reward = random.randint(exp_min, exp_max)
    coins_reward = random.randint(*coin_range)
    return exp_reward, coins_reward

async def award_rewards(progression_cog, user_id: int, guild_id: int, exp: int, coins: int):
    if not progression_cog:
        return None, None, False
    level, new_exp, leveled_up = await progression_cog.add_exp(user_id, guild_id, exp)
    await progression_cog.add_coins(user_id, guild_id, coins)
    return level, new_exp, leveled_up