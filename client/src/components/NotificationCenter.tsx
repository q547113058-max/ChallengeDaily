import { useState, useEffect, useCallback, useRef } from 'react'
import { Bell, Check, AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react'
import {
  getNotifications, markNotificationsRead, getUnreadNotificationCount,
  type AppNotification, type NotifyType,
} from '../api/client'
import { useVisibleInterval } from '../hooks/useVisibleInterval'
import { DATA_REFRESH_MS } from '../config/refresh'

const TYPE_ICON: Record<NotifyType, typeof Info> = {
  info: Info, success: CheckCircle2, warning: AlertTriangle, error: XCircle,
}
const TYPE_COLOR: Record<NotifyType, string> = {
  info: '#6B8AFD', success: '#22A06B', warning: '#D9910C', error: '#DC3545',
}
const CATEGORY_LABEL: Record<string, string> = {
  report: '日报', collector: '采集', ai: 'AI', disk: '磁盘',
  sync: '同步', todo: '待办', system: '系统',
}

/** 右上角通知中心：铃铛 + 未读红点 + 下拉列表。仅页面可见时轮询。 */
export default function NotificationCenter() {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<AppNotification[]>([])
  const [unread, setUnread] = useState(0)
  const [loading, setLoading] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    try {
      const [list, cnt] = await Promise.all([
        getNotifications({ limit: 50 }),
        getUnreadNotificationCount(),
      ])
      setItems(list.notifications.slice().reverse())
      setUnread(cnt.count)
    } catch { /* 拉通知失败不影响主界面 */ }
  }, [])

  useEffect(() => { load() }, [load])
  useVisibleInterval(load, DATA_REFRESH_MS)

  // 点外部关闭
  useEffect(() => {
    if (!open) return
    const h = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])

  const markAll = async () => {
    setLoading(true)
    try { await markNotificationsRead({ all: true }); await load() }
    finally { setLoading(false) }
  }

  return (
    <div className="relative" ref={wrapRef}>
      <button
        onClick={() => { setOpen(v => !v); if (!open) load() }}
        title="通知中心"
        aria-label="通知中心"
        className="relative w-8 h-6 flex items-center justify-center rounded hover:bg-cd-hover text-cd-text-tertiary transition-colors"
      >
        <Bell size={15} />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[15px] h-[15px] px-0.5 rounded-full text-[10px] font-bold flex items-center justify-center"
                style={{ background: '#DC3545', color: '#fff' }}>
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-8 w-[340px] max-w-[90vw] rounded-lg shadow-2xl z-[80] overflow-hidden"
             style={{ background: 'var(--cd-bg)', border: '1px solid var(--cd-border)' }}>
          <div className="flex items-center gap-2 px-4 py-3" style={{ borderBottom: '1px solid var(--cd-border)' }}>
            <Bell size={15} style={{ color: 'var(--cd-green)' }} />
            <span className="text-sm font-semibold flex-1" style={{ color: 'var(--cd-text)' }}>通知中心</span>
            {unread > 0 && (
              <button onClick={markAll} disabled={loading}
                className="flex items-center gap-1 text-xs px-2 py-1 rounded hover:opacity-70 disabled:opacity-40"
                style={{ color: 'var(--cd-green)' }}>
                <Check size={12} /> 全部已读
              </button>
            )}
          </div>

          <div className="max-h-[360px] overflow-y-auto">
            {items.length === 0 ? (
              <div className="px-4 py-8 text-center text-xs" style={{ color: 'var(--cd-text-tertiary)' }}>
                暂无通知
              </div>
            ) : items.map(n => {
              const Icon = TYPE_ICON[n.type] || Info
              return (
                <div key={n.id} className="flex gap-2.5 px-4 py-3"
                     style={{
                       borderBottom: '1px solid var(--cd-border)',
                       background: n.read_at ? 'transparent' : 'var(--cd-bg-secondary)',
                     }}>
                  <Icon size={15} className="mt-0.5 shrink-0" style={{ color: TYPE_COLOR[n.type] }} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm font-medium truncate" style={{ color: 'var(--cd-text)' }}>{n.title}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded shrink-0"
                            style={{ background: 'var(--cd-bg-tertiary)', color: 'var(--cd-text-tertiary)' }}>
                        {CATEGORY_LABEL[n.category] || n.category}
                      </span>
                    </div>
                    <div className="text-xs mt-1 leading-relaxed" style={{ color: 'var(--cd-text-secondary)' }}>{n.body}</div>
                    <div className="text-[10px] mt-1" style={{ color: 'var(--cd-text-tertiary)' }}>
                      {(n.created_at || '').replace('T', ' ').slice(5, 16)}
                      {!n.read_at && <span className="ml-2" style={{ color: 'var(--cd-green)' }}>· 未读</span>}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
