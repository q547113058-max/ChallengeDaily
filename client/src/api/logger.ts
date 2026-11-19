// ── 前端日志采集与上传 ──────────────────────────────────────────────────
// 目标：把浏览器渲染层的错误/告警/关键埋点上传到服务器，方便远程排查 bug。
//
// 设计：
//   * 内存环形缓冲（上限 MAX_BUFFER），不写 localStorage（状态已全部上服务器）；
//   * 自动捕获 window.onerror / unhandledrejection / console.error；
//   * 每 FLUSH_INTERVAL 或缓冲满 FLUSH_THRESHOLD 批量 POST /api/logs/ingest；
//   * 上传失败保留缓冲、下次重试；beforeunload 用 sendBeacon 尽力送达；
//   * 上传是 best-effort，任何失败都吞掉，绝不影响业务。

import { getBaseUrl, resolveApiUrl, getApiTokenSync, getBackendState, setRequestLogHook } from './core'

export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

export interface LogEntry {
  ts: string          // ISO 时间戳
  level: LogLevel
  source: string      // 来源：模块/组件名
  message: string
  detail?: string     // 堆栈 / 额外信息
  tenant?: string     // 租户标识（多租户部署时）
  url?: string        // 当前页面 hash 路由
  extra?: Record<string, unknown>
}

const MAX_BUFFER = 500
const FLUSH_THRESHOLD = 30
const FLUSH_INTERVAL_MS = 30000

const _buffer: LogEntry[] = []
// 保存未被拦截的原始 console.error，供 logError 使用，避免递归
const _origError: (...args: any[]) => void = typeof console !== 'undefined'
  ? console.error.bind(console) : () => {}
let _flushTimer: ReturnType<typeof setInterval> | null = null
let _mainLogTimer: ReturnType<typeof setInterval> | null = null
let _flushing = false
let _installed = false
let _tenant = ''
let _sequence = 0
// 已上报的主进程日志行（简单去重，避免每轮重复上传）
const _seenMainLines = new Set<string>()
const MAX_SEEN_MAIN = 2000

/** 设置租户标识（由 getTenantInfo 拿到后调用）。 */
export function setLoggerTenant(tenant: string): void {
  _tenant = tenant || ''
}

function _now(): string {
  try { return new Date().toISOString() } catch { return String(Date.now()) }
}

function _page(): string {
  try { return window.location.hash || window.location.pathname || '' } catch { return '' }
}

function _truncate(s: string, n = 2000): string {
  return s && s.length > n ? s.slice(0, n) + '…(truncated)' : s
}

/** 内部入队。 */
function _push(level: LogLevel, source: string, message: string, detail?: string, extra?: Record<string, unknown>): void {
  const entry: LogEntry = {
    ts: _now(), level, source,
    message: _truncate(String(message)),
    tenant: _tenant || undefined,
    url: _page(),
  }
  if (detail) entry.detail = _truncate(String(detail), 4000)
  if (extra) entry.extra = extra
  _buffer.push(entry)
  _sequence++
  // 环形：超出上限丢弃最早的
  while (_buffer.length > MAX_BUFFER) _buffer.shift()
  // 错误/告警立即触发一次回传（不等定时器）
  if (level === 'error' || _buffer.length >= FLUSH_THRESHOLD) void flushLogs()
}

export function logDebug(source: string, message: string, detail?: string, extra?: Record<string, unknown>): void {
  _push('debug', source, message, detail, extra)
}
export function logInfo(source: string, message: string, detail?: string, extra?: Record<string, unknown>): void {
  _push('info', source, message, detail, extra)
}
export function logWarn(source: string, message: string, detail?: string, extra?: Record<string, unknown>): void {
  _push('warn', source, message, detail, extra)
}
export function logError(source: string, message: string, detail?: string, extra?: Record<string, unknown>): void {
  _push('error', source, message, detail, extra)
  // 同时保留在浏览器 console，方便本地调试。
  // 关键：必须用 _origError（未被拦截的原始函数），否则 console.error 已被
  // initLogger 覆盖 -> logError -> console.error 无限递归，渲染进程会 OOM 崩溃。
  try {
    _origError(`[${source}] ${message}`, detail || '')
  } catch { /* ignore */ }
}

/** 上传一批日志。失败时保留缓冲，等待下次。 */
export async function flushLogs(): Promise<number> {
  if (_flushing || _buffer.length === 0) return 0
  _flushing = true
  // 取出当前缓冲并清空（新的日志继续进缓冲）
  const batch = _buffer.splice(0, _buffer.length)
  const payload = {
    logs: batch,
    source: 'renderer',
    tenant: _tenant || undefined,
    appVersion: (window as any).__cdAppVersion || undefined,
    backendState: getBackendState(),
    baseUrl: getBaseUrl(),
    sentAt: _now(),
  }
  const data = JSON.stringify(payload)
  const token = getApiTokenSync()
  try {
    const res = await fetch(resolveApiUrl('/api/logs/ingest'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'X-API-Token': token } : {}),
      },
      body: data,
      keepalive: true,
    })
    if (!res.ok) throw new Error('HTTP ' + res.status)
    return batch.length
  } catch {
    // 上传失败：放回缓冲（保持最新在前，避免无限增长），下次重试
    _buffer.unshift(...batch)
    while (_buffer.length > MAX_BUFFER) _buffer.pop()
    return 0
  } finally {
    _flushing = false
  }
}

/** 采集主进程日志中的 error/warn 行，并入队上传（去重）。 */
async function collectMainProcessLogs(): Promise<void> {
  const api = window.electronAPI
  if (!api?.getRecentLogs) return
  try {
    const lines = await api.getRecentLogs(200)
    if (!Array.isArray(lines)) return
    for (const line of lines) {
      if (typeof line !== 'string' || line.length === 0) continue
      // 只上报错误/警告/崩溃相关行，普通 access 日志不上报
      const isError = /\[ERR\]|Error|ERROR|FATAL|uncaughtException|render-process-gone|did-fail-load|crash|failed/i.test(line)
      const isWarn = /\[WARN\]|warn|unresponsive|失败/i.test(line)
      if (!isError && !isWarn) continue
      const key = line.slice(0, 300)
      if (_seenMainLines.has(key)) continue
      _seenMainLines.add(key)
      if (_seenMainLines.size > MAX_SEEN_MAIN) {
        // 丢弃最早插入的一批
        const it = _seenMainLines.values().next()
        if (!it.done) _seenMainLines.delete(it.value)
      }
      const level: LogLevel = isError ? 'error' : 'warn'
      _push(level, 'main-process', line.slice(0, 500))
    }
  } catch { /* 主进程日志读取失败不影响业务 */ }
}

/** 安装全局错误捕获 + 定时上传。幂等。 */
export function initLogger(): void {
  if (_installed || typeof window === 'undefined') return
  _installed = true

  // 注册 API 请求日志钩子（core 不直接依赖 logger，避免循环依赖）
  setRequestLogHook((level, source, message, detail, extra) => {
    if (level === 'warn') logWarn(source, message, detail, extra)
    else logError(source, message, detail, extra)
  })

  window.addEventListener('error', (e) => {
    try {
      const detail = e.error && e.error.stack
        ? e.error.stack
        : `${e.filename || ''}:${e.lineno || 0}:${e.colno || 0}`
      logError('window.onerror', e.message || 'unknown error', detail, {
        filename: e.filename, lineno: e.lineno, colno: e.colno,
      })
    } catch { /* ignore */ }
  })

  window.addEventListener('unhandledrejection', (e) => {
    try {
      const reason: any = (e as PromiseRejectionEvent).reason
      const msg = reason && reason.message ? reason.message : String(reason)
      const stack = reason && reason.stack ? reason.stack : undefined
      logError('unhandledrejection', msg, stack)
    } catch { /* ignore */ }
  })

  // 拦截 console.error，让业务代码现有的 console.error 也自动上报。
  // 注意用模块级 _origError（安装拦截前就 bind 好的原始函数），不要在此重新
  // 取 const _origError = console.error —— 若 initLogger 被调用两次会取到已
  // 被覆盖的函数；而且 logError 内部也要用同一份原始引用来避免递归。
  let _inConsoleHandler = false  // 递归保险：处理期间即使再有 console.error 也不再入队
  console.error = (...args: any[]) => {
    if (!_inConsoleHandler) {
      _inConsoleHandler = true
      try {
      const msg = args.map(a => {
        if (a instanceof Error) return a.message
        if (typeof a === 'string') return a
        try { return JSON.stringify(a) } catch { return String(a) }
      }).join(' ')
      const detail = args.find(a => a instanceof Error && a.stack)?.[0]?.stack
        || args.filter(a => typeof a === 'object' && !(a instanceof Error)).map(a => {
          try { return JSON.stringify(a) } catch { return String(a) }
        }).join(' ')
      logError('console.error', msg, detail)
      } catch { /* ignore */ }
      _inConsoleHandler = false
    }
    _origError.apply(console, args)
  }

  _flushTimer = setInterval(() => { void flushLogs() }, FLUSH_INTERVAL_MS)
  // 主进程日志每 60 秒采集一次（首次延迟 10 秒，避开启动高峰）
  setTimeout(() => {
    void collectMainProcessLogs()
    _mainLogTimer = setInterval(() => { void collectMainProcessLogs() }, 60000)
  }, 10000)

  window.addEventListener('beforeunload', () => {
    if (_buffer.length === 0) return
    try {
      const payload = {
        logs: _buffer.slice(), source: 'renderer', tenant: _tenant || undefined,
        appVersion: (window as any).__cdAppVersion || undefined,
        backendState: getBackendState(), baseUrl: getBaseUrl(), sentAt: _now(),
      }
      const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' })
      const token = getApiTokenSync()
      let url = resolveApiUrl('/api/logs/ingest')
      if (token) url += (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(token)
      // sendBeacon 无法自定义 header，token 用 query 传（服务器兼容）
      navigator.sendBeacon?.(url, blob)
    } catch { /* ignore */ }
    _buffer.length = 0
    if (_mainLogTimer) { clearInterval(_mainLogTimer); _mainLogTimer = null }
    if (_flushTimer) { clearInterval(_flushTimer); _flushTimer = null }
  })

  logInfo('logger', 'logger initialized', undefined, { sequence: _sequence })
}

/** 当前缓冲条目数（调试用）。 */
export function pendingLogCount(): number { return _buffer.length }
