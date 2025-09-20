# AniAvatar Discord Bot  

<img src="assets/Minori.png" width="400" />  

AniAvatar is the project name. The bot appears on Discord as **Minori**.<br>
AniAvatar is a **Discord bot** built with Python and [discord.py](https://discordpy.readthedocs.io/).  
It automates anime-related tasks — search anime info, fetch profile pictures, play trivia, and level up your profile.  

---

## ✨ Features
- **Anime Search** – detailed anime information via AniList API  
- **Anime Profile Pictures** – fetch character avatars with Google Custom Search API  
- **Trivia & Games**
  - Anime quiz with scoring and EXP rewards  
  - Guess-the-character using AniList data  
- **Leveling System**
  - Gain EXP by chatting and playing games  
  - Custom titles based on level  
  - Server leaderboard
  - Profile Cards showing title, EXP, profile picture, and customizable themes/backgrounds
  - **Automatic Role Assignment**
    - Title roles (Novice → Enlightened) are auto-created and maintained
    - Old roles auto-removed when leveling up
    - Roles synced every 2 minutes to ensure consistency
    - Duplicate roles cleaned up automatically
- **Utilities**
  - `/ping` latency check  
  - `/help` dynamic command list  
- **Presence Rotation**
  - Bot updates its Discord status every 20 minutes with random anime
- **Polling**
  - Create your own custom Polling up to 5 options.


---

## 🛠 Tech Stack  
- Python 3.11+  
- [discord.py 2.x](https://pypi.org/project/discord.py/)  
- [aiohttp](https://docs.aiohttp.org/)  
- [AniList API](https://anilist.co/graphiql) – anime data  
- [Google Custom Search API](https://developers.google.com/custom-search) – image search  
- SQLite – local database for profiles, stats, and leveling  

---

## 📜 License  
This project is licensed under the **MIT License** — you are free to use, modify, and distribute it, provided proper credit is given.  
See the [LICENSE](LICENSE) file for details.  

---

## ⚠️ Disclaimer  
AniAvatar is an independent project and is **not affiliated with, supported by, or endorsed by Discord Inc., AniList, or Google.**  
All assets (backgrounds, icons, profile cards) are original and edited by me.  

---

## 🔑 Setup Google Custom Search API  

AniAvatar uses the **Google Custom Search API** to fetch anime profile pictures.  
You’ll need your own **API key** and **Search Engine ID**.  

### 1. Get an API Key  
1. Go to [Google Cloud Console](https://console.cloud.google.com/).  
2. Create a new project (or use an existing one).  
3. Navigate to **APIs & Services → Credentials**.  
4. Click **Create Credentials → API key**.  
5. Copy the generated key — this will be your `GOOGLE_API_KEY`.  

### 2. Create a Custom Search Engine (CSE)  
1. Visit [Google Programmable Search Engine](https://programmablesearchengine.google.com/).  
2. Click **Add**.  
3. Under “Sites to search”, enter:  
   - `site:myanimelist.net`  
   - `site:anilist.co`  
   - `site:zerochan.net`  
   - (or other anime image sites)  
4. Create the engine and copy the **Search Engine ID (cx)** — this will be your `GOOGLE_CSE_ID`.  

### 3. Add Keys to Environment  
In your `.env` file (already in `.gitignore`), add:  
```env
DISCORD_TOKEN=your_discord_token
GOOGLE_API_KEY=your_google_api_key
GOOGLE_CSE_ID=your_google_cse_id
```

🚧 **Note:** AniAvatar is currently under active development — features and code structure are subject to change.
