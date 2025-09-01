# AniAvatar Discord Bot  

<img src="assets/aniavatar.png" width="200" />  

AniAvatar is a **Discord bot** built with Python and [discord.py](https://discordpy.readthedocs.io/).  
It helps users save time by automating anime-related searches — no more manually hunting for profile pictures (PFPs) or anime info. Just use simple commands.  

## Features (current)  
- [x] `/ping` → Check bot latency  
- [x] `/help` → Display available commands in categories  
- [x] `/anime` → Search anime info via **AniList GraphQL API**  
- [x] `/animepfp` → Fetch anime character profile pictures via **Google Custom Search API**  

## Roadmap (Planned Features)  

### Profile Cog  
- [ ] Add bio + favorite anime/character fields  
- [ ] Implement leveling system (XP from chatting)  
- [ ] Display a profile card with avatar, bio, and stats  

### Fun & Interaction Cog  
- [ ] Hug, pat, slap, kiss commands (with anime GIFs)  
- [ ] “Ship” two users together with anime-style results  
- [ ] Daily waifu/husbando generator  

### Media Cog  
- [ ] Random anime GIFs (via Tenor API or local library)  
- [ ] Random anime quotes  

### Games Cog (future)  
- [ ] Anime trivia quiz  
- [ ] Guess-the-character-from-image game  

## Tech Stack  
- Python 3.11+  
- [discord.py 2.x](https://pypi.org/project/discord.py/)  
- [aiohttp](https://docs.aiohttp.org/)  
- [AniList API](https://anilist.co/graphiql) (anime info)  
- [Google Custom Search API](https://developers.google.com/custom-search) (image search)  

## License  
This project is licensed under the **MIT License** — you are free to use, modify, and distribute it, provided that proper credit is given.  
See the [LICENSE](LICENSE) file for details.  

## Disclaimer  
AniAvatar is an independent project and is **not affiliated with, supported by, or endorsed by Discord Inc., AniList, or Google.**  
All anime characters and artwork belong to their respective creators.  

## Setup Google Custom Search API

AniAvatar uses the **Google Custom Search API** to fetch anime profile pictures.  
You’ll need your own **API key** and **Search Engine ID** to run the bot.

### 1. Get an API Key
1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (or use an existing one).
3. Navigate to **APIs & Services → Credentials**.
4. Click **Create Credentials → API key**.
5. Copy the generated key — this will be your `GOOGLE_API_KEY`.

### 2. Create a Custom Search Engine (CSE)
1. Visit [Google Programmable Search Engine](https://programmablesearchengine.google.com/).
2. Click **Add**.
3. Under “Sites to search”, you can enter:
   - `site:myanimelist.net`
   - `site:anilist.co`
   - `site:zerochan.net`
   - (or any sites that host anime images)
4. Create the engine and note the **Search engine ID (cx)** — this will be your `GOOGLE_CSE_ID`.

### 3. Add Keys to Environment
In your `.env` file (already in `.gitignore`), add:


---  

🚧 **Note:** AniAvatar is still in early development, so features and code structure may change frequently.  
