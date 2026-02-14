<div align="center">

EN | [中文](docs/readmeCN.md)
</div>

<h1 align="center">AniAvatar Discord Bot (Minori)</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/discord.py-v2.x-7289DA.svg?logo=discord&logoColor=white" alt="discord.py">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT">
  <img src="https://img.shields.io/badge/status-Active-green.svg" alt="Update Status">
</p>

<p align="center">
  <img src="assets/MinoriBG.png" width="1000" height="900">
</p>

**AniAvatar** (appearing on Discord as **Minori**) is a feature-rich bot built with Python and `discord.py`. It automates a wide range of anime-related tasks, utilizing a custom-built Smart Search Engine for high-quality image retrieval, while also hosting trivia games and managing a server-wide leveling economy.


## ✨ Features

### 🔍 Smart Search Engine
- **Pinterest Integration**: Scrapes high-resolution anime art directly from Pinterest using a headless browser engine (Playwright).
- **Smart Caching**: Implements a "User-Aware Cache" that remembers which images you've seen. Searching for the same character won't show you duplicate images until you've seen everything available.
- **Reliable Fallback**: Automatically switches to Google Images if Pinterest results are insufficient.
- **Auto-Upscaling**: Intelligent logic to find and serve the highest resolution version of an image (e.g., converting thumbnails to originals).

### 💰 Progression & Economy
- **EXP & Leveling**: Gain EXP by chatting and playing games.
- **Level Up Alerts**: Receive public notifications on level-ups and rank changes.
- **Automatic Role Assignment**: The bot auto-creates and manages title roles (from *Novice* to *Enlightened*) based on user level.
- **Customizable Profile Cards**: Display your rank, title, and EXP with a personalized card featuring custom themes and backgrounds.
- **Server Leaderboard**: Compete for the top spot on a beautifully rendered leaderboard image.
- **Shop, Inventory & Trading**: Earn coins to spend in the item shop. Manage items in your inventory and donate them to other users.

<details>
  <summary><b>View Progression Previews</b></summary>
  <img src="docs/screenshots/levelup_msg.png" width="600">
  <img src="docs/screenshots/profilecards_command.png" width="600">
  <img src="docs/screenshots/leaderboard_command.png" width="600">
  <img src="docs/screenshots/shop&inventory_command.png" width="600">
</details>

### 🎮 Games & Fun
- **Anime Quiz & Guessing Games**: Test your knowledge with a multiple-choice quiz or a guess-the-character game to earn EXP and coins.
- **Coin Gambling**: Gamble your coins with a dynamic win chance.
- **Waifu & Quotes**: Get random waifu images or memorable quotes from various anime.
- **Polling**: Create custom polls with up to 5 options for the community to vote on.

<details>
  <summary><b>View Games & Fun Previews</b></summary>
  <img src="docs/screenshots/animequiz_command.png" width="600">
  <img src="docs/screenshots/guess_character.png" width="600">
  <img src="docs/screenshots/gamble_command.png" width="600">
</details>

### ⚙️ Anime & Utilities
- **Anime Metadata**: Get detailed information about any anime from AniList.
- **Server Announcements**: Admins can easily create and send formatted announcements.
- **Dynamic Help Command**: Get a clean, organized list of all available commands.

<details>
  <summary><b>View Utility Previews</b></summary>
  <img src="docs/screenshots/anime_result.png" width="600">
  <img src="docs/screenshots/announce_command.png" width="600">
  <img src="docs/screenshots/help_command.png" width="600">
</details>


## 🤖 Commands

| Command | Category | Description |
| :--- | :--- | :--- |
| `/animepfp <name> [count]` | Search | (Updated) Fetches up to 5 unique, high-quality profile pictures for a character. |
| `/anime <query>` | Search | Fetches detailed information about an anime from AniList. |
| `/profile [user]` | Progression | Displays your or another user's profile card. |
| `/leaderboard` | Progression | Shows the server's top 10 users by EXP. |
| `/profiletheme` | Progression | Choose a custom background theme for your profile card. |
| `/resetprofiletheme` | Progression | Resets your profile card theme to the default. |
| `/shop` | Trading | Opens the item shop to buy consumables like EXP potions. |
| `/inventory` | Trading | Check your inventory and use your items. |
| `/donate <member>` | Trading | Give an item from your inventory to another user. |
| `/animequiz <questions>` | Games | Starts a multiple-choice anime trivia quiz. |
| `/guesscharacter` | Games | Starts a guess-the-character from an image game. |
| `/gamble` | Fun | Gamble your coins with a dynamic win chance. |
| `/waifu` | Fun | Fetches a random waifu image. |
| `/animequotes` | Fun | Gives you a random quote from an anime. |
| `/poll <duration>` | Fun | Creates a poll with custom options via a pop-up modal. |
| `/announce <mention> <channel>` | Admin | (Admin Only) Creates and sends an announcement. |
| `/help` | General | Shows this list of all available commands. |
| `/ping` | General | Checks the bot's latency to Discord's servers. |


## 🚀 Getting Started (Self-Hosting)

To run your own instance of Minori, follow these steps.

### 1. Prerequisites
- Python 3.11+
- PostgreSQL (Required for the Search Engine cache).
- Chromium (Required for the Pinterest scraper via Playwright).

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/Dendroculus/AniAvatar.git

# Navigate to the project directory
cd AniAvatar

# Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate   # Windows
source .venv/bin/activate  # macOS / Linux

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright Browsers (Required for Search Engine)
playwright install chromium
```

### 3. Configuration

In your project directory, create a `.env` file and add the following keys. This file is included in `.gitignore` to prevent you from accidentally sharing your secrets.

```env
DISCORD_TOKEN=your_discord_token
GOOGLE_API_KEY=your_google_api_key
SEARCH_ENGINE_ID=your_google_cse_id

# Database (PostgreSQL)
# Required for caching and user history
DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<database>

# Optional Configuration
LOG_LEVEL=INFO
CACHE_TTL_HOURS=24
```

#### Google API Setup (Fallback)
The `/animepfp` command uses Google as a backup if Pinterest fails.

<details>
  <summary>Click here for instructions</summary>
  
  1. Get an API Key from the [Google Cloud Console](https://console.cloud.google.com/).
  2. Create a Custom Search Engine (CSE) at [Google Programmable Search Engine](https://programmablesearchengine.google.com/).
  3. Enable "Image search" in the CSE settings.
  4. Copy the **Search Engine ID (cx)** into `SEARCH_ENGINE_ID` in your `.env`.
</details>

### 4. Database Setup

Minori uses PostgreSQL. The bot will automatically create the necessary tables (`image_cache`, `search_history`, `user_seen_images`) on the first run.

Ensure your `DATABASE_URL` is correct and the PostgreSQL server is running.

### 5. Run the Bot

Once configured, you can start the bot with:
```bash
python main.py
```


## 🛠 Built With
- **Frameworks**: [discord.py](https://pypi.org/project/discord.py/), [aiohttp](https://docs.aiohttp.org/)
- **Search Engine**: Playwright (Headless Browser), Google Custom Search
- **Database**: PostgreSQL (via asyncpg)
- **APIs**: [AniList API (GraphQL)](https://anilist.co/graphiql)
- **Imaging**: [Pillow (PIL)](https://pillow.readthedocs.io/en/stable/)


## 📜 License
This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for details.


## 🙌 Acknowledgements
- Thanks to [Noto Fonts](https://github.com/notofonts/noto-cjk/releases) for providing CJK font support for the profile cards.
- This project is an independent creation and is **not affiliated with, supported by, or endorsed by Discord Inc., AniList, Pinterest, or Google.** All original assets are created by me.