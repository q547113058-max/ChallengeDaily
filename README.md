# 🖥️ ChallengeDaily

<p align="center">
  <img src="https://img.shields.io/github/stars/EXtreameChallenge/ChallengeDaily?style=for-the-badge&color=fedc2e" />
  <img src="https://img.shields.io/github/forks/EXtreameChallenge/ChallengeDaily?style=for-the-badge&color=3296ff" />
  <img src="https://img.shields.io/badge/Electron-31-47848f?style=for-the-badge&logo=electron" />
  <img src="https://img.shields.io/badge/Python-3.11-3776ab?style=for-the-badge&logo=python" />
  <img src="https://img.shields.io/badge/AI-多模型-8b5cf6?style=for-the-badge&logo=openai" />
  <img src="https://img.shields.io/badge/Windows-11-0078d6?style=for-the-badge&logo=windows11" />
  <img src="https://img.shields.io/badge/License-MIT-97ca00?style=for-the-badge" />
</p>

<p align="center"><b>AI 替你记录每一天。你只管活。</b></p>

> 📌 **接手 / 启动看这里**：[HANDOFF.md](HANDOFF.md) —— 本机实测路径、三种启动方式、环境坑与验证清单。
> 本仓库为私有 fork [`q547113058-max/ChallengeDaily`](https://github.com/q547113058-max/ChallengeDaily)（分支 `master`）；上游为 `EXtreameChallenge/ChallengeDaily`（MIT）。文档最后一次核对：2026-11-07。

---

> 🥟 你打开微信想回一条消息。45 分钟后你在看怎么做锅包肉。你连锅包肉都没吃过。
>
> 📖 你点开 B 站搜 Rust 教程。两个小时后，你在看「猫咪第一次见到雪」。你没有猫。
>
> 💀 你告诉自己今天要写完那个模块。凌晨 1 点你躺在床上刷手机，VSCode 还开着——今天新建了一个文件，删了，又新建了一个，写了 11 行，全删了。

**这不是效率问题。这是你不知道自己在浪费时间。而你不知道的原因，是你不敢知道。**

---

## 😨 没人愿意面对这件事

你想过用时间记录软件。你装过 Toggl、试过番茄钟、甚至买过 RescueTime 的订阅。

三天后你都卸载了。原因是同一个：**它们让你手动记录，但你根本不想记。**

——因为你隐约知道，记录下来的数字会让你难堪。

| 😇 你以为 | 💀 真实 |
|-----------|--------|
| 今天学了 4 个小时 | 学了 1.5 小时，剩余 2.5 小时在"打开教程 → 切 B 站 → 切微信 → 再也没回去" |
| 只回了"几条消息" | 微信实打实吞了你 2.3 小时 |
| 下午一直在码代码 | 中间切了 17 次到浏览器 |
| 这周很努力 | 趋势线在往下走，已经连续三周了 |

> 🧠 **人类对时间的感知，烂到连自己都骗得过。**
>
> 人脑天生不擅长感知时间跨度——你能感觉到 5 分钟和 1 小时的区别，但你不能感觉到「今天有效工作 4.2 小时还是 6.5 小时」。没有外部数据，你永远不知道这个差距。

---

## 👀 所以 ChallengeDaily 不问你"在干什么"

它直接看你的屏幕。

```
┌─────────────────────────────────────────────┐
│  📸 每 60 秒截一张屏幕                        │
│              ↓                               │
│  🤖 AI 视觉模型识别内容（12 个类别）           │
│              ↓                               │
│  📊 自动归档 → 生成日报 / 周报 / 深度洞察       │
└─────────────────────────────────────────────┘
```

**全程不用你点任何按钮。连"开始"都省了。**

这不是"自动记录"——这是**把你变成旁观者，让你从上帝视角看自己的一天。**

> 🔥 **你不需要读时间管理书。你不需要学什么方法论。你只需要看见你自己。**
>
> 看见一次，胜过自我反思一年。

---

## 🛠️ 但"看见"只是第一步

你看见自己每天有 2.3 小时被微信吞掉。然后呢？

**ChallengeDaily 不是只告诉你「你废了」，它给你工具让你不再废。**

### 🍅 番茄钟 / 🐾 桌面宠物 / 💬 AI 对话 —— 已移除

以下模块在当前版本中**不再提供**，保留说明仅为避免读者被历史文案误导：

| 模块 | 移除提交 | 说明 |
|---|---|---|
| 🍅 番茄钟 | `20403f6`（2026-09-12） | 计时、白噪音、专注屏蔽全部下线 |
| 🐾 桌面宠物 | `6a34b2c`（2026-09-06） | 独立宠物窗口与情绪引擎一并删除 |
| 💬 AI 对话 / AI 教练 | `1f13409`（2026-09-06） | 对话页与首页教练面板删除，仅保留日报/周报生成与深度洞察 |

**当前版本仍提供**：全自动屏幕记录与分类、待办与周计划、习惯打卡与成就、AI 日报 / 周报 / 月报、日记、深度洞察、Webhook 推送。功能现状以 `HANDOFF.md` 与仓库代码为准。

### ✅ 待办 + 周计划 —— 让你知道然后干什么

你最大的时间黑洞：**不是不想干，是不知道干什么，于是打开手机刷十分钟等灵感。**

| 模式 | 适合场景 | 比如 |
|------|---------|------|
| ⏱️ 计时型 | 有明确截止时间的任务 | "25 分钟内搞定登录表单" |
| 🎯 目标型 | 结果导向（没明确时长） | "重构到单元测试全绿为止" |
| 🔁 习惯型 | 每日重复性积累 | "每天背 20 个单词"——在**习惯追踪**页创建 |

周计划按月 → 周 → 日三级层级，拖拽分配。**打开电脑第一眼看到的是今天要做什么，不是今天要看什么视频。**

### 🏆 习惯打卡 + 成就 —— 让你想回来

单独的习惯 App 你装了 3 个，全弃了。为什么？**因为它们跟你的工作数据完全割裂——你打不打卡，和你的时间流向毫无关系。**

ChallengeDaily 这边：
- 📝 连续 7 天写日记 → 解锁「🧘 自我觉醒者」
- 📅 连续打卡喝水 21 天 → 解锁「💧 生命之源」
- 📚 学习类目累计达标 → 解锁对应勋章

> 这些不是游戏化噱头。是你的数据在替你说话。

### 🤖 AI 日报 —— 不用写日报

不是 ChatGPT 式的"今日总结"。是 AI 读完你今天**全部屏幕记录**后，按 12 个类别自动分类，写成的日报。

```
📅 2026年7月9日 · AI 日报
━━━━━━━━━━━━━━━━━━━━━━
💻 开发      3.2h  ██████████████░░░░░░░░
💬 沟通      1.8h  ████████░░░░░░░░░░░░░░
📚 学习      1.5h  ██████░░░░░░░░░░░░░░░░
☕ 摸鱼      0.8h  ███░░░░░░░░░░░░░░░░░░░
━━━━━━━━━━━━━━━━━━━━━━
✅ 有效时间 6.5h  📝 已写日记  📈 比昨天 +12%
```

周报与深度洞察会基于同一批数据做趋势对比与结构化解读——**结论挂在你自己的真实行为数据上，不是通用鸡汤。**

### 📓 日记 + 🔬 深度洞察 —— 让你看得懂自己

日记 AI 自动关联当天工作数据，你的反思不再对着空白文本框硬编。周报和深度洞察基于 **10 个学术框架**量化分析，告诉你"碎片化学习占比 60%，建议减少并行任务"——这不是 AI 拍脑袋，是心理学 + 教育学框架算出来的。

---

## 🔒 隐私：不回避

| 🚫 不做 | ✅ 做 |
|---------|-----|
| 截图仅留本地、默认保留 7 天后轮换删除（`RETENTION_DAYS`） | 微信 / 飞书 / 密码管理器 / 银行页面自动跳过 |
| API Key 不写 .env 明文 | Windows DPAPI 加密存储 |
| 数据不传云端 | 100% 本地，断网正常跑 |
| 不接 Key 也能用的功能不锁 | 内置 30+ 规则自动分类 |

---

## 🆚 同类产品对比

| | RescueTime | Toggl | Timing | ManicTime | 🔥 ChallengeDaily |
|---|:---:|:---:|:---:|:---:|:---:|
| 📸 自动记录 | ✅ | — | ✅ | ✅ | ✅ |
| 🤖 AI 识别屏幕 | — | — | — | — | ✅ |
| ✅ 待办/周计划 | — | — | — | — | ✅ |
| 🏆 习惯/成就 | — | — | — | — | ✅ |
| 📊 AI 日报 | — | — | — | — | ✅ |
| 🔍 深度洞察 | — | — | — | — | ✅ |
| 🔔 Webhook | — | — | — | — | ✅ |
| 🏠 100% 本地 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 💰 免费开源 | — | — | — | — | ✅ |

> 💡 其他工具解决"记录"。ChallengeDaily 解决 **记录 → 理解 → 优化 → 产出**一整条链。

---

## 🪟 为什么是 Windows，为什么是现在

<p align="center">
  🏆 <b>Timing</b> / <b>Rize</b> / <b>Daily</b> 全部 Mac 独占<br>
  👥 <b>1.5 亿 Windows 用户</b> 没人管
</p>

同时智谱 GLM-4V-Flash 视觉模型已能精准识别屏幕内容，且**完全免费**。以前烧钱的 AI 能力现在成本趋零。技术窗口开了，市场缺口在那——这个坑，我们来填。

---

## 🚀 跑起来（本机实测 2026-11-07）

> 完整启动链路、历史坑位清单与验证命令见 **[HANDOFF.md](HANDOFF.md)**。下面只给最短路径。

**项目根**：`E:\WorkBuddy\2026-09-05-19-07-53\ChallengeDaily-main\ChallengeDaily-main`

### 首次安装（只需一次）

```bash
# 后端依赖，二选一（本机实测：venv 已装齐，系统 Python312 缺 mss）
# A 推荐：装到系统 Python312 —— 装完后双击 start.vbs 就能一键自启后端
"C:/Users/54711/AppData/Local/Programs/Python/Python312/python.exe" -m pip install -r requirements.txt waitress
# B 不改系统环境：装到 WorkBuddy venv（Python 3.13.14）—— 走下面的两段式启动
"C:/Users/54711/.workbuddy/binaries/python/envs/default/Scripts/python.exe" -m pip install -r requirements.txt waitress

# 前端依赖与构建产物（Electron 跑 dist/index.html，不是 dev server）
cd client && npm install && npx vite build && cd ..
```

> ⚠️ 用 `npx vite build`，**不要 `npm run build`**（后者是 `vite build && electron-builder`，会触发打包）。
> ⚠️ 本机系统 `Python312` 与 PATH 上的 `python` 都缺 `mss`，未做 A 步骤时 Electron 自启后端会报 `ModuleNotFoundError`。A 步骤**尚未执行**，需你确认后自行跑；它只改系统 Python，不动仓库。`waitress` 不在 `requirements.txt`，但是 Electron 探测解释器的必要条件。

### 三种启动方式

| 模式 | 操作 | 用途 |
|---|---|---|
| 日常（推荐） | 装齐系统 Python 依赖后**双击 `start.vbs`**（或 `start.bat`） | 完整桌面应用；Electron 自动 spawn 后端并设好 `CHALLENGE_DAILY_DATA_DIR` |
| 两段式 | 先 venv 起后端 → 等 `/api/health` 200 → 再起 Electron（`ELECTRON_IS_DEV=0`，cwd=`client`） | 不改系统环境；Electron 检测有效 token 后 `skip spawning` 复用后端 |
| 纯后端 | `python -u main.py` | 只调 API，无窗口 |

```powershell
# 两段式（普通 PowerShell 控制台；完整命令与说明见 HANDOFF.md §4.2）
$root = 'E:\WorkBuddy\2026-09-05-19-07-53\ChallengeDaily-main\ChallengeDaily-main'
$py   = 'C:\Users\54711\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
$env:CHALLENGE_DAILY_DATA_DIR = 'C:\Users\54711\AppData\Roaming\challenge-daily\backend-data'
$env:PORT = '58888'
Start-Process -FilePath $py -ArgumentList '-u','main.py' -WorkingDirectory $root -WindowStyle Hidden
for ($i=0; $i -lt 30; $i++) { try { (Invoke-WebRequest 'http://127.0.0.1:58888/api/health' -UseBasicParsing).StatusCode; break } catch { Start-Sleep -Seconds 1 } }
$env:ELECTRON_IS_DEV = '0'
Start-Process -FilePath "$root\client\node_modules\electron\dist\electron.exe" -ArgumentList '.' -WorkingDirectory "$root\client"
```

> 在 WorkBuddy 终端里须先 `unset ELECTRON_RUN_AS_NODE PYTHONPATH` 并设 `CODEBUDDY_SAFE_DELETE_ENABLED=0`；且工具进程的常驻子进程会被沙箱回收，**要长期运行请从 Explorer 双击启动**。

窗口出现即开始采集（默认每 60 秒，自适应 30–120 秒）。后端 `http://127.0.0.1:58888`：`/api/health` 无需 token，其余 `/api/*` 需 `X-API-Token`（值在 `<DATA_DIR>\.api_token`）。数据写 `%APPDATA%\challenge-daily\backend-data\xiaohei.db`。

### 服务器存储 / 浏览器远程访问

**所有客户端状态都存在服务器，不再写浏览器 `localStorage`**：首启协议、新手引导、主题外观、应用锁配置、校准提示等原本落在浏览器的数据，统一由 `GET/PUT /api/client-state` 读写，落盘到 `<DATA_DIR>\client_state.json`（单租户、无账号）。业务数据本就在 SQLite。前端启动时一次性拉全量状态到内存缓存，之后同步读写缓存并防抖回写服务器；旧版浏览器里的 `cd_*` 键会在首次启动自动迁移到服务器并清除本地副本。该文件已纳入备份 / 恢复 / 数据自毁范围。

Web 模式（`run-challengedaily-web.bat`）默认让浏览器走**页面同源 `/api/*` 代理**（shim 返回端口 `0`），因此远程浏览器访问 `http://<服务器IP>:5173` 时，API 请求会打到页面所在服务器，而不是客户端自己的 `127.0.0.1`。要点：

- 后端 `HTTP_HOST` 保持 `127.0.0.1`（仅本机监听，由 ui-server 代理转发，无需暴露 58888）；
- ui-server 需监听 `0.0.0.0` 才能被远程访问（见下）；
- 鉴权沿用现有 `X-API-Token`，shim 从 `<DATA_DIR>\.api_token` 读取并注入，无账号体系；
- 如需恢复旧的本机直连调试，设 `CD_BACKEND_DIRECT=1`。

> 远程访问：启动 ui-server 前设 `CD_UI_HOST=0.0.0.0` 即可（`ui-server.js` 默认监听 `127.0.0.1`）。`ui-server.js` 与 `run-challengedaily-web.bat` 位于项目外层工作区根目录。⚠️ token 是唯一凭据，开放监听前请自行做好网络隔离 / 防火墙。

> 🧠 不配 Key 也能用（30+ 规则本地分类）。接智谱 / DeepSeek / Qwen / Kimi 的 OpenAI 兼容 Key 开启 AI 视觉识别，Key 由 Windows DPAPI 加密存本地。
> 📦 版本管理与发布见 [`RELEASE.md`](RELEASE.md)（已按本仓库实际重写：当前**无** Actions 自动打包 / Release / 客户端自动更新，只有源码提交与手动版本号管理）。

---

## 🧰 技术栈

```
⚡ Electron 31  ·  ⚛️ React 18 + TS (Vite)  ·  🐍 Python 3.10+（本机 3.13.14）  ·  🌶️ Flask 3
🗄️ SQLite WAL  ·  🖼️ glm-4.1v-thinking-flash（429 降级 glm-4v-flash）  ·  📝 glm-4-flash  ·  🔐 Windows DPAPI
```

✅ 已通过 3 轮深度审计 + 30+ 项 Loop Engineering 修复，核心链路在本地环境连续验证通过。
📌 当前版本 `3.4.1`；2026-11-07 核对：代码基线 `20403f6`（其后为文档提交）、分支 `master`、前端 `dist` 已构建、端口 58888 未运行、运行时库在 `%APPDATA%\challenge-daily\backend-data`。

---

| 平台 | 仓库 |
|------|------|
| 🐙 **本仓库（私有）** | [q547113058-max/ChallengeDaily](https://github.com/q547113058-max/ChallengeDaily)（分支 `master`） |
| 🐙 上游（MIT） | [EXtreameChallenge/ChallengeDaily](https://github.com/EXtreameChallenge/ChallengeDaily) |
| 🏮 Gitee | [EXtreameChallenge/ChallengeDaily](https://gitee.com/EXtreameChallenge/ChallengeDaily) |
| 🦊 GitCode | [EXtreameChallenge/ChallengeDaily](https://gitcode.com/EXtreameChallenge/ChallengeDaily) |

📌 灵感：[samlaying/xiaohei-daily](https://github.com/samlaying/xiaohei-daily)（仅 macOS） ·  MIT License
📄 交接文档：[HANDOFF.md](HANDOFF.md) · 审查报告：[REVIEW_2026-09-10.md](REVIEW_2026-09-10.md)
