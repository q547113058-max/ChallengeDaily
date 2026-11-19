# ChallengeDaily Windows 打包说明

> 最后打包：2026-11-18，产物版本 **3.4.15**（Setup 71 MB / Portable 70.8 MB）
> 产物目录：`client/dist-electron/`

## 1. 一键打包命令

```powershell
cd D:\project\daily\ChallengeDaily\client

# 1) 构建前端（dist/）
$env:TEMP="$PWD\.buildtmp"; $env:TMP=$env:TEMP
$env:CD_BACKEND_ORIGIN='http://193.112.246.85'   # meta CSP 允许直连云端
node node_modules\vite\bin\vite.js build

# 2) 打包（nsis + portable）
$env:ELECTRON_BUILDER_CACHE='D:\project\daily\.eb-cache'
$env:XDG_CACHE_HOME=$env:ELECTRON_BUILDER_CACHE
node node_modules\electron-builder\out\cli\cli.js --win --publish never
```

- `--publish never`：不上传 GitHub（本仓库无自动发布链路）。
- 打包后产物：`ChallengeDaily-<version>-Setup.exe`、`ChallengeDaily-<version>-Portable.exe`、
  `.blockmap`、`latest.yml`、`win-unpacked/`。

## 2. package.json 里为打包做的两处改动（保留）

| 配置 | 值 | 原因 |
|---|---|---|
| `build.electronDist` | `node_modules/electron/dist` | 直接用本地已装的 Electron 31.7.7，避免打包时从 GitHub 下载 111 MB（沙箱下下载分片常失败） |
| `build.win.signAndEditExecutable` | `false` | 跳过 winCodeSign/rcedit 对 exe 写图标/版本资源——该工具包含 macOS 符号链接，本机无 `SeCreateSymbolicLinkPrivilege`，7za 解压必失败 |

**取舍**：`signAndEditExecutable: false` 意味着 exe 文件本身的图标/文件版本信息是 Electron 默认的；
NSIS 安装包的图标仍由 `installerIcon`/`uninstallerIcon` 正确设置为应用图标，功能不受影响。
若以后在有符号链接权限的机器上打包，可把该字段删掉恢复资源编辑。

## 3. 打包内容

- `files`: `dist/**/*` + `electron/**/*`（前端与 Electron 主进程代码）
- `extraResources`: 后端 Python 运行时（main.py / config.py / db.py / routes/*.py / requirements.txt /
  deep_insight_frameworks.yaml 等）复制到 `resources/backend/`。**历史坑**：该列表曾指向已删除文件
  导致打包缺资源，2026-11-18 已核对全部源路径存在（含新增的 `routes/bridge.py`）。
- `backend-default.json` 复制到 `resources/`：含随包默认后端配置（本机构建未写死 token/地址）。

## 4. 验证清单（每次打包后建议执行）

1. `dist-electron/ChallengeDaily-<version>-Setup.exe` 与 `-Portable.exe` 存在且 > 60 MB。
2. `win-unpacked/resources/backend/` 下有 `main.py`、`config.py`、`routes/stats.py`、`routes/bridge.py`、
   `requirements.txt`。
3. `win-unpacked/resources/backend-default.json` 存在。
4. `latest.yml` 与 `.blockmap` 生成（用于更新器/增量分发；本仓库当前无自动发布）。
5. 若改了 CSP 相关代码，确认 `dist/index.html` 的 `connect-src` 含 `http://193.112.246.85`。

## 5. 已知环境坑

- 沙箱/受限账户下 `C:\Users\<user>\AppData\Local\electron\Cache` 与 `...\electron-builder` 写入被拒 →
  用 `ELECTRON_BUILDER_CACHE`/`XDG_CACHE_HOME` 指到工作区可写目录解决。
- winCodeSign 7z 解压 darwin 符号链接失败（无特权）→ `signAndEditExecutable: false` 绕过。
- 不要用 `npm run build`（它会 `vite build && electron-builder` 并可能在无缓存环境下触发下载失败）；
  按 §1 分两步、显式设置缓存变量更稳。
