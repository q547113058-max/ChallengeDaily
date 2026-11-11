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
const ELECTRON = path.join(CLIENT, 'node_modules', 'electron', 'dist', 'electron.exe')

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
env.ELECTRON_IS_DEV = '0'                // 加载 dist/index.html（非 dev server）
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

// 2) 启动源码 Electron（GUI 进程需由用户终端启动）
console.log('[dev] 启动源码 Electron（direct 模式，不监听 58889）...')
const child = spawn(ELECTRON, ['.'], {
  cwd: CLIENT, env, stdio: 'inherit', windowsHide: false,
})
child.on('exit', (code) => {
  console.log('[dev] Electron 退出，code =', code)
  process.exit(code || 0)
})
