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
- [ ] Set a custom anime profile picture (avatar)  
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

---  

🚧 **Note:** AniAvatar is still in early development, so features and code structure may change frequently.  
