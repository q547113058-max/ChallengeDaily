import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, Download, CheckCircle, AlertCircle, Rocket, Loader2 } from 'lucide-react'
import { useToast } from './Toast'

// UpdateState 为 vite-env.d.ts 中声明的全局类型（无 import/export 的 .d.ts 为 ambient）

const INITIAL: UpdateState = {
  status: 'idle',
  supported: false,
  version: null,
  currentVersion: '',
  releaseNotes: null,
  releaseDate: null,
  progress: null,
  error: null,
  checkedAt: null,
}

function formatBytes(n: number) {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(1)} ${units[i]}`
}

/**
 * 在线更新面板（放在设置页「关于」区）。
 * 所有更新逻辑在主进程 electron/updater.cjs，本组件只读状态 + 触发 IPC。
 * 打包版 Windows 才启用；dev/浏览器模式显示说明，不联网。
 */
export default function UpdateChecker({ appVersion }: { appVersion: string }) {
  const toast = useToast()
  const api = typeof window !== 'undefined' ? window.electronAPI : undefined
  const [state, setState] = useState<UpdateState>(INITIAL)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!api?.updaterGetState) return
    let alive = true
    api.updaterGetState().then((s) => { if (alive) setState(s) }).catch(() => {})
    const unsub = api.onUpdaterState?.((s) => { if (alive) setState(s) })
    return () => {
      alive = false
      if (typeof unsub === 'function') unsub()
    }
  }, [api])

  const doCheck = useCallback(async () => {
    if (!api?.updaterCheck || busy) return
    setBusy(true)
    try {
      const s = await api.updaterCheck()
      setState(s)
      if (s.status === 'error') toast.error(`检查更新失败：${s.error || '未知错误'}`)
      else if (s.status === 'not-available') toast.success('已是最新版本')
    } catch (e) {
      toast.error(`检查更新失败：${String(e)}`)
    } finally {
      setBusy(false)
    }
  }, [api, busy, toast])

  const doDownload = useCallback(async () => {
    if (!api?.updaterDownload || busy) return
    setBusy(true)
    try {
      const s = await api.updaterDownload()
      setState(s)
      if (s.error) toast.error(`下载失败：${s.error}`)
    } catch (e) {
      toast.error(`下载失败：${String(e)}`)
    } finally {
      setBusy(false)
    }
  }, [api, busy, toast])

  const doInstall = useCallback(async () => {
    if (!api?.updaterQuitAndInstall || busy) return
    setBusy(true)
    try {
      const ok = await api.updaterQuitAndInstall()
      if (!ok) toast.error('更新未就绪，无法安装')
    } catch (e) {
      toast.error(`安装失败：${String(e)}`)
      setBusy(false)
    }
    // 成功时应用会退出，不必复位 busy
  }, [api, busy, toast])

  const version = state.currentVersion || appVersion || '—'
  const busyThis = busy || state.status === 'checking' || state.status === 'downloading'

  return (
    <div className="rounded-lg border border-cd-border bg-cd-bg-secondary/50 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs font-medium text-cd-text">版本 {version}</p>
          <p className="text-[11px] text-cd-text-tertiary mt-0.5">
            {!state.supported
              ? '在线更新仅在已安装的 Windows 版本中可用'
              : state.status === 'downloading'
                ? `正在下载 ${state.version || ''}…`
                : state.status === 'downloaded'
                  ? `${state.version || '新版本'} 已下载，等待安装`
                  : state.status === 'available'
                    ? `发现新版本 ${state.version || ''}`
                    : state.status === 'error'
                      ? '更新检查出错'
                      : '启动时会静默检查新版本'}
          </p>
        </div>
        <button
          onClick={doCheck}
          disabled={!state.supported || busyThis}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-cd-bg-secondary text-cd-text-secondary hover:bg-cd-hover border border-cd-border disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
        >
          {state.status === 'checking' ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          检查更新
        </button>
      </div>

      {state.status === 'downloading' && state.progress && (
        <div className="space-y-1">
          <div className="h-1.5 w-full rounded-full bg-cd-bg overflow-hidden">
            <div
              className="h-full bg-cd-green transition-all"
              style={{ width: `${Math.min(100, Math.max(0, state.progress.percent))}%` }}
            />
          </div>
          <p className="text-[10px] text-cd-text-tertiary">
            {state.progress.percent.toFixed(0)}% · {formatBytes(state.progress.transferred)} / {formatBytes(state.progress.total)}
          </p>
        </div>
      )}

      {state.status === 'available' && (
        <button
          onClick={doDownload}
          disabled={busy}
          className="w-full flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-medium bg-cd-green hover:bg-cd-green-dark text-white disabled:opacity-50 transition-colors"
        >
          <Download size={12} />
          下载 {state.version || '新版本'}
        </button>
      )}

      {state.status === 'downloaded' && (
        <button
          onClick={doInstall}
          disabled={busy}
          className="w-full flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-medium bg-cd-green hover:bg-cd-green-dark text-white disabled:opacity-50 transition-colors"
        >
          <Rocket size={12} />
          立即重启并安装
        </button>
      )}

      {state.status === 'not-available' && (
        <p className="flex items-center gap-1.5 text-[11px] text-cd-green">
          <CheckCircle size={12} /> 已是最新版本
        </p>
      )}

      {state.status === 'error' && state.error && (
        <p className="flex items-start gap-1.5 text-[11px] text-red-400 break-all">
          <AlertCircle size={12} className="mt-0.5 shrink-0" /> {state.error}
        </p>
      )}

      {state.status === 'available' && state.releaseNotes && (
        <details className="text-[11px] text-cd-text-tertiary">
          <summary className="cursor-pointer select-none">更新内容</summary>
          <pre className="mt-1 whitespace-pre-wrap font-sans text-[10px] max-h-32 overflow-auto">{state.releaseNotes}</pre>
        </details>
      )}
    </div>
  )
}
