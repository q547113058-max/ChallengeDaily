/**
 * ChallengeDaily 在线更新模块（electron-updater）
 *
 * 设计约定（与 main.cjs 现有架构对齐）：
 * - 只在「已打包 + win32」下启用；源码/dev 模式一律不联网，避免开发期误触发。
 * - 采用「启动检查 + 弹窗确认」：发现新版本先弹窗询问是否下载，下载完成后再弹窗询问是否重启安装。
 * - 不自动下载（autoDownload=false），用户拒绝即不消耗带宽。
 * - autoInstallOnAppQuit=true：若用户选择「退出时安装」，下次正常退出会自动落盘安装。
 * - 所有状态变化通过 send('updater-state', state) 推给渲染进程，渲染层只消费状态、不直接调 autoUpdater。
 * - 更新源由 electron-builder 依据 package.json 的 build.publish 生成的 resources/app-update.yml 提供，
 *   本模块不硬编码 URL、不携带任何 token。
 *
 * 由 main.cjs 调用 initUpdater({ send, getMainWindow })，IPC handler 仍在 main.cjs 内注册以便复用
 * isFromMainWindow() 的发送方校验。
 */

const { app, dialog } = require('electron')
const { autoUpdater } = require('electron-updater')

// ─── 模块内状态 ────────────────────────────────────
let _send = () => {}
let _getMainWindow = () => null
let _initialized = false
let _startupTimer = null
let _checkInFlight = false
let _dialogOpen = false

const SUPPORTED = app.isPackaged && process.platform === 'win32'

/** 对外暴露的更新状态（结构与前端 UpdateState 一致） */
let _state = {
  status: 'idle',
  supported: SUPPORTED,
  version: null,
  currentVersion: app.getVersion(),
  releaseNotes: null,
  releaseDate: null,
  progress: null,
  error: null,
  checkedAt: null,
}

function getState() {
  return { ..._state }
}

function setState(patch) {
  _state = { ..._state, ...patch }
  try {
    _send('updater-state', getState())
  } catch (e) {
    console.error('[Updater] send state failed:', e?.message || e)
  }
}

function _errMessage(err) {
  if (!err) return '未知错误'
  return String(err?.message || err).slice(0, 300)
}

function _normalizeNotes(notes) {
  if (!notes) return null
  if (Array.isArray(notes)) {
    return notes
      .map((n) => (typeof n === 'string' ? n : n?.note || ''))
      .filter(Boolean)
      .join('\n')
      .slice(0, 2000) || null
  }
  return String(notes).slice(0, 2000)
}

// ─── 弹窗 ──────────────────────────────────────────
async function _showAvailableDialog(info) {
  if (_dialogOpen) return
  _dialogOpen = true
  try {
    const notes = _normalizeNotes(info?.releaseNotes)
    const detail =
      `当前版本 ${_state.currentVersion} → 新版本 ${info?.version || _state.version || ''}` +
      (notes ? `\n\n更新内容：\n${notes}` : '') +
      '\n\n是否现在下载更新包？'
    const { response } = await dialog.showMessageBox(_getMainWindow() || undefined, {
      type: 'info',
      title: '发现新版本',
      message: `ChallengeDaily ${info?.version || '新版本'} 已发布`,
      detail,
      buttons: ['下载更新', '稍后提醒'],
      defaultId: 0,
      cancelId: 1,
      noLink: true,
    })
    if (response === 0) {
      await downloadUpdate()
    }
  } catch (e) {
    console.error('[Updater] available dialog failed:', e?.message || e)
  } finally {
    _dialogOpen = false
  }
}

async function _showDownloadedDialog(info) {
  if (_dialogOpen) return
  _dialogOpen = true
  try {
    const { response } = await dialog.showMessageBox(_getMainWindow() || undefined, {
      type: 'info',
      title: '更新已就绪',
      message: `ChallengeDaily ${info?.version || _state.version || ''} 已下载完成`,
      detail:
        '重启应用即可完成安装。也可以选择稍后，在你下次退出应用时自动安装。\n\n' +
        '安装过程不会删除本地数据（数据库、设置、备份均保留）。',
      buttons: ['立即重启安装', '退出时安装'],
      defaultId: 0,
      cancelId: 1,
      noLink: true,
    })
    if (response === 0) {
      quitAndInstall()
    }
    // response===1：autoInstallOnAppQuit=true 会在应用退出时自动安装
  } catch (e) {
    console.error('[Updater] downloaded dialog failed:', e?.message || e)
  } finally {
    _dialogOpen = false
  }
}

// ─── autoUpdater 事件绑定 ───────────────────────────
function _bindEvents() {
  autoUpdater.logger = {
    info: (...a) => console.log('[Updater]', ...a),
    warn: (...a) => console.log('[Updater][warn]', ...a),
    error: (...a) => console.error('[Updater]', ...a),
    debug: () => {},
  }

  autoUpdater.autoDownload = false
  autoUpdater.autoInstallOnAppQuit = true

  autoUpdater.on('checking-for-update', () => {
    setState({ status: 'checking', error: null })
  })

  autoUpdater.on('update-available', (info) => {
    setState({
      status: 'available',
      version: info?.version || null,
      releaseNotes: _normalizeNotes(info?.releaseNotes),
      releaseDate: info?.releaseDate || null,
      error: null,
      checkedAt: Date.now(),
    })
    // 弹窗不 await，避免阻塞 checkForUpdates() 调用链
    _showAvailableDialog(info)
  })

  autoUpdater.on('update-not-available', (info) => {
    setState({
      status: 'not-available',
      version: info?.version || _state.currentVersion,
      error: null,
      checkedAt: Date.now(),
    })
  })

  autoUpdater.on('error', (err) => {
    // 启动期静默失败（如尚未发布首个 Release / 断网），只记日志并推状态给设置页
    console.error('[Updater] check/download error:', _errMessage(err))
    setState({ status: 'error', error: _errMessage(err), checkedAt: Date.now() })
  })

  autoUpdater.on('download-progress', (progress) => {
    setState({
      status: 'downloading',
      progress: {
        percent: Number(progress?.percent || 0),
        transferred: Number(progress?.transferred || 0),
        total: Number(progress?.total || 0),
        bytesPerSecond: Number(progress?.bytesPerSecond || 0),
      },
      error: null,
    })
  })

  autoUpdater.on('update-downloaded', (info) => {
    setState({
      status: 'downloaded',
      version: info?.version || _state.version,
      progress: null,
      error: null,
    })
    _showDownloadedDialog(info)
  })
}

// ─── 对外操作 ──────────────────────────────────────

/** 检查更新。manual=true 表示来自设置页手动触发（错误由前端 toast 呈现）。 */
async function checkForUpdates({ manual = false } = {}) {
  if (!SUPPORTED || !_initialized) return getState()
  if (_checkInFlight) return getState()
  if (_state.status === 'downloading') return getState()

  _checkInFlight = true
  setState({ status: 'checking', error: null })
  try {
    await autoUpdater.checkForUpdates()
    if (manual) console.log('[Updater] manual check finished:', _state.status)
  } catch (e) {
    // 'error' 事件通常已 setState，这里兜底
    setState({ status: 'error', error: _errMessage(e), checkedAt: Date.now() })
  } finally {
    _checkInFlight = false
  }
  return getState()
}

/** 下载当前可用版本（仅 available/downloaded 之外的状态才允许）。 */
async function downloadUpdate() {
  if (!SUPPORTED || !_initialized) return getState()
  if (_state.status === 'downloading' || _state.status === 'downloaded') return getState()
  if (_state.status !== 'available') {
    return { ...getState(), error: '当前没有可下载的更新' }
  }
  setState({ status: 'downloading', progress: { percent: 0, transferred: 0, total: 0, bytesPerSecond: 0 }, error: null })
  try {
    await autoUpdater.downloadUpdate()
  } catch (e) {
    setState({ status: 'error', error: _errMessage(e) })
  }
  return getState()
}

/** 退出并安装已下载的更新；由 main.cjs 的 before-quit 负责停后端。 */
function quitAndInstall() {
  if (_state.status !== 'downloaded') return false
  try {
    autoUpdater.quitAndInstall(false, true)
    return true
  } catch (e) {
    console.error('[Updater] quitAndInstall failed:', _errMessage(e))
    return false
  }
}

/** 启动后延迟检查，避免与后端启动/首屏渲染抢资源。 */
function scheduleStartupCheck(delayMs = 8000) {
  if (!SUPPORTED || !_initialized) return
  if (_startupTimer) clearTimeout(_startupTimer)
  _startupTimer = setTimeout(() => {
    _startupTimer = null
    checkForUpdates({ manual: false }).catch((e) => console.error('[Updater] startup check failed:', _errMessage(e)))
  }, Math.max(0, Number(delayMs) || 0))
}

/** 在 app.whenReady() 之后调用一次。 */
function initUpdater({ send, getMainWindow } = {}) {
  if (_initialized) return
  if (typeof send === 'function') _send = send
  if (typeof getMainWindow === 'function') _getMainWindow = getMainWindow

  _state.supported = SUPPORTED
  if (!SUPPORTED) {
    console.log('[Updater] disabled (dev/non-packaged or non-Windows), no update checks will run')
    _initialized = true
    return
  }

  _bindEvents()
  _applyFeedConfig()
  _initialized = true
  console.log('[Updater] initialized, current version:', _state.currentVersion)
}

/**
 * 更新源配置。
 *
 * 默认源来自打包时写入 app-update.yml 的 GitHub provider。
 * 若随包默认配置里带了 updatesUrl（或环境变量 CD_UPDATES_URL），
 * 则改用自建服务器（generic provider）——国内访问更快、不依赖 GitHub。
 *
 * 服务器目录结构（server.py 的 /updates/ 路由）：
 *   <updatesUrl>/latest.yml
 *   <updatesUrl>/ChallengeDaily-<ver>-Setup.exe
 *   <updatesUrl>/ChallengeDaily-<ver>-Setup.exe.blockmap
 */
function _applyFeedConfig() {
  let updatesUrl = process.env.CD_UPDATES_URL || ''
  if (!updatesUrl) {
    try {
      const cfg = require('./backend-config.cjs').loadConfig()
      updatesUrl = cfg.updatesUrl || ''
    } catch (_) {}
  }
  if (!updatesUrl) {
    console.log('[Updater] feed: packaged app-update.yml (github)')
    return
  }
  const base = String(updatesUrl).replace(/\/+$/, '')
  try {
    autoUpdater.setFeedURL({
      provider: 'generic',
      url: base,
      // generic provider 默认会拼接 channel，这里显式指定，避免多出路径
      channel: 'latest',
    })
    _state.feed = base
    console.log('[Updater] feed: server', base)
  } catch (e) {
    console.error('[Updater] setFeedURL failed, fallback to packaged feed:', _errMessage(e))
  }
}

module.exports = {
  initUpdater,
  scheduleStartupCheck,
  checkForUpdates,
  downloadUpdate,
  quitAndInstall,
  getState,
  isSupported: () => SUPPORTED,
}
