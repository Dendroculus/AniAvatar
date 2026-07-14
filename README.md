<div align="center">

  EN | [中文](docs/readmeCN.md)
</div>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white" alt="discord.py 2.x">
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/Redis-Optional-DC382D?logo=redis&logoColor=white" alt="Redis">
  <img src="https://img.shields.io/badge/Playwright-Pinterest-2EAD33?logo=playwright&logoColor=white" alt="Playwright">
</p>

<p align="center" style="margin-top: -12px;">
  <img src="https://img.shields.io/badge/License-MIT-22C55E?logo=opensourceinitiative&logoColor=white" alt="MIT License">
  <img src="https://img.shields.io/badge/Status-Active-22C55E" alt="Active">
</p>

<div align="center">

# 🌸 AniAvatar

### A feature-oriented Discord bot for anime discovery, progression, games, and community interaction

</div>

## 🚀 Why AniAvatar

**AniAvatar**, appearing on Discord as **Minori**, started as an anime profile-picture search bot and grew into a complete community platform.

It combines intelligent anime image discovery with persistent progression, rendered profile cards, server economies, interactive games, polls, and moderation utilities. The codebase is organized around feature ownership so Discord commands remain thin while repositories, workflows, views, rendering, and external integrations stay independently maintainable.

- 🔍 Smart anime image search with Pinterest and Google fallback
- 🧠 User-aware history that reduces repeated image results
- 📈 Persistent EXP, levels, coins, title roles, and leaderboards
- 🎮 Discord-native games with isolated interaction state
- 🛍️ Shop, inventory, consumables, and item donation
- ⚙️ Feature-oriented architecture with async repositories and services
- 🛡️ Timeouts, cooldowns, rate limits, fallback providers, and recovery paths

## 🎯 Features

### A) Anime Discovery

1. 🔍 **Smart PFP Search** — Search for high-quality anime profile pictures by character name.
2. 📌 **Pinterest Worker** — Uses Playwright to collect image candidates and resolve higher-resolution Pinterest assets.
3. 🌐 **Google Fallback** — Falls back to Google Custom Search when Pinterest cannot provide enough usable results.
4. 🧠 **User-Aware Results** — Tracks previously served images so repeated searches remain fresh.
5. 🧹 **Deduplication & Validation** — Filters duplicate, unreachable, and unsuitable image URLs.
6. 📚 **Anime Metadata** — Retrieves anime information through AniList.

<details>
  <summary><b>View anime discovery previews</b></summary>
  <br>
  <img src="docs/screenshots/anime_result.png" width="600" alt="Anime search result">
</details>

### B) Progression & Economy

1. ⭐ **EXP and Leveling** — Members earn experience through messages and supported games.
2. 📢 **Level-Up Feedback** — Announces level progression and rewards.
3. 🏷️ **Automatic Title Roles** — Creates and synchronizes progression roles from Novice through Enlightened.
4. 🪪 **Profile Cards** — Renders rank, title, level, EXP, and customizable backgrounds.
5. 🏆 **Server Leaderboards** — Generates visual leaderboard images for the top members.
6. 🪙 **Coin Economy** — Stores persistent balances alongside progression data.
7. 🛒 **Shop and Inventory** — Buy consumables, inspect owned items, and apply item effects.
8. 🎁 **Item Donation** — Transfer supported inventory items to another server member.

<details>
  <summary><b>View progression previews</b></summary>
  <br>
  <img src="docs/screenshots/levelup_msg.png" width="600" alt="Level-up message">
  <img src="docs/screenshots/profilecards_command.png" width="600" alt="Profile card">
  <img src="docs/screenshots/leaderboard_command.png" width="600" alt="Leaderboard">
  <img src="docs/screenshots/shop&inventory_command.png" width="600" alt="Shop and inventory">
</details>

### C) Games & Community

1. 🧩 **Anime Trivia** — Run multiple-choice quizzes with balanced question selection.
2. 🖼️ **Guess the Character** — Identify a character from an image and earn rewards.
3. 🎲 **Coin Gambling** — Play an interactive risk-and-reward coin game.
4. 💬 **Anime Quotes** — Receive randomized quotes while reducing immediate repeats.
5. 🌸 **Waifu Images** — Fetch random SFW images through `waifu.im`.
6. 📊 **Persistent Polls** — Create timed polls with custom options, vote tracking, recovery, and result presentation.
7. 📣 **Announcements** — Let administrators compose formatted server announcements through a modal.
8. 🧭 **Dynamic Help** — Browse the available commands from Discord.

<details>
  <summary><b>View games and community previews</b></summary>
  <br>
  <img src="docs/screenshots/animequiz_command.png" width="600" alt="Anime quiz">
  <img src="docs/screenshots/guess_character.png" width="600" alt="Guess the character">
  <img src="docs/screenshots/gamble_command.png" width="600" alt="Gambling game">
  <img src="docs/screenshots/announce_command.png" width="600" alt="Announcement modal">
  <img src="docs/screenshots/help_command.png" width="600" alt="Help command">
</details>

## 🧠 Architecture Highlights

AniAvatar uses a feature-oriented architecture that separates Discord integration from business logic and shared infrastructure.

- **Thin Discord cogs** handle command registration, validation, and response orchestration.
- **Feature packages** own their workflows, views, repositories, domain models, and external integrations.
- **Core packages** contain infrastructure shared across multiple features.
- **PostgreSQL repositories** persist progression, economy, trading, polling, and search state.
- **Redis is optional** and accelerates selected progression and leaderboard operations.
- **Process-pool rendering** keeps profile and leaderboard image generation away from the Discord event loop.
- **Dedicated Discord views** isolate interaction state for concurrent games, shops, inventories, donations, and polls.
- **External API clients** use timeouts, validation, provider fallback, and user-facing error handling.
- **Recovery workflows** restore active poll state after restarts.

## 🔄 Main Runtime Flows

### Anime PFP Search

1. A member submits a character name.
2. The search engine checks cached and previously served results.
3. Pinterest is queried through a rate-limited Playwright worker.
4. Google Custom Search provides fallback candidates when configured.
5. Results are normalized, validated, and deduplicated.
6. New images are returned and recorded for that member.

### Progression and Rewards

1. A supported message or game action produces EXP or coin rewards.
2. The progression workflow validates and persists the update.
3. Level changes trigger role synchronization and feedback.
4. Profile and leaderboard requests are rendered outside the event loop.
5. Optional Redis caching reduces repeated work.

## 🏗️ Project Structure

```text
AniAvatar/
├── bot/
│   ├── cogs/                       # Discord extension entrypoints
│   ├── config/                     # Settings, paths, assets, emojis, constants
│   ├── core/
│   │   ├── discord/                # Shared Discord helpers
│   │   ├── logging_config/         # Structured application logging
│   │   ├── rendering/              # Shared render management
│   │   └── repositories/           # Cross-feature repositories
│   └── features/
│       ├── administration/         # Announcement components
│       ├── anime/                  # AniList, Jikan, and quiz helpers
│       ├── animepfp/               # Smart image search engine
│       ├── fun/                    # Quotes, gambling, responses, waifu client
│       ├── games/                  # Trivia and character-guess workflows
│       ├── polling/                # Poll domain, persistence, recovery, and UI
│       ├── progression/            # EXP, profiles, leaderboards, rendering
│       ├── roles/                  # Progression-role synchronization
│       └── trading/                # Shop, inventory, donation, item effects
├── data/                           # Trivia, quote, and application data
├── docs/                           # Screenshots and translated documentation
├── tests/
│   └── manual/                     # External API connectivity checks
├── main.py                         # Bot entrypoint and shared resources
└── requirements.txt
```

## 🤖 Commands

| Command | Category | Description |
| :--- | :--- | :--- |
| `/animepfp <name> [count]` | Search | Fetch up to five unique anime profile pictures for a character. |
| `/anime <query>` | Search | Retrieve anime information from AniList. |
| `/profile [user]` | Progression | Display your profile card or another member's card. |
| `/leaderboard` | Progression | Render the server's top members by EXP. |
| `/profiletheme` | Progression | Select a custom profile-card theme and background. |
| `/resetprofiletheme` | Progression | Restore the default profile-card theme. |
| `/shop` | Trading | Open the item shop and purchase consumables. |
| `/inventory` | Trading | Inspect your inventory and use supported items. |
| `/donate <member>` | Trading | Donate an inventory item to another member. |
| `/animequiz <questions>` | Games | Start a multiple-choice anime trivia session. |
| `/guesscharacter` | Games | Guess a character from an image. |
| `/gamble` | Fun | Gamble coins through an interactive Discord view. |
| `/waifu` | Fun | Fetch a random SFW image from `waifu.im`. |
| `/animequotes` | Fun | Display a random anime quote. |
| `/poll <duration>` | Community | Create a timed poll through a Discord modal. |
| `/announce <mention> <channel>` | Admin | Compose and send a server announcement. |
| `/help` | General | Display the available commands. |
| `/ping` | General | Check the bot's Discord latency. |

Most user-facing commands are hybrid commands and can also be invoked through the configured `!` prefix.

## 🏗️ Architecture & Stack

- **Discord Application — `discord.py`**  
  Handles slash commands, prefix commands, modals, selects, buttons, cooldowns, listeners, and persistent interaction flows.

- **Database — PostgreSQL + `asyncpg`**  
  Stores user progression, economy state, trading data, polls, search history, and image-cache metadata.

- **Optional Cache — Redis**  
  Supports selected progression and leaderboard caching while remaining optional for local development.

- **Anime Search — Playwright + Google Custom Search**  
  Uses Pinterest as the primary visual source and Google as an optional fallback.

- **Rendering — Pillow + process workers**  
  Generates profile cards and leaderboards without blocking the Discord event loop.

- **External APIs — AniList, Jikan, and `waifu.im`**  
  Supply anime metadata, character data, quiz options, and SFW images.

- **Networking — `aiohttp`**  
  Provides one shared asynchronous HTTP session for external integrations.

## ⚙️ Environment Variables

Create a `.env` file in the project root:

```env
# Required
DISCORD_TOKEN=your_discord_bot_token
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/aniavatar

# Optional: owner-only development commands
OWNER_ID=your_discord_user_id

# Optional: Google fallback for /animepfp
GOOGLE_API_KEY=your_google_api_key
SEARCH_ENGINE_ID=your_google_custom_search_engine_id

# Optional: progression and leaderboard cache
REDIS_URL=redis://localhost:6379/0

# Optional: PostgreSQL statement timeout
PG_STATEMENT_TIMEOUT_MS=2000

# Optional: external or mounted asset directory
ASSET_ROOT=
```

`DISCORD_TOKEN` and `DATABASE_URL` are required at runtime. Google credentials, Redis, and the owner ID are optional. The bot initializes its required PostgreSQL schemas when the relevant extensions load.

## 🚀 Local Development

### 1) Clone the repository

```bash
git clone https://github.com/Dendroculus/AniAvatar.git
cd AniAvatar
```

### 2) Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

### 3) Install dependencies

```bash
pip install -r requirements.txt
```

The Pinterest worker imports Playwright, which is not currently pinned in `requirements.txt`. Install it and its Chromium runtime separately:

```bash
pip install playwright
playwright install chromium
```

### 4) Configure PostgreSQL

Create a PostgreSQL database and assign its connection string to `DATABASE_URL`.

Redis is optional. Without `REDIS_URL`, AniAvatar continues using PostgreSQL and in-process behavior for supported workflows.

### 5) Configure the Discord application

In the Discord Developer Portal:

1. Create an application and bot.
2. Enable the **Server Members Intent**.
3. Enable the **Message Content Intent**.
4. Invite the bot with the permissions needed by the commands you plan to use.
5. Add the bot token to `.env`.

### 6) Run the bot

```bash
python main.py
```

On startup, AniAvatar:

1. Initializes the shared `aiohttp` session.
2. Creates the PostgreSQL connection pool.
3. Loads the Discord cogs.
4. Initializes feature schemas and services.
5. Synchronizes application commands.

## 🔒 Reliability Notes

- Secrets are loaded from environment variables and should never be committed.
- External API calls use shared asynchronous networking and explicit timeout handling.
- The character providers use fallback behavior between AniList and Jikan.
- The waifu client validates HTTP status, JSON structure, session availability, and image presence.
- Search workers use rate limiting and result validation.
- Interactive games and trading views validate the original user before accepting actions.
- Cooldowns protect resource-heavy and economy-related commands.
- Admin and owner-only commands apply explicit permission checks.
- PostgreSQL statement timeouts can be configured through `PG_STATEMENT_TIMEOUT_MS`.

## 🤝 Contributing

Issues, pull requests, and focused improvements are welcome.

For larger changes, open an issue first to align on scope. Keep feature-specific logic inside its owning package and avoid adding new generic utility modules when a clear feature or core owner exists.

Before submitting changes:

```bash
ruff format .
ruff check .
python -m compileall -q bot main.py
```

## 📜 License

Licensed under the MIT License. See [LICENSE](LICENSE) for details.

## 🙏 Acknowledgements

- [discord.py](https://github.com/Rapptz/discord.py)
- [AniList](https://anilist.co/)
- [Jikan](https://jikan.moe/)
- [waifu.im](https://waifu.im/)
- [Playwright](https://playwright.dev/python/)
- [Noto Fonts](https://github.com/notofonts/noto-cjk/releases) for CJK profile-card support

AniAvatar is an independent project and is not affiliated with, supported by, or endorsed by Discord, AniList, Jikan, Pinterest, Google, or `waifu.im`.

## 👤 Author

<table>
  <tr>
    <td align="center" width="180">
      <a href="https://github.com/Dendroculus">
        <img src="https://github.com/Dendroculus.png?size=96" width="96" alt="Hans avatar"><br>
        <b>Hans Valerie</b>
      </a>
      <br>
      <sub><b>Creator & Lead Developer</b></sub>
    </td>
  </tr>
</table>
