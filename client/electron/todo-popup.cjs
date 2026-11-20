/**
 * 桌面顶层待办审批弹窗（独立 BrowserWindow，不依赖主窗口是否打开/最小化）。
 *
 * 为什么独立：用户反馈「应用内的右下角 toast 要打开应用才看得到，很容易忽略」。
 * 这里用 alwaysOnTop + skipTaskbar 的无边框小窗，固定在屏幕右下角工作区，
 * 由主进程自己订阅 SSE 触发，主窗口隐藏时也照常弹出。
 *
 * 数据来源：本机桥接代理 127.0.0.1:58889（由独立 node 进程提供，见
 * bridge-proxy.cjs）。主进程直接发 HTTP 请求，不经过渲染层，也不把
 * X-API-Token / X-Todo-Token 暴露给页面。
 *
 * 页面用独立的最小 preload（todo-popup-preload.cjs），只暴露 3 个 API：
 *   decide(action)  /  dismiss()  /  onTodo(cb)
 * 这些通道在 setupIPC() 的「原始 ipcMain」被白名单包裹之前注册，不受影响。
 */

const { BrowserWindow, screen, ipcMain } = require('electron')
const http = require('http')
const path = require('path')
const fs = require('fs')
const { exec } = require('child_process')

// ─── 数据源 ───
// 云端 todo-sync 是 systemd 常驻服务，7×24 稳定。之前弹窗只连本机桥接代理
// 127.0.0.1:58889，而那个独立 node 进程一旦意外退出就没人拉起，日志里
// 连续 7 小时刷 ECONNREFUSED，弹窗窗口虽在却永远没数据。
// 现在主进程直连云端（HTTP 不受渲染层 CSP 限制），彻底摆脱对 58889 的依赖；
// 云端不可达时才回退到本机桥接。
const UPSTREAM_HOST = process.env.TODO_SYNC_HOST || '193.112.246.85'
const UPSTREAM_PORT = Number(process.env.TODO_SYNC_PORT || 18766)
// todo-sync write token (port 18766) is NOT the cloud tenant token.
// Priority: env var -> deploy/todo_sync.json -> TodoSyncToken in settings.
function _readSyncToken() {
  if (process.env.TODO_SYNC_TOKEN) return process.env.TODO_SYNC_TOKEN.trim()
  var fs = require('fs')
  var path = require('path')
  function pick(o) { return (o && typeof o.token === 'string' && o.token.trim()) ? o.token.trim() : '' }
  // candidate config files: dev checkout, next to the exe, userData
  var cands = []
  try {
    var electron = require('electron')
    if (electron.app && electron.app.getPath) {
      cands.push(path.join(electron.app.getPath('userData'), 'todo_sync.json'))
    }
    if (process.resourcesPath) {
      cands.push(path.join(path.dirname(process.resourcesPath), 'deploy', 'todo_sync.json'))
      cands.push(path.join(process.resourcesPath, 'todo_sync.json'))
    }
  } catch (_) { /* ignore */ }
  cands.push(process.env.CD_TODO_CONFIG || '')
  cands.push(path.join(__dirname, '..', '..', '..', 'deploy', 'todo_sync.json'))
  cands.push(path.join(__dirname, '..', '..', 'deploy', 'todo_sync.json'))
  cands = cands.filter(Boolean)
  for (var i = 0; i < cands.length; i++) {
    try {
      if (!fs.existsSync(cands[i])) continue
      var t = pick(JSON.parse(fs.readFileSync(cands[i], 'utf8')))
      if (t) return t
    } catch (_) { /* ignore */ }
  }
  return ''
}
const UPSTREAM_TOKEN = _readSyncToken()
const BRIDGE_HOST = '127.0.0.1'
const BRIDGE_PORT = Number(process.env.CD_BRIDGE_PORT || 58889)
const POPUP_W = 360
const POPUP_H = 250
const TTL_MS = 300000 // 与服务端 TODO_SYNC_PROPOSED_TTL 一致

// 云端原生路径（与桥接代理转发的路径一一对应）
const P = {
  proposed: '/api/todos?status=proposed',
  events: '/api/events',
  decide: (id, act) => `/api/todos/${id}/${act}`,
  status: (id) => `/api/todos/${id}/status`,
}

let _win = null
let _queue = []
let _sseReq = null
let _pollTimer = null
let _current = null
let _busy = false
let _started = false
let _lastSeenIds = new Set()

function _log(...a) { console.log('[TodoPopup]', ...a) }

// ─── 58889 桥接守护 ───
// 弹窗本身已直连云端，不再依赖 58889。但应用抽屉和 direct 模式的 HealthCheck
// 仍探 58889，那个独立 node 进程挂了会让 App 每 3 分钟误报「后端断开」。
// 守护策略：探测失败 → 在 %TEMP% 动态写一个 .cmd（自包含，不依赖 asar 内
// 文件，因为 app.asar 是归档，里面的 .cmd 无法被 exec 直接执行）→ exec 它，
// 用 powershell Start-Process 拉起独立 node.exe（spawn 在本环境报 EFTYPE）。
let _guardTimer = null
const os = require('os')

const NODE_CANDIDATES = [
  process.env.CD_NODE_EXE,
  'C:\\Users\\54711\\AppData\\Local\\Microsoft\\WinGet\\Packages\\OpenJS.NodeJS.LTS_Microsoft.Winget.Source_8wekyb3d8bbwe\\node-v24.16.0-win-x64\\node.exe',
  'C:\\Users\\54711\\.workbuddy\\binaries\\node\\versions\\22.22.2-6\\node.exe',
].filter(Boolean)

function _nodeExe() {
  for (const p of NODE_CANDIDATES) { try { if (fs.existsSync(p)) return p } catch (_) {} }
  return 'node'
}

function _probeBridge() {
  return new Promise((resolve) => {
    const req = http.get(`http://${BRIDGE_HOST}:${BRIDGE_PORT}/api/health?quick=1`, (res) => {
      res.resume(); resolve(res.statusCode === 200)
    })
    req.on('error', () => resolve(false))
    req.setTimeout(2000, () => { req.destroy(); resolve(false) })
  })
}

function _writeRespawnCmd() {
  const node = _nodeExe()
  // bridge-proxy.cjs 在源码目录（asar 外的真实路径）
  const bridge = 'D:\\project\\daily\\ChallengeDaily\\client\\electron\\bridge-proxy.cjs'
  const lines = [
    '@echo off',
    'set "ELECTRON_RUN_AS_NODE="',
    `set "CD_BRIDGE_PORT=${BRIDGE_PORT}"`,
    `set "TODO_SYNC_URL=http://${UPSTREAM_HOST}:${UPSTREAM_PORT}"`,
    `set "TODO_SYNC_TOKEN=${UPSTREAM_TOKEN}"`,
    `set "NODE_EXE=${node}"`,
    `set "BRIDGE=${bridge}"`,
    'if not exist "%BRIDGE%" exit /b 1',
    'powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath \'%NODE_EXE%\' -ArgumentList \'%BRIDGE%\' -WindowStyle Hidden"',
    'exit /b 0',
  ]
  const f = path.join(os.tmpdir(), 'cd-respawn-bridge.cmd')
  fs.writeFileSync(f, lines.join('\r\n') + '\r\n', 'ascii')
  return f
}

async function _guardTick() {
  const ok = await _probeBridge()
  if (ok) return
  try {
    const cmd = _writeRespawnCmd()
    exec(`"${cmd}"`, { windowsHide: true }, (err) => {
      if (err) _log('bridge respawn failed', err.message)
      else _log('bridge 58889 was down, respawned via temp cmd')
    })
  } catch (e) {
    _log('respawn cmd write failed', e?.message || e)
  }
}

function _startBridgeGuard() {
  if (_guardTimer) return
  // 启动时先探一次，之后每 30 秒守护
  _guardTick()
  _guardTimer = setInterval(_guardTick, 30000)
}

/** 通用 JSON 请求：host/port/path + 可选 token。 */
function _req(host, port, apiPath, method, body, token) {
  return new Promise((resolve, reject) => {
    const data = body ? Buffer.from(JSON.stringify(body)) : null
    const headers = { 'Content-Type': 'application/json; charset=utf-8' }
    if (token) headers['X-Todo-Token'] = token
    if (data) headers['Content-Length'] = String(data.length)
    const req = http.request(
      { host, port, path: apiPath, method, headers, timeout: 10000 },
      (res) => {
        const chunks = []
        res.on('data', (c) => chunks.push(c))
        res.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8')
          try { resolve({ code: res.statusCode, data: JSON.parse(text) }) }
          catch (_) { resolve({ code: res.statusCode, data: {} }) }
        })
      },
    )
    req.on('timeout', () => req.destroy(new Error('timeout')))
    req.on('error', reject)
    if (data) req.write(data)
    req.end()
  })
}

/** 直连云端 todo-sync（主路径）。 */
function _cloud(method, apiPath, body) {
  return _req(UPSTREAM_HOST, UPSTREAM_PORT, apiPath, method, body, UPSTREAM_TOKEN)
}

/** 本机桥接代理（仅云端不可达时的回退）。
 *  云端 /api/todos... → 桥接 /api/bridge/todos...（一次替换即可）。
 */
function _bridgeFallback(method, apiPath, body) {
  const p = apiPath.startsWith('/api/bridge/') ? apiPath : apiPath.replace('/api/', '/api/bridge/')
  return _req(BRIDGE_HOST, BRIDGE_PORT, p, method, body, null)
}

/** 取数：先云端，失败回退本机桥接。 */
async function _get(method, apiPath, body) {
  try {
    return await _cloud(method, apiPath, body)
  } catch (e) {
    _log('cloud unreachable, fallback to bridge:', e?.message || e)
    return await _bridgeFallback(method, apiPath, body)
  }
}

function _popupHtmlPath() {
  // 打包后位于 app.asar/electron/todo-popup.html
  return path.join(__dirname, 'todo-popup.html')
}

function _place(win) {
  try {
    const area = screen.getPrimaryDisplay().workArea
    const x = Math.max(area.x, area.x + area.width - POPUP_W - 16)
    const y = Math.max(area.y, area.y + area.height - POPUP_H - 16)
    win.setBounds({ x, y, width: POPUP_W, height: POPUP_H })
  } catch (e) { _log('place failed', e?.message || e) }
}

function _createWindow() {
  if (_win && !_win.isDestroyed()) return _win
  const html = _popupHtmlPath()
  if (!fs.existsSync(html)) {
    _log('todo-popup.html missing:', html)
    return null
  }
  _win = new BrowserWindow({
    width: POPUP_W, height: POPUP_H,
    frame: false, transparent: true, resizable: false, movable: false,
    minimizable: false, maximizable: false, closable: false,
    alwaysOnTop: true, skipTaskbar: true, focusable: true,
    hasShadow: false, backgroundColor: '#00000000',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'todo-popup-preload.cjs'),
      contextIsolation: true, nodeIntegration: false, sandbox: true,
      backgroundThrottling: false,
    },
  })
  _win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
  _win.loadFile(html)
  _win.once('ready-to-show', () => {
    _place(_win)
    _win.showInactive() // 不抢焦点，避免打断用户打字
    // 关键：置顶必须在 show 之后再设一次。创建时设的 alwaysOnTop 会被
    // showInactive/hide-show 流程冲掉（实测枚举窗口 topmost=False）。
    _win.setAlwaysOnTop(true, 'screen-saver')
  })
  // 显示器变化（外接屏/分辨率）时重新贴右下角
  screen.on('display-metrics-changed', () => { if (_win && !_win.isDestroyed()) _place(_win) })
  _win.on('closed', () => { _win = null })
  return _win
}

function _render() {
  if (!_win || _win.isDestroyed()) return
  const item = _current
  _win.webContents.send('todo-popup:data', item ? {
    id: item.id, project: item.project, todo: item.todo,
    basis: item.basis, confidence: item.confidence,
    ttl: TTL_MS / 1000,
  } : null)
  if (item) {
    _place(_win)
    if (!_win.isVisible()) _win.showInactive()
    // 每次显示都重申置顶：hide→show 会清掉置顶状态
    _win.setAlwaysOnTop(true, 'screen-saver')
  } else {
    if (_win.isVisible()) _win.hide()
  }
}

function _next() {
  _current = _queue.shift() || null
  _busy = false
  _render()
}

function _enqueue(d) {
  if (!d || !d.id) return
  if (_lastSeenIds.has(d.id)) return
  _lastSeenIds.add(d.id)
  if (_current && _current.id === d.id) return
  if (_queue.some((x) => x.id === d.id)) return
  _queue.push({
    id: d.id,
    project: d.project || 'ChallengeDaily',
    todo: d.todo || '',
    basis: d.basis || '',
    confidence: d.confidence || 'medium',
  })
  _log('enqueued', d.id, d.todo)
  if (!_current && !_busy) _next()
}

/** 审批：approve / reject，转给桥接代理 → 线上 todo-sync。 */
async function _decide(id, action) {
  if (_busy) return
  _busy = true
  try {
    const r = await _get('POST', P.decide(id, action), {})
    _log('decide', id, action, '->', r.code, JSON.stringify(r.data).slice(0, 120))
  } catch (e) {
    _log('decide failed', e?.message || e)
  }
  if (_current && _current.id === id) {
    _next()
  } else {
    _queue = _queue.filter((x) => x.id !== id)
    _busy = false
  }
}

/** 启动时补拉一次历史 proposed（SSE 只推新 insert，不回放）。
 *  只补最新 1 条：桌面弹窗是「即时打扰」，一次塞 4 条会排队等十几分钟，
 *  反而错过时效；其余历史候选仍可在应用抽屉的「待确认」区处理。
 */
async function _fetchPending() {
  try {
    const r = await _get('GET', P.proposed)
    if (r.code === 200 && Array.isArray(r.data.todos) && r.data.todos.length) {
      const newest = r.data.todos.reduce((a, b) => (a.id > b.id ? a : b))
      _enqueue(newest)
    }
  } catch (e) { _log('fetch pending failed', e?.message || e) }
}

/** 断线重连的 SSE 订阅：直连云端 /api/events。
 *  云端稳定（systemd）；本机桥接只在云端连续失败时作为回退。
 */
let _sseFallback = false
function _subscribe() {
  if (_sseReq) { try { _sseReq.destroy() } catch (_) {} }
  const useCloud = !_sseFallback
  const host = useCloud ? UPSTREAM_HOST : BRIDGE_HOST
  const port = useCloud ? UPSTREAM_PORT : BRIDGE_PORT
  const spath = useCloud ? P.events : '/api/bridge/events'
  const headers = { Accept: 'text/event-stream' }
  if (useCloud) headers['X-Todo-Token'] = UPSTREAM_TOKEN
  const req = http.request(
    { host, port, path: spath, method: 'GET', headers, timeout: 0 },
    (res) => {
      _log('SSE connected', useCloud ? 'cloud' : 'bridge', res.statusCode)
      _sseFallback = false
      let buf = ''
      res.setEncoding('utf8')
      res.on('data', (chunk) => {
        buf += chunk
        let idx
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const frame = buf.slice(0, idx)
          buf = buf.slice(idx + 2)
          const line = frame.split('\n').find((l) => l.startsWith('data:'))
          if (!line) continue
          try {
            const ev = JSON.parse(line.slice(5).trim())
            if (ev.action === 'insert' && ev.detail) _enqueue(ev.detail)
            else if (ev.action === 'status' && ev.status !== 'proposed') {
              // 别的设备审批/超时忽略后，从队列里移除
              if (_current && _current.id === ev.id) _next()
              else _queue = _queue.filter((x) => x.id !== ev.id)
            }
          } catch (_) { /* 心跳/坏包 */ }
        }
      })
      res.on('end', () => { _log('SSE ended, reconnect in 5s'); setTimeout(_subscribe, 5000) })
    },
  )
  req.on('error', (e) => {
    // 云端连不上就切本机桥接；本机桥接也连不上就再切回云端（云端恢复时自动回主路）
    if (useCloud) { _log('cloud SSE failed, try bridge:', e?.message || e); _sseFallback = true }
    else { _log('bridge SSE failed, retry cloud:', e?.message || e); _sseFallback = false }
    setTimeout(_subscribe, 5000)
  })
  req.on('timeout', () => req.destroy())
  req.end()
  _sseReq = req
}

/** 兜底轮询：即使 SSE 断了也能补到新候选。 */
function _startPoll() {
  if (_pollTimer) return
  _pollTimer = setInterval(async () => {
    let r = null
    try {
      r = await _get('GET', P.proposed)
    } catch (_) { /* 桥接未就绪时静默 */ }
    // 关键：拿不到 proposed（桥接返回 501/结构异常/网络失败）时，也要按「无待审」处理，
    // 否则 _current 会残留已过期待审，alwaysOnTop 窗口一直盖在最上层像遮罩。
    const liveTodos = (r && r.code === 200 && r.data && Array.isArray(r.data.todos))
      ? r.data.todos
      : []
    const live = new Set(liveTodos.map((t) => t.id))
    // 当前弹的那条若已不在待审列表（被审批/TTL 过期/拿不到列表），立刻关掉
    if (_current && !live.has(_current.id)) { _next(); return }
    _queue = _queue.filter((x) => live.has(x.id))
    // 兜底：队列已空但窗口仍可见，强制隐藏（防残留遮罩）
    if (!_current && _queue.length === 0 && _win && !_win.isDestroyed() && _win.isVisible()) {
      _win.hide()
    }
    // 只补最新一条新候选，避免队列堆积
    const fresh = liveTodos.filter((t) => !_lastSeenIds.has(t.id))
    if (fresh.length) {
      const newest = fresh.reduce((a, b) => (a.id > b.id ? a : b))
      _enqueue(newest)
    }
  }, 30000)
}

function start() {
  if (_started) return
  _started = true
  // 在 setupIPC() 包裹 ipcMain 之前注册（那时 ipcMain.handle 已被白名单代理）
  ipcMain.on('todo-popup:decide', (_e, payload) => {
    const { id, action } = payload || {}
    if (id && (action === 'approve' || action === 'reject')) _decide(id, action)
  })
  ipcMain.on('todo-popup:dismiss', () => { if (_current) _next() })
  ipcMain.on('todo-popup:ready', () => _render())

  _createWindow()
  _fetchPending()
  _subscribe()
  _startPoll()
  _startBridgeGuard()
  _log('started, cloud', `${UPSTREAM_HOST}:${UPSTREAM_PORT}`, '| bridge guard on', BRIDGE_PORT)
}

function stop() {
  _started = false
  if (_sseReq) { try { _sseReq.destroy() } catch (_) {} _sseReq = null }
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null }
  if (_guardTimer) { clearInterval(_guardTimer); _guardTimer = null }
  if (_win && !_win.isDestroyed()) _win.destroy()
  _win = null
}

module.exports = { start, stop }
