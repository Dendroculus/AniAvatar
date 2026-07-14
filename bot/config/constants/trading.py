"""Trading and shop domain constants."""


class TradingConstants:
    NOT_ENOUGH_COINS_MSG = "❌ You don't have enough coins, nothing purchased."
    SHOP_ICON_URL = "https://cdn.discordapp.com/emojis/1415555390489366680.png"
    MYSTERY_BOX_NAME = "Mystery Box"
    SMALL_EXP_POTION = "Small EXP Potion"
    MEDIUM_EXP_POTION = "Medium EXP Potion"
    LARGE_EXP_POTION = "Large EXP Potion"
    LEVEL_SKIP_TOKEN = "Level Skip Token"
    POTION_ITEMS = (
        SMALL_EXP_POTION,
        MEDIUM_EXP_POTION,
        LARGE_EXP_POTION,
        LEVEL_SKIP_TOKEN,
    )
    STMT_TIMEOUT_MS = 2000
    MAINTENANCE_INTERVAL = 6 * 60 * 60
    SQL_USER_INV_SELECT = (
        "SELECT item_name, quantity FROM user_inventory "
        "WHERE user_id = $1 AND guild_id = $2"
    )
    SQL_UPSERT_USER_INV = """
    INSERT INTO user_inventory (user_id, guild_id, item_name, quantity)
    VALUES ($1, $2, $3, $4)
    ON CONFLICT(user_id, guild_id, item_name)
    DO UPDATE SET quantity = user_inventory.quantity + EXCLUDED.quantity
    """
    SQL_SELECT_PRICE_EMOJI = "SELECT price, emoji FROM shop_items WHERE name = $1"
