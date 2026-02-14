<div align="center">CN | [English](../README.md)</div>

<h1 align="center">AniAvatar Discord 机器人 (Minori)</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python 版本">
  <img src="https://img.shields.io/badge/discord.py-v2.x-7289DA.svg?logo=discord&logoColor=white" alt="discord.py">
  <img src="https://img.shields.io/badge/许可证-MIT-green.svg" alt="许可证">
  <img src="https://img.shields.io/badge/状态-活跃-green.svg" alt="状态">
</p>

<p align="center">
  <img src="../assets/MinoriBG.png" width="1000" height="900" alt="Minori">
</p>

**AniAvatar**（在 Discord 上显示为 **Minori**）是一个功能丰富的机器人，使用 Python 和 `discord.py` 构建。它能自动化处理各种与动漫相关的任务，利用定制构建的智能搜索引擎进行高质量图片检索，同时还能主持问答游戏并管理全服的等级与经济系统。


## ✨ 主要功能

### 🔍 智能搜索引擎 (新!)
- **Pinterest 集成**：使用无头浏览器引擎（Playwright）直接从 Pinterest 抓取高分辨率动漫艺术图。
- **智能缓存**：实现"用户感知缓存"，记住用户已看过的图片。搜索同一角色时，直到你看完所有可用图片前，不会显示重复内容。
- **可靠后备**：如果 Pinterest 结果不足，自动切换至 Google 图片。
- **自动画质提升**：智能逻辑查找并提供图片的最高分辨率版本（例如将缩略图转换为原图）。

### 💰 成长与经济系统
- **经验与升级**：通过聊天和参与小游戏获得经验值（EXP）。
- **升级提醒**：达到新等级时会触发公开通知。
- **自动角色分配**：根据用户等级自动创建与分配称号（例如从初学者到高级称号）。
- **可定制个人资料卡**：展示等级、称号与经验的个性化卡片，支持主题与背景定制。
- **服务器排行榜**：生成精美的排行榜图片，展示服务器排名。
- **商店、物品栏与交易**：赚取金币用于在商店购买道具，管理物品栏，支持捐赠物品给其他用户。

<details>
  <summary><b>查看成长系统预览</b></summary>
  <img src="screenshots/levelup_msg.png" width="600" alt="levelup">
  <img src="screenshots/profilecards_command.png" width="600" alt="profilecards">
  <img src="screenshots/leaderboard_command.png" width="600" alt="leaderboard">
  <img src="screenshots/shop&inventory_command.png" width="600" alt="shop inventory">
</details>

### 🎮 游戏与娱乐
- **动漫问答与猜角色**：多项选择的问答或图片猜人游戏，答对可获得 EXP 与金币。
- **金币赌博**：动态几率的押注系统。
- **老婆图 & 语录**：随机获取老婆图片或经典语录。
- **投票功能**：创建最多 5 个选项的弹出式投票（modal）。

<details>
  <summary><b>查看游戏与娱乐预览</b></summary>
  <img src="screenshots/animequiz_command.png" width="600" alt="animequiz">
  <img src="screenshots/guess_character.png" width="600" alt="guesscharacter">
  <img src="screenshots/gamble_command.png" width="600" alt="gamble">
</details>

### ⚙️ 动漫工具与实用功能
- **动漫与角色搜索**：从 AniList 获取动漫/角色的详细信息。
- **服务器公告**：管理员可发送格式化公告。
- **动态帮助命令**：清晰、组织良好的命令列表。

<details>
  <summary><b>查看实用功能预览</b></summary>
  <img src="screenshots/anime_result.png" width="600" alt="anime result">
  <img src="screenshots/announce_command.png" width="600" alt="announce">
  <img src="screenshots/help_command.png" width="600" alt="help">
</details>


## 🤖 命令列表

| 命令 | 分类 | 描述 |
| :--- | :--- | :--- |
| `/animepfp <name> [count]` | 搜索 | (已更新) 获取最多 5 张独特的角色高清头像。 |
| `/anime <query>` | 搜索 | 从 AniList 获取动漫详细信息。 |
| `/profile [user]` | 成长系统 | 显示您或别人的个人资料卡。 |
| `/leaderboard` | 成长系统 | 显示服务器前 10 名用户（按 EXP）。 |
| `/profiletheme` | 成长系统 | 选择个人资料卡的主题背景。 |
| `/resetprofiletheme` | 成长系统 | 重置资料卡主题为默认。 |
| `/shop` | 交易 | 打开商店购买消耗品（如经验药水）。 |
| `/inventory` | 交易 | 查看并使用个人物品栏。 |
| `/donate <member>` | 交易 | 将物品捐赠给其他用户。 |
| `/animequiz <questions>` | 游戏 | 启动多项选择动漫问答。 |
| `/guesscharacter` | 游戏 | 启动根据图片猜角色游戏。 |
| `/gamble` | 娱乐 | 用金币进行赌博，胜率动态变化。 |
| `/waifu` | 娱乐 | 获取随机老婆图。 |
| `/animequotes` | 娱乐 | 获取随机动漫语录。 |
| `/poll <duration>` | 娱乐 | 创建带自定义选项的投票（通过弹窗）。 |
| `/announce <mention> <channel>` | 管理 | （仅限管理员）创建并发送公告。 |
| `/help` | 通用 | 显示所有可用命令的列表。 |
| `/ping` | 通�� | 检查机器人到 Discord 服务器的延迟。 |


## 🚀 快速上手（自托管）

按照以下步骤运行您自己的 Minori 实例。

### 1. 先决条件
- Python 3.11+
- PostgreSQL（搜索引擎缓存必需）。
- Chromium（Pinterest 抓取器通过 Playwright 运行必需）。

### 2. 安装
```bash
# 克隆仓库
git clone https://github.com/Dendroculus/AniAvatar.git

# 进入项目目录
cd AniAvatar

# 推荐：创建虚拟环境
python -m venv .venv
.venv\Scripts\activate   # Windows
source .venv/bin/activate  # macOS / Linux

# 安装 Python 依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器（搜索引擎必需）
playwright install chromium
```

### 3. 配置

在项目根目录创建 `.env` 文件并添加下列密钥。该文件已包含在 `.gitignore` 中，防止意外泄露您的密钥。

```env
DISCORD_TOKEN=your_discord_token
GOOGLE_API_KEY=your_google_api_key
SEARCH_ENGINE_ID=your_google_cse_id

# 数据库 (PostgreSQL)
# 缓存和用户历史记录必需
DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<database>

# 可选配置
LOG_LEVEL=INFO
CACHE_TTL_HOURS=24
```

#### Google API 设置（后备）
如果 Pinterest 抓取失败，`/animepfp` 命令会使用 Google 作为后备。

<details>
  <summary>点击此处查看说明</summary>
  
  1. 从 [Google Cloud Console](https://console.cloud.google.com/) 获取 API Key。
  2. 在 [Google Programmable Search Engine](https://programmablesearchengine.google.com/) 创建一个 Custom Search Engine (CSE)。
  3. 在 CSE 设置中启用"Image search（图片搜索）"。
  4. 将 **Search Engine ID (cx)** 复制到 `.env` 文件中的 `SEARCH_ENGINE_ID`。
</details>

### 4. 数据库设置

Minori 使用 PostgreSQL。机器人在首次运行时会自动创建所需的表（`image_cache`, `search_history`, `user_seen_images`）。

请确保您的 `DATABASE_URL` 正确且 PostgreSQL 服务器正在运行。

### 5. 运行机器人

配置完成后，使用以下命令启动机器人：
```bash
python main.py
```


## 🛠 技术栈
- **框架**: [discord.py](https://pypi.org/project/discord.py/), [aiohttp](https://docs.aiohttp.org/)
- **搜索引擎**: Playwright (无头浏览器), Google Custom Search
- **数据库**: PostgreSQL (via asyncpg)
- **API**: [AniList API (GraphQL)](https://anilist.co/graphiql)
- **图像处理**: [Pillow (PIL)](https://pillow.readthedocs.io/en/stable/)


## 📜 许可证
本项目使用 **MIT License**。详见 [LICENSE](../LICENSE) 文件。


## 🙌 致谢
- 感谢 [Noto Fonts](https://github.com/notofonts/noto-cjk/releases) 提供 CJK 字体支持用于个人资料卡。
- 本项目为独立创作，与 Discord Inc., AniList, Pinterest 或 Google 无任何隶属或背书关系。所有原创资产均由作者制作。