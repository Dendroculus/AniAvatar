[EN](../README.md) | 中文
# AniAvatar Discord 机器人  

<img src="../assets/MinoriBG.png" width="1000" height ="900">  

AniAvatar 是项目名称，机器人在 Discord 上的名字为 **Minori**。  
AniAvatar 是一个用 Python 和 [discord.py](https://discordpy.readthedocs.io/) 构建的 **Discord 机器人**。  
它可以自动化处理与动漫相关的任务——搜索动漫信息、获取头像、玩问答游戏，以及升级你的个人资料。  

---

## ✨ 功能
- **动漫搜索** – 通过 AniList API 获取详细动漫信息  
- **动漫头像** – 使用 Google Custom Search API 获取角色头像  
- **问答 & 游戏**
  - 动漫知识测验，获得积分和经验值  
  - 猜角色游戏，数据来自 AniList  
- **等级系统**
  - 通过聊天和玩游戏获得经验值  
  - 根据等级获得自定义称号  
  - 服务器排行榜  
  - 个人资料卡展示称号、经验值、头像及可自定义主题/背景  
  - **自动分配角色**
    - 称号角色（初学者 → 智者）会自动创建并管理  
    - 升级时旧角色自动移除  
    - 每两分钟同步角色，保持一致性  
    - 自动清理重复角色  
- **实用功能**
  - `/ping` 延迟检测  
  - `/help` 动态命令列表  
- **状态轮换**
  - 每 20 分钟更新一次 Discord 状态，显示随机动漫  
- **投票**
  - 自定义最多 5 个选项的投票  

---

## 🛠 使用技术
- Python 3.11+  
- [discord.py 2.x](https://pypi.org/project/discord.py/)  
- [aiohttp](https://docs.aiohttp.org/)  
- [AniList API](https://anilist.co/graphiql) – 动漫数据  
- [Google Custom Search API](https://developers.google.com/custom-search) – 图片搜索  
- SQLite – 本地数据库，用于存储个人资料、统计数据和等级信息  

---

## 📜 许可证  
本项目使用 **MIT 许可证** —— 你可以自由使用、修改和分发，但需保留原作者署名。  
详见 [LICENSE](LICENSE) 文件。  

---

## 🙌 鸣谢
感谢 [Noto Fonts](https://github.com/notofonts/noto-cjk/releases) 提供 CJK 字体支持。  

## ⚠️ 免责声明  
AniAvatar 为独立项目，**与 Discord Inc.、AniList 或 Google 无任何关联、支持或背书**。  
所有资源（背景、图标、个人资料卡）均为原创或自行编辑。  

---

## 🔑 设置 Google Custom Search API  

AniAvatar 使用 **Google Custom Search API** 获取动漫头像。  
你需要拥有自己的 **API Key** 和 **搜索引擎 ID**。  

### 1. 获取 API Key  
1. 前往 [Google Cloud Console](https://console.cloud.google.com/)。  
2. 创建新项目（或使用已有项目）。  
3. 导航到 **API 与服务 → 凭证**。  
4. 点击 **创建凭证 → API Key**。  
5. 复制生成的 Key —— 这就是你的 `GOOGLE_API_KEY`。  

### 2. 创建自定义搜索引擎 (CSE)  
1. 访问 [Google 可编程搜索引擎](https://programmablesearchengine.google.com/)。  
2. 点击 **添加**。  
3. 在“要搜索的网站”中输入：  
   - `site:myanimelist.net`  
   - `site:anilist.co`  
   - `site:zerochan.net`  
   - （或其他动漫图片网站）  
4. 创建搜索引擎并复制 **搜索引擎 ID (cx)** —— 这就是你的 `GOOGLE_CSE_ID`。  

### 3. 添加到环境变量  
在 `.env` 文件中（已加入 `.gitignore`）添加：  
```env
DISCORD_TOKEN=your_discord_token
GOOGLE_API_KEY=your_google_api_key
GOOGLE_CSE_ID=your_google_cse_id
```

🚧 注意： AniAvatar 当前仍在开发中 —— 功能和代码结构可能会有变动。
