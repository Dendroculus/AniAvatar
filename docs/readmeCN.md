EN | [English](../README.md)

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

AniAvatar（在 Discord 上显示为 Minori）是一个功能丰富的机器人，使用 Python 和 discord.py 构建。它能自动化处理各种与动漫相关的任务，包括搜索信息、获取头像、主持问答游戏，以及管理服务器范围内的等级与经济系统。



## ✨ 主要功能

### 成长与经济系统
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

### 游戏与娱乐
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

### 动漫工具与实用功能
- **动漫与角色搜索**：从 AniList 获取动漫/角色的详细信息。
- **服务器公告**：管理员可发送格式化公告。
- **动态帮助命令**：清晰、组织良好的命令列表。
- **状态轮换**：机器人状态每 20 分钟切换一次，显示“正在观看”随机动漫。

<details>
  <summary><b>查看实用功能预览</b></summary>
  <img src="screenshots/anime_result.png" width="600" alt="anime result">
  <img src="screenshots/announce_command.png" width="600" alt="announce">
  <img src="screenshots/help_command.png" width="600" alt="help">
</details>



## 🤖 命令列表

| 命令 | 分类 | 描述 |
| :--- | :--- | :--- |
| `/profile [user]` | 成长系统 | 显示您或别人的个人资料卡 |
| `/leaderboard` | 成长系统 | 显示服务器前 10 名用户（按 EXP） |
| `/profiletheme` | 成长系统 | 选择个人资料卡的主题背景 |
| `/resetprofiletheme` | 成长系统 | 重置资料卡主题为默认 |
| `/shop` | 交易 | 打开商店购买消耗品（如经验药水） |
| `/inventory` | 交易 | 查看并使用个人物品栏 |
| `/donate <member>` | 交易 | 将物品捐赠给其他用户 |
| `/anime <query>` | 搜索 | 从 AniList 获取动漫信息 |
| `/animepfp <name>` | 搜索 | 查找角色头像 |
| `/animequiz <questions>` | 游戏 | 启动多项选择动漫问答 |
| `/guesscharacter` | 游戏 | 启动根据图片猜角色游戏 |
| `/gamble` | 娱乐 | 用金币进行赌博 |
| `/waifu` | 娱乐 | 获取随机老婆图 |
| `/animequotes` | 娱乐 | 获取随机动漫语录 |
| `/poll <duration>` | 娱乐 | 创建带自定义选项的投票（通过弹窗） |
| `/announce <mention> <channel>` | 管理 | （仅限管理员）发送公告 |
| `/help` | 通用 | 显示帮助菜单 |
| `/ping` | 通用 | 检查机器人延迟 |



## 🚀 快速上手（自托管）

下面说明如何在本地或服务器上运行 Minori（AniAvatar）。

### 1. 先决条件
- Python 3.11+
- Git
- 一个来自 Discord 开发者门户 的 Bot Token
- PostgreSQL（生产）或本地 Postgres（开发）。若希望快速在本地试用，可使用 Docker。

### 2. 安装项目
```bash
# 克隆仓库
git clone https://github.com/Dendroculus/AniAvatar.git

# 进入项目目录
cd AniAvatar

# 推荐：创建并激活虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

```

### 3. 配置

在项目根目录创建 `.env`（此文件已添加到 .gitignore）并填写下列变量：

```env
DISCORD_TOKEN=your_discord_token
GOOGLE_API_KEY=your_google_api_key
GOOGLE_CSE_ID=your_google_cse_id

# PostgreSQL 连接字符串（示例）
DATABASE_URL=postgresql://<user>:<encoded_password>@<host>:5432/<database>
```

- 注意：若密码包含特殊字符，请对密码进行 URL 编码（例如使用 Python 的 urllib.parse.quote_plus）。

#### Google Custom Search（/animepfp）
- 需要 Google API Key 与 Custom Search Engine ID（cx）。
- 在 Google Cloud Console 创建 API Key，并在 Programmable Search Engine 中创建 CSE，添加要搜索的站点并复制 cx。

#### 自定义表情
- 将 `assets/other essentials emojis/` 中需要的表情上传到您管理的 Discord 服务器（机器人也需在该服）。
- 在 Discord 中启用开发者模式，右键表情并复制 ID，将这些 ID 更新到代码（例如 cogs/utils/emojis.py）。



## 4. 数据库（Postgres）与从 SQLite 迁移

本项目已从 SQLite 迁移到 PostgreSQL（asyncpg）。下面提供迁移与初始化说明。

### A. 本地快速 Postgres（使用 Docker）
```bash
docker run --name ani-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_USER=postgres -e POSTGRES_DB=MinoriDB -p 5432:5432 -d postgres
# 本地 DATABASE_URL 示例：
# postgresql://postgres:postgres@127.0.0.1:5432/MinoriDB
```

### B. 迁移（如果你有现有的 SQLite 数据）
仓库中包含迁移脚本 `migrate_sqlite_to_postgres.py`，可将 `data/minori.db` 的内容迁移到 Postgres。

推荐迁移流程（在迁移前请先备份）：

1. 停止机器人（确保 SQLite 不再写入）。
2. 备份 SQLite：
```cmd
copy data\minori.db data\minori.db.bak
```
3. 如果存在 WAL 文件，做 checkpoint：
```cmd
python -c "import sqlite3; c=sqlite3.connect('data\\minori.db'); c.execute('pragma wal_checkpoint(FULL)'); c.close(); print('checkpoint done')"
```
4. 先做一次 dry-run（仅预览 DDL，不复制数据）：
```cmd
python migrate_sqlite_to_postgres.py --sqlite-file data\minori.db --database-url "%DATABASE_URL%" --dry-run
```
5. 若 dry-run 无误，执行真实迁移（复制数据）：
```cmd
python migrate_sqlite_to_postgres.py --sqlite-file data\minori.db --database-url "%DATABASE_URL%"
```
6. 可选：迁移后将列转换为更合适的类型（如 BIGINT、INTEGER、JSONB），并添加索引以优化查询。相关 SQL 与说明已记录在迁移脚本与文档中。

### C. 全新安装
若不需要迁移，只需创建 Postgres 数据库并设置 `DATABASE_URL`，机器人在启动时（cog 加载）会自动创建所需的表（使用 `CREATE TABLE IF NOT EXISTS`）。



## 5. 运行机器人
配置完成后，运行：

```bash
python main.py
```

确保启动时环境中包含正确的 `DATABASE_URL`，并且数据库可访问。



## 🛠️ 构建技术栈
- Python 3.11+
- discord.py v2.x
- aiohttp
- Pillow (PIL)
- asyncpg（Postgres 驱动）
- APIs: AniList (GraphQL), Google Custom Search

数据库：PostgreSQL（asyncpg）。仓库中同时包含迁移工具以帮助把旧的 SQLite 数据导入 PostgreSQL。



## 📜 许可证
本项目使用 **MIT License**。详见 [LICENSE](../LICENSE)。



## 🙌 致谢
感谢 Noto Fonts 提供的 CJK 字体支持。  
本项目为独立创作，与 Discord Inc., AniList 或 Google 无任何隶属或背书关系。所有原创资产均由作者提供。