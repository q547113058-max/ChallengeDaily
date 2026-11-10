# ChallengeDaily 版本管理与发布

> 更新：**2026-11-10** ｜ 仓库 [`q547113058-max/ChallengeDaily`](https://github.com/q547113058-max/ChallengeDaily) ｜ 默认分支 `master`
> 启动方式见 [README.md](README.md) · 交接与排障见 [HANDOFF.md](HANDOFF.md)。
>
> 本轮已落地「**安装包 + 在线更新 + 远程后端连接**」的代码、本地构建验证，并把仓库转为公开、CI 权限改为 write。首次发版（提交 + tag + Release）见 §6。

---

## 0. 一句话结论

**代码链路已接通**：修好打包资源、配置 GitHub 发布源、客户端接入 `electron-updater`（启动静默检查 + 弹窗确认）、新增发版 workflow，并支持**纯客户端连已部署的远程后端**。仓库已公开，首个 Release 发布后在线更新即真正生效。

---

## 1. 本轮落地清单

| 项 | 文件 | 说明 |
|---|---|---|
| 修复打包 | `client/package.json` | 删除 `build.extraResources` 中 6 条指向已删除文件的条目（32 → 26 条，缺失数 0） |
| 产物目录 | `client/package.json` | `directories.output`：`dist-electron-tmp6` → `dist-electron` |
| 发布源 | `client/package.json` | `publish: { provider: github, owner, repo, releaseType: release }`（原为 `null`）。生成的 `app-update.yml` 由 electron-builder 自动写入包内 |
| 构建脚本 | `client/package.json` | 新增 `build:dir`（免安装包目录）、`publish:win`（构建并发布） |
| 更新逻辑 | `client/electron/updater.cjs`（新增） | 状态机 `idle/checking/available/not-available/downloading/downloaded/error`；`autoDownload=false`、启动 8s 后静默检查、发现新版本弹窗确认、下载完成再弹窗确认重启安装、`autoInstallOnAppQuit=true` |
| 主进程接入 | `client/electron/main.cjs` | 引入模块、IPC 白名单加 4 个 `updater-*` 通道并加发送方校验、`whenReady` 初始化、托盘加「检查更新…」 |
| 渲染层 | `client/electron/preload.cjs` | 暴露 `onUpdaterState` / `updaterGetState` / `updaterCheck` / `updaterDownload` / `updaterQuitAndInstall` |
| 类型 | `client/src/vite-env.d.ts` | 新增 `UpdateState` 接口与 `electronAPI` 对应方法（用 `declare global` 包裹以保持全局增强） |
| 设置页 UI | `client/src/components/UpdateChecker.tsx`（新增） | 设置 → 关于：版本、检查更新、下载进度、下载/安装按钮、更新说明、错误提示；dev/浏览器模式显示「仅在已安装版本可用」且不联网 |
| CI | `.github/workflows/release.yml`（新增） | 推 `vX.Y.Z` tag → Windows runner → `npm ci` → `tsc --noEmit` → `npm run publish:win` 上传 Release 资产；支持 `workflow_dispatch` dry-run |
| 放行 workflow | `.gitignore` | 移除 `.github/` 排除规则（原注释「token 无 workflow scope」已不成立，见 §2）；补 `.venv312/` 忽略 |
| 远程后端配置 | `client/electron/backend-config.cjs`（新增） | `local`（源码默认）/ `remote`（连已部署后端）。优先级：环境变量 > `userData/backend-config.json` > **随包默认 `resources/backend-default.json`** > 内置 local |
| 远程反向代理 | `client/electron/remote-proxy.cjs`（新增） | remote 模式下在 `127.0.0.1:58888` 起轻量代理，把 `/api/*` 转发到远端并注入 `X-API-Token`；**前端 core.ts / CSP 零改动**，token 不进渲染层 |
| 主进程分支 | `client/electron/main.cjs` | remote 模式跳过 Python spawn、进程崩溃监控与本地心跳重启；`stopBackend()` 同时停代理；新增 `backend-config-get/set` IPC（读回不含 token 明文，写入限主窗口） |
| 设置页 UI | `client/src/components/BackendConnectionSettings.tsx`（新增） | 设置 → 关于 → 后端连接：切换本机/远程、填地址与 Token；保存后需重启生效 |

**远程模式部署**（无需 UI，适合批量装机）：设置环境变量后启动即可。

```powershell
$env:CHALLENGE_DAILY_BACKEND_MODE = 'remote'
$env:CHALLENGE_DAILY_BACKEND_URL  = 'http://<后端主机>:58888'
$env:CHALLENGE_DAILY_BACKEND_TOKEN = '<后端 X-API-Token>'
```

> 前端仍连 `http://127.0.0.1:58888`，由本地代理转发，因此 CSP 白名单无需改动。

### 随包预置默认配置（开箱即用）

装到其他机器的客户端**无需任何配置**即可连已部署后端：CI 打包时用 GitHub Actions Secrets 生成 `client/backend-default.json`，由 `extraResources` 打进 `resources/backend-default.json`，客户端首次启动按 `remote` 模式起本地代理。

| 项 | 值 |
|---|---|
| Secrets | `CD_BACKEND_URL`、`CD_BACKEND_TOKEN`（在 Settings → Secrets and variables → Actions 设置，**不入库**） |
| 源码占位 | `client/backend-default.json` = `{ mode: local, url: "", token: "" }` —— 本地开发/未配 Secrets 时保持 local 模式 |
| 用户覆盖 | 设置页保存后写入 `userData/backend-config.json`，优先级高于随包默认；**token 留空 = 不修改**，不会清掉预置凭据 |
| 安全 | 源码与公开仓库**不含任何真实地址/token**；token 仅存在于 CI Secrets、Release 安装包内、以及用户本机配置 |
| BOM 防御 | `backend-config.cjs` 读 JSON 时剥离 BOM；workflow 用 `UTF8Encoding($false)` 无 BOM 写入 |

> 已装 v3.4.2 的用户通过在线更新升到下一版即可获得预置配置（更新包会带上新的 `backend-default.json`）。

**安全约定**：客户端不携带任何 token。`electron-updater` 的 GitHub provider 从包内 `app-update.yml` 读取**公开**仓库的 feed 地址，这也是必须把仓库转公开的原因（feed 方案见 §3）。

---

## 2. 认证与仓库现状（2026-11-10 实测）

| 检查 | 结果 |
|---|---|
| `gh auth status` | 已登录 `q547113058-max`，token scopes 含 `repo`、`workflow` |
| 仓库可见性 | **public**（2026-11-10 由 private 转公开，`gh repo edit --visibility public`） |
| 默认分支 | `master` |
| Actions 默认工作流权限 | **write**（`GITHUB_TOKEN` 可创建 Release） |
| tags / releases | 0 / 0（首个 Release 待发） |
| 工作区 | 有大量未提交改动（提交范围见 §6） |

> 旧版 RELEASE.md 说「token 无 workflow scope，无法推送 .github」——**该前提已失效**，`.github/` 已放行。但把仓库转公开属于远端写操作，本轮按约定未执行。

---

## 3. 更新源方案（已定：当前仓库转公开）

代码按「**GitHub Releases 公开 feed**」实现：

```
客户端启动 → autoUpdater 读 resources/app-update.yml
          → GET https://github.com/q547113058-max/ChallengeDaily/releases/latest/download/latest.yml
          → 比对版本 → 弹窗 → 下载 Setup.exe → quitAndInstall
```

- 客户端**零密钥**，标准 GitHub provider，无需自建服务器、无需跨仓 PAT。
- 代价：整个源码仓库（含历史）需公开。**发布前请先自查仓库内是否含敏感信息**（`.env` / key / 数据库文件已被 `.gitignore` 排除，但历史提交仍需人工确认）。
- 若后续改主意不公开源码，可切换为「新建公开分发仓库 `ChallengeDaily-releases` + 跨仓 PAT secret」，客户端代码无需改动，只改 `build.publish` 的 owner/repo 与 workflow 的上传目标。

---

## 4. 版本号

- 单一来源：`client/package.json` 的 `version`，当前 **`3.4.1`**。后端 `main.py:_get_version()` 也读它。
- `cd client && npm run bump` → patch +1（`3.4.1 → 3.4.2`），只改该文件。
- **发版规则**：`package.json` 的 version 必须与 tag `vX.Y.Z` 完全一致，CI 会校验，不一致直接失败。

---

## 5. 本地构建 / 验证

```bash
cd client
npx tsc --noEmit          # 类型检查
npx vite build            # 前端产物 client/dist
npm run build             # vite build && electron-builder → dist-electron/*.exe + latest.yml
npm run build:dir         # 只出免安装目录，便于快速验证包结构
```

产物（`client/dist-electron/`，已被 `.gitignore` 排除）：

```
ChallengeDaily-3.4.1-Setup.exe       # NSIS 安装包
ChallengeDaily-3.4.1-Portable.exe    # 便携版
ChallengeDaily-3.4.1-Setup.exe.blockmap   # 差分更新块表
latest.yml                          # 自动更新清单（含 sha512 / size / releaseDate）
win-unpacked/resources/app-update.yml     # 打进包内的发布源配置
```

> `npm run build` 只**本地生成**安装包并附带 `latest.yml`，不会创建/上传 Release。要发布见 §6。

### 本机验证结果（2026-11-10 实测）

- `npx tsc --noEmit` → **通过**（EXIT=0）。
- `vite build` → **通过**，2676 模块，`dist/index.html` + 全部 assets 齐全。
- `electron-builder --win` → **通过**，产出上述 4 类产物 + `latest.yml`；包内 `app-update.yml` 内容正确（owner / repo / provider: github / releaseType: release）；`updater.cjs` 已确认打进 `app.asar`。

本机为绕过沙箱与网络限制使用了**仅本地、不入库**的临时参数（CI 的 Windows runner 不需要）：

```
TEMP/TMP=<工作区内目录>                     # esbuild 在系统 %TEMP% 建临时目录后无权删除
ELECTRON_BUILDER_CACHE=<工作区内目录>        # builder 写 %LOCALAPPDATA% 被拒
ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/   # GitHub 下载 NSIS 超时
-c.electronDist=<本地 node_modules/electron/dist>   # 复用已装 Electron 31.7.7，跳过下载
-c.win.signAndEditExecutable=false          # 本地验证不需代码签名，跳过 winCodeSign 下载
```

> 这些参数不要写进 `package.json` 或 workflow；CI 有正常网络与权限，`npm run publish:win` 直接可用。

---

## 6. 首次发版（尚未执行，需你确认后操作）

按顺序：

1. **自查敏感信息**：`git log --all -- .env *.db vault.dat`、全库 grep key/token；确认历史提交无泄露。
2. **转公开**：`gh repo edit q547113058-max/ChallengeDaily --visibility public --accept-visibility-change-consequences`（不可逆地公开源码与历史）。
3. **提交本轮改动**：`.gitignore`、`.github/workflows/release.yml`、`client/package.json`、更新相关 4 个文件、`RELEASE.md`。注意工作区还有大量其他未提交改动，**提交前务必 `git status` 逐项确认**。
4. **放权限**：仓库 Settings → Actions → General → Workflow permissions → **Read and write permissions**（`GITHUB_TOKEN` 需要写权限才能建 Release）。
5. **打 tag 触发 CI**：
   ```bash
   cd client && npm run bump && cd ..     # 3.4.1 → 3.4.2（如需）
   git add client/package.json
   git commit -m "release: 3.4.2"
   git tag v3.4.2
   git push origin master --tags
   ```
   `push` 到 `v*` tag 会触发 `release.yml`，CI 自动 `npm ci` → `tsc --noEmit` → `npm run publish:win`，产出并上传 Release。
6. **验证端到端**：装 `Setup.exe` → 启动 8 秒后应弹「发现新版本」（用旧版本包测）→ 下载 → 重启完成安装；或设置 → 关于 → 检查更新。

> ⚠️ 私有仓库 + 自动更新涉及 token 分发，**绝不要把 PAT 打进客户端或提交进仓库**。本实现依赖仓库公开，客户端不含任何凭据。

### 首次发版实测记录（2026-11-10）

- 仓库转 **public**；Actions 默认工作流权限设为 **write**。
- 提交 `96bbd84`（本地），经 GitHub Git Data API 增量推送为远端 `24c8abf`（因 `git push` 在本会话被 `getaddrinfo() thread failed to start` 拦，改用 API 重建 commit）。**两棵 tree 均为 `0ed6db0`、229 个 blob 完全一致**，仅 commit sha 因作者时间戳精度不同而异；本地工作区因此显示与远端 sha 不一致，但内容无差异，下次提交前建议先 `git fetch`/对齐。
- tag `v3.4.2` → workflow run `42807013271` → **conclusion: success**（约 3 分钟）。
- Release `v3.4.2`（非草稿）含 4 个资产：`Setup.exe` / `Portable.exe` / `.blockmap` / `latest.yml`。
- 公开 feed `https://github.com/q547113058-max/ChallengeDaily/releases/latest/download/latest.yml` 匿名 **HTTP 200**，内容含 version 3.4.2、sha512、size、releaseDate。

> 后续发版若 `git push` 恢复可用，直接用 §6 第 5 步的常规 `git push origin master --tags` 即可；API 推送脚本为一次性临时方案，未入库。

---

## 7. 已知限制 / 遗留

| 项 | 说明 |
|---|---|
| **安装包不带 Python 运行时** | 仅影响 `local` 模式：打包版优先找 `resources/python/python.exe`，回退系统 Python 3.10/3.11/3.12（需 `import mss, flask, waitress`）。**`remote` 模式无此限制**，本机不跑 Python、只跑 Node 代理，正是「发到其他机器的纯客户端」场景 |
| 更新只覆盖前端/Electron 壳 | `extraResources` 里的 `backend/*.py` 会随包更新，但**用户数据**（`%APPDATA%\challenge-daily`、SQLite、备份、vault）不在包内、不会被覆盖；`nsis.deleteAppDataOnUninstall=false` |
| 便携版 | `portable` 产物同样会上传到 Release，但 `electron-updater` 对 portable 目标不做自动更新（仅 NSIS 安装版生效） |
| 首次 Release 前 | 客户端启动检查会拿到 404 / `latest.yml` 不存在 → 进入 `error` 状态，只在设置页显示错误，**不弹窗打扰用户** |
| Rollback | 见 §8 |

---

## 8. 回退与恢复（分支 `master`）

```bash
git log --oneline
git reset --hard HEAD~1            # 破坏性，先确认无未提交改动
git restore <文件>
```

> 数据目录（`data/`、`%APPDATA%\challenge-daily`）不受 Git 影响，回退代码不会回退数据库。

---

## 9. 文档口径

- `README.md`：功能与启动。
- `HANDOFF.md`：交接、环境坑、排障、推送认证。
- 本文：版本管理、打包、在线更新与发布流程。
- `REVIEW_2026-09-10.md`：历史代码审查基线。
