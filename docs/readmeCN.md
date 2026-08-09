<div align="center">

  中文 | [English](../README.md)
</div>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white" alt="discord.py 2.x">
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/Redis-可选-DC382D?logo=redis&logoColor=white" alt="Redis">
  <img src="https://img.shields.io/badge/Playwright-Pinterest-2EAD33?logo=playwright&logoColor=white" alt="Playwright">
</p>

<p align="center" style="margin-top: -12px;">
  <img src="https://img.shields.io/badge/许可证-MIT-22C55E?logo=opensourceinitiative&logoColor=white" alt="MIT License">
  <img src="https://img.shields.io/badge/状态-已完成-22C55E" alt="项目状态">
</p>

<div align="center">

# 🌸 AniAvatar

### 一个面向功能模块设计的 Discord 机器人，集动漫搜索、成长系统、小游戏与社区互动于一体

</div>

## 🚀 为什么选择 AniAvatar

**AniAvatar** 在 Discord 中以 **Minori** 的身份运行。它最初只是我在空闲时间开发的个人项目，用来练习异步 Python、Discord 交互、图片搜索与模块化架构，之后逐渐发展成一个完整的社区机器人。

它将智能动漫图片搜索、持久化成长系统、个人资料卡渲染、服务器经济、互动小游戏、投票和管理工具整合在一起。项目采用按功能划分的结构，使 Discord 命令保持简洁，而仓库、工作流、视图、渲染逻辑和外部 API 集成都由各自模块负责。

- 🔍 Pinterest 主搜索与 Google 后备的动漫图片检索
- 🧠 记录用户已浏览图片，减少重复结果
- 📈 持久化 EXP、等级、金币、称号身份组和排行榜
- 🎮 独立管理交互状态的 Discord 小游戏
- 🛍️ 商店、物品栏、消耗品和物品赠送
- ⚙️ 基于 `bot.core` 与 `bot.features` 的功能导向架构
- 🛡️ 超时、冷却、限速、后备服务和恢复机制

## 🎯 功能

### A) 动漫搜索

1. 🔍 **智能头像搜索** — 根据角色名称搜索高质量动漫头像。
2. 📌 **Pinterest Worker** — 通过 Playwright 启动无头 Chromium，抓取候选图片并解析更高分辨率资源。
3. 🌐 **Google 后备搜索** — 当 Pinterest 无法提供足够结果时，可切换至 Google Custom Search。
4. 🧠 **用户感知结果** — 记录用户已接收的图片，使重复搜索保持新鲜。
5. 🧹 **去重与验证** — 过滤重复、失效和不适合展示的图片链接。
6. 📚 **动漫资料查询** — 通过 AniList 获取动漫信息。

<details>
  <summary><b>查看动漫搜索预览</b></summary>
  <br>
  <img src="screenshots/anime_result.png" width="600" alt="动漫搜索结果">
</details>

### B) 成长与经济系统

1. ⭐ **经验与等级** — 用户可通过聊天和指定小游戏获得经验值。
2. 📢 **升级反馈** — 升级时发送通知并处理相关奖励。
3. 🏷️ **自动称号身份组** — 根据等级自动创建并同步从 Novice 到 Enlightened 的称号身份组。
4. 🪪 **个人资料卡** — 渲染等级、称号、排名、EXP 和自定义背景。
5. 🏆 **服务器排行榜** — 生成服务器高排名成员的可视化排行榜。
6. 🪙 **金币经济** — 与成长数据一起持久化保存用户金币。
7. 🛒 **商店与物品栏** — 购买消耗品、查看已有道具并使用物品效果。
8. 🎁 **物品赠送** — 将支持的物品转赠给同一服务器中的其他成员。

<details>
  <summary><b>查看成长系统预览</b></summary>
  <br>
  <img src="screenshots/levelup_msg.png" width="600" alt="升级消息">
  <img src="screenshots/profilecards_command.png" width="600" alt="个人资料卡">
  <img src="screenshots/leaderboard_command.png" width="600" alt="排行榜">
  <img src="screenshots/shop&inventory_command.png" width="600" alt="商店与物品栏">
</details>

### C) 游戏与社区功能

1. 🧩 **动漫问答** — 通过平衡题目选择运行多项选择问答。
2. 🖼️ **猜动漫角色** — 根据图片猜角色并获得 EXP 与金币。
3. 🎲 **金币赌博** — 使用 Discord 交互视图进行风险与收益游戏。
4. 💬 **动漫语录** — 随机展示动漫语录，并减少短时间内重复。
5. 🌸 **Waifu 图片** — 通过 `waifu.im` 获取随机 SFW 图片。
6. 📊 **持久化投票** — 创建限时投票，支持自定义选项、投票记录、恢复与结果展示。
7. 📣 **服务器公告** — 管理员可通过 Modal 编写并发送格式化公告。
8. 🧭 **动态帮助命令** — 在 Discord 中查看可用命令。

<details>
  <summary><b>查看游戏与社区预览</b></summary>
  <br>
  <img src="screenshots/animequiz_command.png" width="600" alt="动漫问答">
  <img src="screenshots/guess_character.png" width="600" alt="猜角色">
  <img src="screenshots/gamble_Command.png" width="600" alt="金币赌博">
  <img src="screenshots/announce_command.png" width="600" alt="公告功能">
  <img src="screenshots/help_command.png" width="600" alt="帮助命令">
</details>

## 🧠 架构亮点

AniAvatar 使用功能导向架构，将 Discord 接入层、业务逻辑和共享基础设施分开。

- **轻量 Cog** 只负责命令注册、基础验证和响应编排。
- **Feature 功能包** 管理自身的工作流、视图、仓库、领域模型与外部服务。
- **Core 核心包** 存放多个功能共同使用的基础设施。
- **PostgreSQL 仓库层** 持久化成长、经济、交易、投票、搜索历史和图片缓存数据。
- **Redis 为可选依赖**，用于加速部分成长和排行榜操作。
- **进程池渲染** 将个人资料卡与排行榜生成移出 Discord 事件循环。
- **独立 Discord View** 隔离小游戏、商店、物品栏、赠送与投票的并发交互状态。
- **外部 API 客户端** 提供超时、响应验证、后备提供商和清晰错误提示。
- **恢复工作流** 可在机器人重启后重新加载仍处于活动状态的投票。

## 🔄 主要运行流程

### 动漫头像搜索流程

1. 用户提交角色名称。
2. 搜索引擎检查缓存与该用户之前收到的结果。
3. 通过限速的 Playwright Worker 搜索 Pinterest。
4. 如果已配置 Google Custom Search，则在需要时获取后备结果。
5. 对候选结果进行标准化、验证与去重。
6. 返回新图片并记录该用户已查看的结果。

### 成长与奖励流程

1. 支持的消息或游戏操作产生 EXP 或金币奖励。
2. 成长工作流验证并持久化更新。
3. 等级变化会触发身份组同步与升级反馈。
4. 个人资料卡和排行榜通过独立进程进行渲染。
5. 如果配置了 Redis，则缓存可减少重复处理。

## 🏗️ 项目结构

```text
AniAvatar/
├── bot/
│   ├── cogs/                       # Discord 扩展入口
│   ├── config/                     # 设置、路径、资源、表情和常量
│   ├── core/
│   │   ├── discord/                # 通用 Discord 辅助函数
│   │   ├── logging_config/         # 结构化日志
│   │   ├── rendering/              # 通用渲染管理
│   │   └── repositories/           # 跨功能共享的仓库
│   └── features/
│       ├── administration/         # 公告功能
│       ├── anime/                  # AniList、Jikan 与问答辅助
│       ├── animepfp/               # 智能图片搜索引擎
│       ├── fun/                    # 语录、赌博、响应与 Waifu 客户端
│       ├── games/                  # 问答和猜角色工作流
│       ├── polling/                # 投票领域、持久化、恢复与 UI
│       ├── progression/            # EXP、资料卡、排行榜与渲染
│       ├── roles/                  # 成长称号身份组同步
│       └── trading/                # 商店、物品栏、赠送和物品效果
├── data/                           # 问答、语录和应用数据
├── docs/                           # 截图与翻译文档
├── tests/
│   └── manual/                     # 外部 API 手动连通性测试
├── main.py                         # 机器人入口和共享资源
└── requirements.txt
```

## 🤖 命令列表

| 命令 | 分类 | 描述 |
| :--- | :--- | :--- |
| `/animepfp <name> [count]` | 搜索 | 获取最多 5 张独特的动漫角色头像。 |
| `/anime <query>` | 搜索 | 从 AniList 获取动漫信息。 |
| `/profile [user]` | 成长 | 显示自己或其他成员的个人资料卡。 |
| `/leaderboard` | 成长 | 渲染服务器 EXP 排行榜。 |
| `/profiletheme` | 成长 | 选择资料卡主题与背景。 |
| `/resetprofiletheme` | 成长 | 恢复默认资料卡主题。 |
| `/shop` | 交易 | 打开商店并购买消耗品。 |
| `/inventory` | 交易 | 查看物品栏并使用支持的道具。 |
| `/donate <member>` | 交易 | 将物品赠送给其他成员。 |
| `/animequiz <questions>` | 游戏 | 启动多项选择动漫问答。 |
| `/guesscharacter` | 游戏 | 根据图片猜动漫角色。 |
| `/gamble` | 娱乐 | 通过交互视图进行金币赌博。 |
| `/waifu` | 娱乐 | 从 `waifu.im` 获取随机 SFW 图片。 |
| `/animequotes` | 娱乐 | 显示随机动漫语录。 |
| `/poll <duration>` | 社区 | 通过 Discord Modal 创建限时投票。 |
| `/announce <mention> <channel>` | 管理 | 创建并发送服务器公告。 |
| `/help` | 通用 | 显示可用命令。 |
| `/ping` | 通用 | 检查机器人与 Discord 的延迟。 |

大多数用户命令都是 Hybrid Command，也可以通过配置的 `!` 前缀调用。

## 🏗️ 架构与技术栈

- **Discord 应用 — `discord.py`**  
  处理 Slash Command、前缀命令、Modal、Select、Button、冷却、监听器和持续交互流程。

- **数据库 — PostgreSQL + `asyncpg`**  
  保存用户成长、经济、交易、投票、搜索历史和图片缓存元数据。

- **可选缓存 — Redis**  
  用于部分成长和排行榜缓存，本地开发时可以不配置。

- **动漫图片搜索 — Playwright + Google Custom Search**  
  Pinterest 为主要图片来源，Google 为可选后备。

- **图片渲染 — Pillow + 多进程 Worker**  
  在不阻塞 Discord 事件循环的情况下生成资料卡与排行榜。

- **外部 API — AniList、Jikan 与 `waifu.im`**  
  提供动漫资料、角色数据、问答选项和 SFW 图片。

- **异步网络 — `aiohttp`**  
  为所有外部服务提供共享的异步 HTTP Session。

## ⚙️ 环境变量

在项目根目录创建 `.env` 文件：

```env
# 必需
DISCORD_TOKEN=your_discord_bot_token
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/aniavatar

# 可选：仅机器人所有者可使用的开发命令
OWNER_ID=your_discord_user_id

# 可选：/animepfp 的 Google 后备搜索
GOOGLE_API_KEY=your_google_api_key
SEARCH_ENGINE_ID=your_google_custom_search_engine_id

# 可选：成长与排行榜缓存
REDIS_URL=redis://localhost:6379/0

# 可选：PostgreSQL 语句超时
PG_STATEMENT_TIMEOUT_MS=2000

# 可选：外部或挂载的资源目录
ASSET_ROOT=
```

运行时必须配置 `DISCORD_TOKEN` 和 `DATABASE_URL`。Google 凭据、Redis 和 `OWNER_ID` 都是可选项。相关功能扩展加载时，机器人会自动初始化所需的 PostgreSQL 表结构。

## 🚀 本地开发

### 1) 克隆仓库

```bash
git clone https://github.com/Yoruxyv/AniAvatar.git
cd AniAvatar
```

### 2) 创建虚拟环境

```bash
python -m venv .venv
```

激活虚拟环境：

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

### 3) 安装依赖

```bash
pip install -r requirements.txt
```

Pinterest Worker 使用 Playwright。如果 `requirements.txt` 中尚未包含 Playwright，请额外安装：

```bash
pip install playwright
playwright install chromium
```

### 4) 配置 PostgreSQL

创建一个 PostgreSQL 数据库，并将连接字符串填写至 `DATABASE_URL`。

Redis 是可选的。即使没有配置 `REDIS_URL`，AniAvatar 仍可使用 PostgreSQL 和进程内逻辑运行支持的功能。

### 5) 配置 Discord 应用

在 Discord Developer Portal 中：

1. 创建应用与机器人。
2. 启用 **Server Members Intent**。
3. 启用 **Message Content Intent**。
4. 使用功能所需权限邀请机器人进入服务器。
5. 将机器人 Token 写入 `.env`。

### 6) 启动机器人

```bash
python main.py
```

启动时，AniAvatar 会：

1. 初始化共享 `aiohttp` Session。
2. 创建 PostgreSQL 连接池。
3. 加载 Discord Cogs。
4. 初始化功能所需的表结构与服务。
5. 同步 Application Commands。

## 🔒 可靠性说明

- 密钥通过环境变量加载，不应提交至 Git。
- 外部 API 调用使用共享异步网络客户端和明确超时。
- 角色数据提供商可在 AniList 与 Jikan 之间执行后备切换。
- Waifu 客户端会验证 HTTP 状态、JSON 结构、Session 可用性与图片 URL。
- 搜索 Worker 使用限速与结果验证。
- 小游戏和交易视图会验证交互用户是否为原始发起者。
- 冷却机制保护资源消耗较高和经济相关命令。
- 管理员与 Owner 命令使用明确权限检查。
- PostgreSQL 语句超时可通过 `PG_STATEMENT_TIMEOUT_MS` 配置。

## 🤝 参与贡献

欢迎提交 Issue、Pull Request 和针对性的改进。

对于较大的修改，建议先创建 Issue 确认范围。功能相关逻辑应放在对应的 `bot.features` 包中；只有真正跨多个功能共享的基础设施才应进入 `bot.core`。

提交前建议运行：

```bash
ruff format .
ruff check .
python -m compileall -q bot main.py
```

## 📜 许可证

本项目使用 MIT License。详情请查看 [LICENSE](../LICENSE)。

## 🙏 致谢

- [discord.py](https://github.com/Rapptz/discord.py)
- [AniList](https://anilist.co/)
- [Jikan](https://jikan.moe/)
- [waifu.im](https://waifu.im/)
- [Playwright](https://playwright.dev/python/)
- [Noto Fonts](https://github.com/notofonts/noto-cjk/releases)，为个人资料卡提供 CJK 字体支持

AniAvatar 是独立项目，与 Discord、AniList、Jikan、Pinterest、Google 或 `waifu.im` 不存在隶属、赞助或官方背书关系。

## 👤 作者

<table>
  <tr>
    <td align="center" width="180">
      <a href="https://github.com/Yoruxyv">
        <img src="https://github.com/Yoruxyv.png?size=96" width="96" alt="Hans 头像"><br>
        <b>Hans Valerie</b>
      </a>
      <br>
      <sub><b>创建者与主要开发者</b></sub>
    </td>
  </tr>
</table>
