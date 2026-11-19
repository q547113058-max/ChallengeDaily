/**
 * 源码调试启动器（免打包、免安装）
 *
 *   npm start        = 重新构建前端 + 启动源码 Electron（一条命令搞定）
 *   npm start -- --no-build   = 跳过构建，直接启动（仅改了 .cjs 主进程时用）
 *   node scripts/dev-launch.cjs --dry-run  = 只打印将使用的环境变量（供验证）
 *
 * 为什么需要这个包装：
 *   源码直接 `electron .` 会回退 local 模式（尝试起本机 Python 后端），
 *   且 file:// 页面的 meta CSP 不含云端 origin，direct 模式会被拦。
 *   本启动器统一注入环境变量，并在启动前跑一次 vite build，
 *   保证 dist/ 与 CSP 都是最新的。
 *
 * token 只从 deploy/sync_agent.json 读取，绝不写死在仓库里。
 */
const { spawnSync, spawn } = require('child_process')
const fs = require('fs')
const path = require('path')

const CLIENT = path.join(__dirname, '..')
const TOKEN_FILE = path.join(__dirname, '..', '..', '..', 'deploy', 'sync_agent.json')
const DIST_INDEX = path.join(CLIENT, 'dist', 'index.html')
// Windows 11 的任务栏通知区域按 exe 路径识别托盘图标。
// 实测只有 D:\Program Files\ChallengeDaily\ChallengeDaily.exe 在该系统上
// 有通知区记录（IsPromoted=1），node_modules / runtime 路径均不会被系统接纳。
// 因此优先使用 Program Files 下的 exe（内容是 electron 运行时，加载源码 app 目录）。
const ELECTRON_PF = 'D:\\Program Files\\ChallengeDaily\\ChallengeDaily.exe'
const ELECTRON_RUNTIME = path.join(CLIENT, '..', 'runtime', 'ChallengeDaily.exe')
const ELECTRON_NAMED = path.join(CLIENT, 'node_modules', 'electron', 'dist', 'ChallengeDaily.exe')
const ELECTRON_DEFAULT = path.join(CLIENT, 'node_modules', 'electron', 'dist', 'electron.exe')
const ELECTRON = fs.existsSync(ELECTRON_PF)
  ? ELECTRON_PF
  : (fs.existsSync(ELECTRON_RUNTIME)
    ? ELECTRON_RUNTIME
    : (fs.existsSync(ELECTRON_NAMED) ? ELECTRON_NAMED : ELECTRON_DEFAULT))

const args = process.argv.slice(2)
const dryRun = args.includes('--dry-run')
const noBuild = args.includes('--no-build')
const buildOnly = args.includes('--build-only')

function readToken() {
  try {
    return (JSON.parse(fs.readFileSync(TOKEN_FILE, 'utf8')).token || '').trim()
  } catch (e) {
    console.error('[dev] 无法读取 token:', TOKEN_FILE, e.message)
    return ''
  }
}

// 统一环境：清掉干扰项 + direct 模式连云端
const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE          // 否则 electron 以 Node 模式启动，main.cjs 主动退出
delete env.PYTHONHOME
delete env.PYTHONPATH

// 关键：esbuild 会在 %TEMP% 下建临时服务目录并尝试删除；某些 Windows 环境
// （cmd.exe / 受限账户）对该目录无删除权限，导致 vite build 报
// "remove ...: Access is denied" 而失败。重定向到工作区内可写目录。
const BUILD_TMP = path.join(CLIENT, '.temp', 'build')
try { fs.mkdirSync(BUILD_TMP, { recursive: true }) } catch (_) {}
env.TEMP = BUILD_TMP
env.TMP = BUILD_TMP

// 用包内自带的 esbuild 二进制，避免它再去 %TEMP% 解包临时服务
env.ESBUILD_BINARY_PATH = path.join(CLIENT, 'node_modules', '@esbuild', 'win32-x64', 'esbuild.exe')

env.ELECTRON_IS_DEV = '0'                // 加载 dist/index.html（非 dev server）
// 用改名的 ChallengeDaily.exe 后 electron 可能误判 isPackaged，禁用更新检查
env.CD_SOURCE_MODE = '1'
// 源码调试用独立 userData，避免与已安装的打包版争抢单实例锁
// （否则会报 "Lock file can not be created! Error code: 5" 并立即退出）
// Business state dir (app.setPath) + separate native --user-data-dir for
// Chromium's cache/Network. The native switch is applied earliest so Chromium
// creates those subdirs itself (avoids cache/Network creation FATAL).
const DEV_USER_DATA = path.join(CLIENT, '..', 'data', 'electron-profile')
const CHROME_USER_DATA = path.join(CLIENT, '..', 'data', 'chrome-profile')
try { fs.mkdirSync(DEV_USER_DATA, { recursive: true }) } catch (_) {}
try { fs.mkdirSync(CHROME_USER_DATA, { recursive: true }) } catch (_) {}
env.CHALLENGE_DAILY_USER_DATA_DIR = DEV_USER_DATA
env.CD_CHROME_USER_DATA = CHROME_USER_DATA
// Chromium singleton lock creation fails on this machine even with no
// electron process; main.cjs skips requestSingleInstanceLock when set.
env.CD_NO_SINGLETON = '1'
env.CHALLENGE_DAILY_BACKEND_MODE = 'direct'
env.CHALLENGE_DAILY_BACKEND_URL = 'http://193.112.246.85'
env.CHALLENGE_DAILY_BACKEND_TOKEN = readToken()
env.CD_BACKEND_ORIGIN = 'http://193.112.246.85'

if (dryRun) {
  console.log('ELECTRON_RUN_AS_NODE       = <deleted>')
  console.log('ELECTRON_IS_DEV            =', env.ELECTRON_IS_DEV)
  console.log('CHALLENGE_DAILY_BACKEND_MODE =', env.CHALLENGE_DAILY_BACKEND_MODE)
  console.log('CHALLENGE_DAILY_BACKEND_URL  =', env.CHALLENGE_DAILY_BACKEND_URL)
  console.log('CHALLENGE_DAILY_BACKEND_TOKEN= <len ' + env.CHALLENGE_DAILY_BACKEND_TOKEN.length + '>')
  console.log('CD_BACKEND_ORIGIN          =', env.CD_BACKEND_ORIGIN)
  console.log('dist/index.html            =', fs.existsSync(DIST_INDEX))
  console.log('electron.exe               =', fs.existsSync(ELECTRON))
  process.exit(0)
}

if (buildOnly) {
  console.log('[dev] 构建前端 dist/（仅构建，不启动 Electron）...')
  const r = spawnSync(process.execPath, [path.join(CLIENT, 'node_modules', 'vite', 'bin', 'vite.js'), 'build'], {
    cwd: CLIENT, env, stdio: 'inherit',
  })
  process.exit(r.status || 0)
}

if (!fs.existsSync(ELECTRON)) {
  console.error('[dev] 未找到 electron.exe，请先 npm install')
  process.exit(1)
}

// 1) 构建前端（含 CSP 注入）
if (!noBuild) {
  console.log('[dev] 构建前端 dist/ ...')
  const r = spawnSync(process.execPath, [path.join(CLIENT, 'node_modules', 'vite', 'bin', 'vite.js'), 'build'], {
    cwd: CLIENT, env, stdio: 'inherit',
  })
  if (r.status !== 0) {
    console.error('[dev] 构建失败，终止启动')
    process.exit(r.status || 1)
  }
  console.log('[dev] 构建完成')
}

if (!fs.existsSync(DIST_INDEX)) {
  console.error('[dev] 缺少 dist/index.html，请先去掉 --no-build 跑一次')
  process.exit(1)
}

// 2) 启动源码 Electron
// --no-sandbox：本机 Chromium 沙箱初始化会触发 STATUS_BREAKPOINT。
// --user-data-dir：显式指向干净目录，让 Chromium 自行创建 Cache/Network，
//   避免缓存目录创建失败导致的断点崩溃。
// 不用 --single-process：渲染进程独立，崩溃不会拖死整个应用（黑屏后自退）。
// 用 CLIENT 绝对路径作 app 参数，避免依赖 cwd 解析到项目根（无 package.json）。
console.log('[dev] 启动源码 Electron（direct 模式，不监听 58889）...')
const child = spawn(ELECTRON, [CLIENT, '--no-sandbox', '--disable-gpu', '--user-data-dir=' + CHROME_USER_DATA], {
  cwd: CLIENT, env, stdio: 'inherit', windowsHide: false,
})
child.on('exit', (code) => {
  console.log('[dev] Electron 退出，code =', code)
  process.exit(code || 0)
})
