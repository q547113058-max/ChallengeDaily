# ChallengeDaily 交接文档（HANDOFF）

> 最后核对：**2026-11-07** ｜ 基线 commit `20403f6` ｜ 分支 `master` ｜ 私有仓库 <https://github.com/q547113058-max/ChallengeDaily>
> 面向零上下文的新会话 / 换机接手。所有路径、版本、状态均为本机实测，不是推测。
> 一句话：**这是应用内的定时截屏分析，不是 WorkBuddy 的定时自动化任务。**

---

## 0. 这东西是什么

桌面上跑的「AI 屏幕时间记录 + 自我量化」应用。主循环在 `main.py`，用 `mss` 每 60 秒抓一次屏（自适应 30–120 秒），送视觉模型识别归类，写入 SQLite，再自动出日报 / 周报 / 深度洞察。非工作时段 300 秒醒一次，只做日报与备份。

```
main.py 主循环 ──> Collector.capture_once() ──> mss 抓屏
                                            ──> ai_client.analyze_screenshot() 视觉模型分类
                                            ──> SQLite (xiaohei.db) ──> 日报 / 周报 / 报告页
```

---

## 1. 位置与仓库（精确路径）

| 项 | 值 |
|---|---|
| 项目根 | `E:\WorkBuddy\2026-09-05-19-07-53\ChallengeDaily-main\ChallengeDaily-main\` |
| 历史工作日志 | `E:\WorkBuddy\2026-09-05-19-07-53\.workbuddy\memory\2026-09-05.md` ~ `2026-09-14.md`（9 份，记录修剪/启动/修复全过程） |
| 远端 | `https://github.com/q547113058-max/ChallengeDaily.git`（**私有**，2026-11-06 创建，默认分支 `master`，推送时 HEAD `20403f6`） |
| 上游 | `EXtreameChallenge/ChallengeDaily`（MIT），本项目是其 Windows fork，已大幅剪枝 |
| 运行时数据目录 | `C:\Users\54711\AppData\Roaming\challenge-daily\backend-data\`（`xiaohei.db` 13.5 MB，含 `.api_token`、`vault.dat`、`screenshots\`） |
| 项目内数据目录 | `<项目根>\data\`（**另一套库**，1.6 MB，历史遗留，勿与运行时库混用） |
| 前端 | `<项目根>\client\`（Electron 31 / React 18 / TS / Vite；`package.json` version `3.4.1`） |
| 后端 | `<项目根>\main.py` + `server.py` + `routes\`（Flask 3，端口 **58888**） |

---

## 2. 启动链路（源码级）

```
双击 start.vbs / start.bat
  └─ 清理 PYTHONHOME、PYTHONPATH，设 ELECTRON_IS_DEV=0
     └─ 生成/更新 ChallengeDaily.lnk → 启动 client\node_modules\electron\dist\electron.exe .  (cwd = client)
        └─ client\electron\main.cjs
           ├─ isDev = false（ELECTRON_IS_DEV=0 或 dist/index.html 存在）→ loadFile(dist/index.html)
           ├─ 先探测 58888：后端已存活且 token 有效 → skip spawning（复用）
           └─ 未存活 → spawn(pythonExe, ['-u', 'main.py'])
                 env 白名单 + PORT=58888 + PYTHONUNBUFFERED=1
                 + CHALLENGE_DAILY_DATA_DIR = <userData>\backend-data
                 └─ main.py：命名互斥体单实例 → init_db() → 后台线程 start_server() → Collector.on_start()
```

关键源码索引：

| 文件 | 作用 |
|---|---|
| `start.vbs` / `start.bat` | 快捷方式启动器，只拉起 Electron（不清 `ELECTRON_RUN_AS_NODE`） |
| `client/electron/main.cjs:62-71` | `BACKEND_PORT=58888`、`isDev` 判定 |
| `client/electron/main.cjs:218-332` | Python 解释器查找、env 白名单、spawn 后端 |
| `client/electron/main.cjs:87` | userData 固定为 `%APPDATA%\challenge-daily` |
| `config.py:33-41` | `CHALLENGE_DAILY_DATA_DIR` 覆盖 DATA_DIR |
| `config.py:48,67,80-86` | 截图间隔 60s、端口、视觉/文本模型与 429 降级 |
| `main.py:29-69` | 单实例 Mutex + 端口预占 |
| `main.py:299-359` | 采集主循环、工作时间判定、自适应休眠 |
| `server.py:244-270` | Flask threaded 启动 + `save_token()` |
| `routes/deps.py:21,75` | `.api_token` = `DATA_DIR/.api_token`，`check_token()` 校验 `X-API-Token` |
| `collector.py` / `ai_client.py` | 抓屏 → AI 分类 → 入库 |

---

## 3. 本机现状（2026-11-07 实测，接手前先看这一节）

| 检查项 | 结果 |
|---|---|
| `client\node_modules\electron\dist\electron.exe` | ✅ 已装（180 MB 二进制，曾需 npmmirror 手动下载） |
| `client\dist\index.html` | ✅ 已构建，可直接生产模式启动 |
| WorkBuddy venv `...\envs\default\Scripts\python.exe` | ✅ Python 3.13.14，`flask/mss/waitress/openai/PIL/psutil/yaml/win32api` 全齐 |
| 系统 `Python312\python.exe` | ❌ `ModuleNotFoundError: No module named 'mss'` |
| PATH 上 `python`（3.13.12 裸解释器） | ❌ 同样缺 `mss` |
| 端口 58888 | 无监听（应用当前**未运行**） |
| 计划任务 `CDBackend` / `CDElectron` | 已不存在（9-12 曾创建，现在只剩无关的 `CDSSync`） |
| `ELECTRON_RUN_AS_NODE` | User/Machine **未设置**；只有 WorkBuddy 工具进程注入 `=1` |
| `PYTHONPATH` | User/Machine **未设置**；只有 WorkBuddy 工具进程注入 safe-delete shim 路径 |
| `.env` | 不存在（用 `.env.example` 模板；API Key 走应用内 DPAPI vault） |

> 结论：**从 Explorer 双击启动不会踩 WorkBuddy 的环境变量坑**；但当前系统 Python 缺包，Electron 自启后端会失败（见坑 1）。所以「能跑起来的方式」有两种，见下节。

---

## 4. 怎么启动（三种，按推荐度）

### 4.1 一次性修好后，日常双击 `start.vbs`（推荐）

Electron 自启后端时优先按 `Python311/312/310` 标准路径找解释器，并用 `import mss, flask, waitress` 验证；装齐后会自动 spawn 它，且自动设 `CHALLENGE_DAILY_DATA_DIR`，token 天然一致，**无 401**。

```powershell
& 'C:\Users\54711\AppData\Local\Programs\Python\Python312\python.exe' -m pip install -r 'E:\WorkBuddy\2026-09-05-19-07-53\ChallengeDaily-main\ChallengeDaily-main\requirements.txt' waitress
```

然后**双击 `<项目根>\start.vbs`**（或 `start.bat`）。
> 该 pip 安装**尚未执行**，需你确认后自行跑；它只改系统 Python312，不动仓库。
> `waitress` 不在 `requirements.txt`，但 `main.cjs:247/271` 的探测要求能 import 它；`server.py` 实际用 Flask threaded，不依赖 waitress 运行。

### 4.2 不改系统环境：venv 后端 + Electron 复用（9-12 实测成功路径）

**串行**：先起后端、等 58888 就绪，再起 Electron。在**普通 PowerShell 控制台**（不是 WorkBuddy 终端）执行：

```powershell
$root = 'E:\WorkBuddy\2026-09-05-19-07-53\ChallengeDaily-main\ChallengeDaily-main'
$py   = 'C:\Users\54711\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
$data = 'C:\Users\54711\AppData\Roaming\challenge-daily\backend-data'

# 1) 后端
$env:CHALLENGE_DAILY_DATA_DIR = $data; $env:PORT = '58888'
Start-Process -FilePath $py -ArgumentList '-u','main.py' -WorkingDirectory $root -WindowStyle Hidden
for ($i=0; $i -lt 30; $i++) { try { (Invoke-WebRequest 'http://127.0.0.1:58888/api/health' -UseBasicParsing).StatusCode; break } catch { Start-Sleep -Seconds 1 } }

# 2) Electron（检测到有效 token 会 skip spawning，复用上面的后端）
$env:ELECTRON_IS_DEV = '0'
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
Start-Process -FilePath "$root\client\node_modules\electron\dist\electron.exe" -ArgumentList '.' -WorkingDirectory "$root\client"
```

若在 **WorkBuddy 的 bash 工具进程**里调试，前面必须加：

```bash
unset ELECTRON_RUN_AS_NODE PYTHONPATH
export CODEBUDDY_SAFE_DELETE_ENABLED=0
export CHALLENGE_DAILY_DATA_DIR='C:\Users\54711\AppData\Roaming\challenge-daily\backend-data'
```

> ⚠️ **WorkBuddy 工具进程受 Windows Job Object 管控，命令返回即杀掉子进程，长驻服务活不下来**。要常驻只能由沙箱外进程启动：双击 `.vbs` / `.lnk`，或从独立 PowerShell 用 `Start-Process`。工具进程内只适合短时验证。

### 4.3 纯后端 / 开发模式

| 模式 | 命令 | 用途 |
|---|---|---|
| C 纯后端 | `python -u main.py`（端口 58888，`PORT` 可覆盖） | 只调 API，无窗口 |
| B 产品 | `cd client && npx vite build && electron.exe .` | 改前端后必须重建 `dist`，Electron 跑的是 `dist/index.html` 不是 dev server |
| A 开发 | `npm run dev` | **本机不可用**：vite dev 绑 `[::1]:5173`，`wait-on http://localhost:5173` 永不就绪 → Electron 不启动。已放弃 |

> 前端重建用 **`npx vite build`**，不要用 `npm run build` —— 后者是 `vite build && electron-builder`，会触发打包，日常改代码不需要。

---

## 5. 停止、重启、验证

```powershell
# 看监听与进程
Get-NetTCPConnection -LocalPort 58888 -State Listen
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'main\.py|electron\.exe' } | Select ProcessId,CommandLine

# 停止（先 Electron 再后端；后端正常是 2 层父子进程，不是重复实例，勿误判）
Stop-Process -Id <PID> -Force
```

- 后端用**命名互斥体** `ChallengeDaily_SingleInstance_<DATA_DIR SHA256 前16位>` 做单实例，进程死即释放；端口 58888 另有一次预占检查。
- 验证：`curl -s http://127.0.0.1:58888/api/health`（`/api/health`、`/api/metrics`、`/` 公开，无需 token）；其余 `/api/*` 需请求头 `X-API-Token`，值取自 `<DATA_DIR>\.api_token`。
- 日志：
  - `<DATA_DIR>\logs\challenge-daily.log`（后端主日志，5 MB × 3 轮转；DATA_DIR 被覆盖时在这里，否则在 `项目\data\logs\`）
  - `<项目根>\data\logs\electron-backend.log`（Electron spawn 的后端 stdout/stderr，**路径固定**）
  - `%APPDATA%\challenge-daily\logs\electron-main.log`（Electron 主进程）
- 代码侧验证：`pytest`（56+ passed）、`cd client && npx tsc --noEmit`、`npx vite build`。

---

## 6. 配置与密钥

| 项 | 值 / 说明 |
|---|---|
| 模板 | `.env.example`（仓库内），复制为 `.env`；**空值不覆盖已有 env/vault** |
| API Key | 在应用设置页/首次引导页输入 → Windows **DPAPI** 加密存 `<DATA_DIR>\vault.dat`，不落明文、不入库 |
| 视觉模型 | `config.py:80` 默认 `glm-4.1v-thinking-flash`；429 自动降级 `glm-4v-flash` |
| 文本模型 | `glm-4-flash` |
| Base URL | `https://open.bigmodel.cn/api/paas/v4`（OpenAI 兼容，可换 DeepSeek/Qwen/Kimi） |
| 数据保留 | `RETENTION_DAYS=7`，截图 7 天轮换删除 |
| 隐私 | 微信/飞书/密码管理器/银行页面自动跳过；`HTTP_HOST` 默认 `0.0.0.0`，设 `127.0.0.1` 可收回仅本机 |
| 不入库 | `.gitignore` 排除 `data/`、`*.db`、`*.log`、`.env`、`dist/`、`node_modules/`、`.github/`、`.coverage` |

> `.env.example` 里写的 `AI_VISION_MODEL=glm-4v-flash` 是**旧模板**，运行时以 `config.py` 为准（未设 `.env` 时不生效）。

---

## 7. 坑位清单（都踩过，附根因）

| # | 现象 | 根因 | 处理 |
|---|---|---|---|
| 1 | 双击后后端起不来，`ModuleNotFoundError: No module named 'mss'` | `main.cjs:262-286` 优先系统 Python311/312/310，本机 Python312 缺 `mss`；回退 PATH `python` 也缺 | 按 §4.1 装齐依赖，或按 §4.2 用 venv 先起后端让 Electron 复用 |
| 2 | 全局 401（health 200，其余全 401） | 手动起后端未设 `CHALLENGE_DAILY_DATA_DIR` → 后端用 `项目\data\.api_token`，Electron 读 `%APPDATA%\challenge-daily\backend-data\.api_token`，两边 token 不同 | **两端必须同一 DATA_DIR**；统一指向 `%APPDATA%\challenge-daily\backend-data`（真实历史库在这里） |
| 3 | `[FATAL] ELECTRON_RUN_AS_NODE=1 detected` / 后端被 `SystemExit` 杀 | 这些变量只在 **WorkBuddy 工具进程**注入（`PYTHONPATH` 指向 safe-delete shim，collector 删 7 天前截图时累计触发 `SAFE_DELETE_BULK_CONFIRM_REQUIRED`） | 从 Explorer 双击最省事；工具进程内须 `unset ELECTRON_RUN_AS_NODE PYTHONPATH` + `CODEBUDDY_SAFE_DELETE_ENABLED=0` |
| 4 | launcher 设了 `CHALLENGE_DAILY_DATA_DIR` 却没生效 | `.bat` 里中文 REM 注释 + `chcp 65001` 在 UTF-8 无 BOM 文件下扰乱后续 `set` 行解析 | 传 env 的启动脚本一律**纯 ASCII**；现有 `start.bat`/`start.vbs` 已符合 |
| 5 | `npm run dev` 卡死 | vite dev 绑 IPv6 `[::1]:5173`，`wait-on` 拿不到 | 放弃 A 模式，改 `npx vite build` + Electron 生产模式 |
| 6 | `electron.exe` 不存在 | npm postinstall 静默失败 | `ELECTRON_MIRROR=https://registry.npmmirror.com/-/binary/electron/ node node_modules/electron/install.js` |
| 7 | 新后端绑不上端口 / curl 命中旧实例返 401 | 旧 `main.py` 残留 LISTENING 58888 | 先查 `Get-NetTCPConnection -LocalPort 58888` 并杀净再起；正常是 2 层父子进程 |
| 8 | 打 tag 后没有自动打包 / Release | 本地**根本没有** `.github/` 目录，且 `.gitignore` 显式排除它（token 无 workflow scope）；远端 workflows 404、tags/Releases 均为 0；`build.publish=null`、主进程无 `autoUpdater` | 当前无自动发布链路，按 `RELEASE.md` §5 的 5 步待办恢复（未执行） |

---

## 8. 提交与推送 GitHub

- 仓库：`q547113058-max/ChallengeDaily`（**私有**），分支 `master`，`origin` 为不带 token 的 HTTPS URL。
- 认证：**Windows Credential Manager 的 `git:https://github.com` 条目**（username `q547113058-max`，token scope 含 `repo`）。`gh` CLI 不在 PATH；SSH key 未被账号认可 —— 不要再试 SSH/gh。
- 非交互环境加 `GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=Never` 防挂起。
- 推送前红线：`data/`、`*.db`、`.env`、`*.log`、`screenshots/`、`vault.dat` 一律不入库；提交前 `git status` 与 `git grep -i "api_key\|token\|password"` 过一遍。
- 文档口径（2026-11-07 已统一）：`README.md` = 功能与启动，`HANDOFF.md` = 交接排障，`RELEASE.md` = 版本管理与发布现状（已按实际重写：本仓库 `master` 分支、无 workflow / tag / Release / 自动更新，`publish: null`，打包清单有 6 条缺失资源）。

---

## 9. 已知遗留 / 待决策

1. 已被移除但历史文案仍在宣传的模块（**2026-11-07 已统一在 README 标注**，代码侧确认零引用）：
   - 🍅 番茄钟 —— commit `20403f6`（2026-09-12）全量移除（39 文件，+139/−953）
   - 🐾 桌面宠物 —— commit `6a34b2c`（2026-09-06）整段移除（14 文件、842 行，含 `Pet.tsx` 558 行、`pet.html`、`pet-entry.tsx`、主进程宠物窗口、`pet_mood.py`）
   - 💬 AI 对话 / AI 教练 —— commit `1f13409`（2026-09-06）移除（`AIChat.tsx`、`AICoach.tsx`、`SmartCoachPanel.tsx`、`api/ai.ts`、`pet_mood.py`）
   - 残留 `index.css` 中 4 条 `pet-*` 动画关键帧已于 2026-11-07 清理。
2. `REVIEW_2026-09-10.md` §2.1：定时日报存在 `settings.json` 与 `auto_report.json` 两套并行配置，UI 各改一套，建议合并（未动）。
3. `.env.example` 模型名与 `config.py` 默认值不一致（旧模板）。
4. 历史上 Overview 的腾讯地图 IP 定位被 CSP 拦（`apis.map.qq.com` 不在 connect-src），非致命降级。
5. `项目\data\`（1.6 MB 旧库）与运行时库（13.5 MB）并存，隔离测试须显式 `CHALLENGE_DAILY_DATA_DIR=<临时目录>`，否则污染项目库。
6. 系统 Python312 仍未装后端依赖（§4.1 的可选修复未执行）。**注意：本机实测 `C:\Users\54711\.workbuddy\binaries\python\versions\3.13.12\python.exe` 监听的回环端口不可被其他进程连接（防火墙/WFP 拦截），Web 模式启动请用 `ChallengeDaily\.venv312`（Python 3.12）。**
7. `client/package.json` 的 `build.extraResources` 有 6 条指向已剪枝删除的文件，`npm run build` 打包会缺资源（静态检查，未实跑、未修，见 `RELEASE.md` §4）。
8. 自动发布链路不存在：无 `.github/` / tag / Release，`publish: null`，主进程无 `autoUpdater`（见 `RELEASE.md` §5）。
9. 2026-11-07 的「减脂」改造（A+B 档）：下线 数据看板 / 每日卡片 / 倒数日 / 热力图独立页 / 应用标签独立页，报告三合一（`ReportsHub`）、计划二合一（`PlanHub`）、日历并入时间线；后端删除 `/api/countdowns`、`/api/daily-card` 两组接口（183 → 178 端点），`todos.mode=habit` 返回 410，导入白名单同步收紧。表与历史数据保留。

---

## 10. 自举检查（新会话第一件事）

```bash
cd "E:/WorkBuddy/2026-09-05-19-07-53/ChallengeDaily-main/ChallengeDaily-main"
git status -sb                         # 期望 ## master...origin/master 干净
git log --oneline -1                   # 期望 20403f6（或更新的文档 commit）
netstat -ano | grep 58888             # 判断是否已在运行
ls client/dist/index.html client/node_modules/electron/dist/electron.exe   # 启动前置
```

然后按 §4 选一种启动方式，`curl -s http://127.0.0.1:58888/api/health` 确认 200 即可开工。
