# ChallengeDaily 版本管理与发布（当前实际状态）

> 核对：**2026-11-07** ｜ 仓库 [`q547113058-max/ChallengeDaily`](https://github.com/q547113058-max/ChallengeDaily)（**私有**）｜ 默认分支 `master` ｜ 核对时 HEAD `cedd020`
> 本文按**本仓库当前实际**编写。旧版描述的是上游 `EXtreameChallenge/ChallengeDaily` 的理想流程（`main` 分支 + GitHub Actions 自动打包 + 客户端自动更新），本仓库均不具备，已按实测重写。
> 启动方式见 [README.md](README.md) · 交接与排障见 [HANDOFF.md](HANDOFF.md)。

---

## 0. 一句话结论

**当前没有自动发布链路。** 无 workflow、无 tag、无 Release、无客户端自动更新；`npm run build` 的打包清单还引用了 6 个已剪枝删除的文件。能正常用的是：**源码提交 + 手动版本号管理**。

---

## 1. 旧文档说法 vs 实际（含证据）

| 旧版 RELEASE.md 写法 | 本仓库实际 | 证据 |
|---|---|---|
| `cd xiaohei-daily` | 项目根 `E:\WorkBuddy\2026-09-05-19-07-53\ChallengeDaily-main\ChallengeDaily-main` | 本机路径 |
| `git branch -M main` / `git push -u origin main` | 私有仓库默认分支 **`master`**，`origin` 已存在，只有一条 `master` 分支 | GitHub API `/branches`、本地 `git remote -v` |
| 版本号示例 `2.6.1 → 2.6.2` | 当前 **`3.4.1`** | `client/package.json:3` |
| 打 tag → GitHub Actions 自动打包 → 自动建 Release | **整条链不存在**：本地无 `.github/` 目录，远端 `.github/workflows` 返回 404；tags 0 个、Releases 0 个 | `ls .github`、GitHub API |
| `npm run build` 产出 `Setup.exe` | `build.extraResources` 32 条中 **6 条指向已删除文件**，打包会缺资源 / 报错（静态检查，未实跑） | `client/package.json:114-246` |
| 「确保 `publish` 配置指向正确的 GitHub 仓库」 | `"publish": null`（**未配置任何发布目标**） | `client/package.json:113` |
| 「用户启动自动检测新版本」 | 主进程 `client/electron/main.cjs` **零** `autoUpdater` / `checkForUpdates` 引用；`electron-updater` 只在 dependencies 里，没被使用 | 全文件 grep 无命中 |
| 提示输入 GitHub 密码用 PAT | 认证走 **Windows Credential Manager** 的 `git:https://github.com` 条目；`gh` 不在 PATH，SSH key 未被账号认可 | 2026-11-06 推送实测 |

---

## 2. 当前可用：日常提交

```bash
cd "E:/WorkBuddy/2026-09-05-19-07-53/ChallengeDaily-main/ChallengeDaily-main"
git status -sb
git add <具体文件>
git commit -m "feat: xxx"
GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=Never git push origin master
```

提交前缀：`feat` / `fix` / `ui` / `refactor` / `docs` / `chore` / `release`。

**推送认证**：Windows Credential Manager 中 `git:https://github.com`（username `q547113058-max`，token scope 含 `repo`，**不含 `workflow`**）。不要试 SSH 或 `gh` CLI。非交互环境加 `GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=Never` 防挂起。

**红线**：`data/`、`*.db`、`.env`、`*.log`、`screenshots/`、`vault.dat`、`client/dist/`、`node_modules/` 一律不入库（`.gitignore` 已排除）。提交前 `git status` + 敏感词 grep 过一遍。

---

## 3. 版本号（当前唯一在跑的版本机制）

- 单一来源：`client/package.json` 的 `version`，当前 `3.4.1`。后端 `main.py:_get_version()` 也读它，所以**改这一处即可**。
- `cd client && npm run bump` → `client/scripts/bump-version.cjs`：把 patch 位 +1（`3.4.1 → 3.4.2`），重写 `package.json`，**不建 tag、不推远端、不改其他文件**。

| 位 | 含义 | 示例 |
|---|---|---|
| 第 1 位 | 不兼容大版本 | `4.0.0` |
| 第 2 位 | 新增功能 | `3.5.0` |
| 第 3 位 | 修复 / 小优化 | `3.4.2` |

> 当前版本号的**唯一实际消费者**是应用启动横幅与安装包文件名；没有 tag / Release 与之绑定。

---

## 4. 本地打包（现状：需先修复，别直接跑）

`client/package.json` 的 `npm run build` = `vite build && electron-builder`，配置目标为 Windows `nsis` + `portable`（x64），输出目录 `client/dist-electron-tmp6`，产物 `ChallengeDaily-3.4.1-Setup.exe` / `ChallengeDaily-3.4.1-Portable.exe`。

**阻断项（静态检查）**：`build.extraResources` 32 条里，6 条 `from` 指向 2026-09 剪枝时已删除的文件：

```
../mubu_sync.py                 ../routes/mubu_routes.py
../install_deps.py              ../db_consistency_check.py
../feature_flags.py             ../screenshot_redactor.py
```

复检命令：

```bash
python -c "import json,pathlib;d=json.loads(pathlib.Path('client/package.json').read_text(encoding='utf-8'));print([e['from'] for e in d['build']['extraResources'] if not (pathlib.Path('client')/e['from']).exists()])"
```

修复方式就是从 `extraResources` 删掉这 6 条，再跑 `npx vite build && npx electron-builder`。**本次只记录，未改动 `package.json`、未实跑打包。**

> 还有一处运行期依赖：打包版主进程会找 `resources/python/python.exe` 或系统 Python311/312/310 并要求能 `import mss, flask, waitress`（`main.cjs:242-255`）。本机系统 Python312 缺 `mss`，所以安装包在目标机器上仍需按 [HANDOFF.md §4.1](HANDOFF.md) 装齐后端依赖，否则后端起不来。

---

## 5. 自动发布 / 自动更新：当前不存在

| 能力 | 状态 | 依据 |
|---|---|---|
| GitHub Actions 工作流 | ❌ 本地无 `.github/`；远端 `/contents/.github/workflows` = 404；`.gitignore` 还显式排除 `.github/`（注释：token 无 workflow scope） | 本地 ls + GitHub API |
| Git tag | ❌ 本地 0 个、远端 0 个 | `git tag -l` + API |
| GitHub Release / Setup.exe 下载 | ❌ 0 个 Release | GitHub API |
| 客户端自动更新 | ❌ 主进程无 `autoUpdater`；`publish: null` | `main.cjs` grep + `package.json:113` |

因此「打 tag → Actions 打包 → 自动建 Release → 客户端检测更新」这条链**每一步都不成立**。

### 若要恢复自动发布（待办，未执行）

1. 从 `.gitignore` 放行 `.github/`，并换用带 `workflow` scope 的 token（现有 token 无该 scope，推不上去）。
2. 新增 Windows workflow：装依赖 → `npx tsc --noEmit` → `npx vite build` → `npx electron-builder` → 上传 Release 资产。
3. `build.publish` 设为 `{ "provider": "github", "owner": "q547113058-max", "repo": "ChallengeDaily", "private": true }`。
4. 在 `main.cjs` 接 `autoUpdater`，并处理**私有仓库**资产下载鉴权（electron-updater 需要 token，不能照公开仓库配置抄）。
5. 先修 §4 的 6 条缺失资源，否则 CI 打包必挂。

> ⚠️ 私有仓库 + 自动更新涉及 token 分发，别把 PAT 打进客户端或提交进仓库。

---

## 6. 回退与恢复（通用，分支 `master`）

```bash
git log --oneline                 # 查提交
git reset --hard HEAD~1            # 回退上一个提交（破坏性，先确认无未提交改动）
git reset --hard <commit-id>       # 回退到指定提交
git restore <文件>                 # 恢复误删/误改的文件（旧写法 git checkout -- <文件> 亦可）
```

> `git reset --hard` 会丢未提交改动；数据目录（`data/`、`%APPDATA%\challenge-daily\backend-data`）不受 Git 影响，回退代码不会回退数据库。

---

## 7. 快速命令清单（本仓库口径）

```bash
# 状态 / 提交 / 推送
git status -sb
git add . && git commit -m "docs: xxx"
GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=Never git push origin master

# 版本号 patch +1（仅改 client/package.json）
cd client && npm run bump && cd ..

# 前端构建（日常改代码用这个，不要 npm run build）
cd client && npx vite build && cd ..

# 本地打包（需先修 §4 的 6 条资源）
cd client && npm run build && cd ..

# 查历史
git log --oneline
```

---

## 8. 文档口径

- `README.md`：功能与启动（含本机三种启动方式）。
- `HANDOFF.md`：交接、环境坑、排障、推送认证、遗留问题。
- 本文：版本管理、发布现状与恢复自动发布的待办。
- `REVIEW_2026-09-10.md`：代码审查报告（历史基线，非当前状态）。
