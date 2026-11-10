// ── 客户端状态存储：全部数据存到服务器，不再使用 localStorage ──
//
// 目标：单机服务器、无账号体系，浏览器/多窗口共享同一份状态。
//
// 实现方式：
//   1) 启动时 GET /api/client-state 拉全量状态到内存缓存（_cache）；
//   2) 之后所有 getItem/setItem/removeItem 同步读写 _cache —— 现有代码
//      （大量 useState 惰性初始化同步读取）无需改成 async；
//   3) 每次写操作异步、防抖地把「变更集」PATCH 回服务器；
//   4) 首次启动时把旧版浏览器 localStorage 里的 cd_* 键一次性迁移到服务器，
//      随后删除本地副本，本地不再保留任何业务状态。
//
// 失败策略：服务器不可达时缓存仍可用（内存态），写操作会重试；
// 下次启动仍以服务器为准。这样离线/重启都不会丢交互能力。

import { request, resolveApiUrl, getApiTokenSync } from './core'

/** 曾经存在 localStorage 的键（迁移用）。新增键必须同样以 cd_ 开头。 */
const LEGACY_KEYS = [
  'cd_legal_accepted',
  'cd_onboarding_done',
  'cd_onboarding_done_at',
  'cd_calibration_guided',
  'cd_app_lock_v1',
  'cd_theme',
  'cd_accent',
  'cd_font',
  'cd_sidebar_translucent',
  'cd_radius',
  'cd_shadow',
  'cd_opacity',
  'cd_skin',
  'cd_custom_accent',
  'cd_font_scale',
] as const

/** 迁移标记：本地只保留这一个键，用于判断旧数据是否已经搬过。 */
const MIGRATION_FLAG = 'cd_state_migrated_v2'

let _cache: Record<string, string> = {}
let _loaded = false
let _loadPromise: Promise<void> | null = null
let _flushTimer: ReturnType<typeof setTimeout> | null = null
let _flushing = false
let _dirty = false
// 待同步的变更集：key -> 新值（null 表示删除）。只提交变化的键，
// 避免多窗口/多设备同时修改不同字段时整份覆盖互相冲掉。
const _pending: Record<string, string | null> = {}
let _lastError = ''
const _readyListeners = new Set<() => void>()

/** 服务端状态是否已加载完成（App 用它来 gate 首屏渲染）。 */
export function isServerStorageLoaded(): boolean { return _loaded }

/** 订阅「服务器状态加载/更新完成」事件，返回取消订阅函数。
 *  用于那些在顶层 hook 里同步读取配置的组件（如应用锁）在状态到齐后重新读取。 */
export function onServerStorageReady(cb: () => void): () => void {
  _readyListeners.add(cb)
  return () => _readyListeners.delete(cb)
}

function _notifyReady(): void {
  _readyListeners.forEach(cb => { try { cb() } catch { /* ignore */ } })
}

/** 最近一次同步错误（供状态栏/调试查看，不影响使用）。 */
export function getServerStorageError(): string { return _lastError }

/** 与 localStorage 同形的同步接口。 */
export const serverStorage = {
  getItem(key: string): string | null {
    return Object.prototype.hasOwnProperty.call(_cache, key) ? _cache[key] : null
  },
  setItem(key: string, value: string): void {
    const v = String(value)
    _cache[key] = v
    _pending[key] = v
    _scheduleFlush()
  },
  removeItem(key: string): void {
    delete _cache[key]
    _pending[key] = null
    _scheduleFlush()
  },
  key(index: number): string | null {
    return Object.keys(_cache)[index] ?? null
  },
  get length(): number { return Object.keys(_cache).length },
  clear(): void {
    for (const k of Object.keys(_cache)) _pending[k] = null
    _cache = {}
    _scheduleFlush()
  },
}

function _collectLegacy(): Record<string, string> {
  const out: Record<string, string> = {}
  try {
    for (const k of LEGACY_KEYS) {
      const v = localStorage.getItem(k)
      if (v !== null) out[k] = v
    }
  } catch { /* 隐私模式下 localStorage 可能抛错，忽略 */ }
  return out
}

function _cleanLegacy(): void {
  try {
    for (const k of LEGACY_KEYS) localStorage.removeItem(k)
    localStorage.setItem(MIGRATION_FLAG, '1')
  } catch { /* ignore */ }
}

async function _migrateLegacy(): Promise<void> {
  try {
    const already = localStorage.getItem(MIGRATION_FLAG)
    const legacy = _collectLegacy()
    if (already === '1' || Object.keys(legacy).length === 0) {
      // 即使没有旧数据也打上标记，避免每次启动都扫描
      if (already !== '1') _cleanLegacy()
      return
    }
    await request('/api/client-state/migrate', {
      method: 'POST',
      body: JSON.stringify({ state: legacy }),
    }, 10000)
    _cleanLegacy()
  } catch (e) {
    // 迁移失败不阻断启动；下次启动会重试（因为标记没写）
    _lastError = '旧本地数据迁移失败，将在下次启动重试'
    console.warn('[clientState] migrate failed:', e)
  }
}

/** 启动引导：拉全量状态 → 迁移旧 localStorage → 标记加载完成。 */
export function loadServerState(): Promise<void> {
  if (_loadPromise) return _loadPromise
  _loadPromise = (async () => {
    try {
      const data = await request('/api/client-state', {}, 10000) as { state?: Record<string, string> }
      _cache = (data && typeof data.state === 'object' && data.state) ? { ...data.state } : {}
      _lastError = ''
    } catch (e) {
      // 后端刚起来 / 网络抖动：内存缓存保持空，稍后由 App 重试
      _lastError = '服务器状态加载失败'
      console.warn('[clientState] load failed:', e)
      throw e
    }
    await _migrateLegacy()
    _loaded = true
    _notifyReady()
  })().catch(() => {
    // 允许 App 重试：清掉 promise，但 _loaded 保持 false
    _loadPromise = null
  })
  return _loadPromise
}

/** 防抖批量回写：120ms 内的多次写入合并成一次 PUT，避免主题初始化写风暴。 */
function _scheduleFlush(): void {
  _dirty = true
  if (_flushTimer) clearTimeout(_flushTimer)
  _flushTimer = setTimeout(() => { void _flush() }, 120)
}

async function _flush(): Promise<void> {
  if (_flushing) return
  if (!_dirty || Object.keys(_pending).length === 0) return
  _flushing = true
  _dirty = false
  if (_flushTimer) { clearTimeout(_flushTimer); _flushTimer = null }
  // 取出并清空待同步集；失败时原样放回，保证不丢变更
  const changes: Record<string, string | null> = {}
  for (const k of Object.keys(_pending)) { changes[k] = _pending[k]; delete _pending[k] }
  try {
    const data = await request('/api/client-state', {
      method: 'PATCH',
      body: JSON.stringify({ state: changes }),
    }, 10000) as { state?: Record<string, string> }
    // 服务端返回合并后的全量状态：合并别的窗口刚写入的键，
    // 但保留本窗口尚未同步的变更（_pending）优先。
    if (data && typeof data.state === 'object' && data.state) {
      const merged: Record<string, string> = { ...data.state }
      for (const k of Object.keys(_pending)) {
        const v = _pending[k]
        if (v === null) delete merged[k]
        else merged[k] = v
      }
      const changed = JSON.stringify(_cache) !== JSON.stringify(merged)
      _cache = merged
      if (changed) _notifyReady()  // 别的窗口刚写的改动，通知 UI 刷新
    }
    _lastError = ''
  } catch (e) {
    _dirty = true  // 标记待重试
    for (const k of Object.keys(changes)) {
      if (!(k in _pending)) _pending[k] = changes[k]
    }
    _lastError = '状态同步到服务器失败，将自动重试'
    console.warn('[clientState] flush failed:', e)
    // 3 秒后自动重试（最多由后续写入继续触发）
    if (!_flushTimer) _flushTimer = setTimeout(() => { void _flush() }, 3000)
  } finally {
    _flushing = false
  }
}

/** 定期从服务器拉取最新状态，让多个窗口/设备看到彼此的改动（无 pending 时才合并）。 */
async function _pollRemote(): Promise<void> {
  if (!_loaded || Object.keys(_pending).length > 0 || _flushing) return
  try {
    const data = await request('/api/client-state', {}, 8000) as { state?: Record<string, string> }
    if (data && typeof data.state === 'object' && data.state) {
      const next: Record<string, string> = { ...data.state }
      for (const k of Object.keys(_pending)) {
        const v = _pending[k]
        if (v === null) delete next[k]
        else next[k] = v
      }
      const changed = JSON.stringify(_cache) !== JSON.stringify(next)
      _cache = next
      if (changed) _notifyReady()
    }
  } catch { /* 网络抖动忽略，下次轮询重试 */ }
}

/** 页面关闭前尽量把未落盘的状态同步出去（best-effort）。 */
export function initServerStorageLifecycle(): void {
  if (typeof window === 'undefined') return
  // 多窗口同步：每 15 秒拉一次；窗口重新可见时立即拉一次
  setInterval(() => { void _pollRemote() }, 15000)
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) void _pollRemote()
  })
  window.addEventListener('beforeunload', () => {
    if (!_dirty) return
    try {
      const token = getApiTokenSync()
      const payload = JSON.stringify({ state: { ..._pending } })
      // 用 keepalive 提高离开页面时的送达率；必须用绝对 URL，
      // 因为 Electron 以 file:// 加载页面，相对路径会解析失败。
      fetch(resolveApiUrl('/api/client-state'), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...(token ? { 'X-API-Token': token } : {}) },
        body: payload,
        keepalive: true,
      }).catch(() => {})
    } catch { /* ignore */ }
  })
}
