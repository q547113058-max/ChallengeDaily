import { useState, useEffect, useCallback, useRef } from 'react'
import {
  CheckSquare, X, Check, Ban, RefreshCw, ChevronDown, ChevronUp,
  Sparkles, ListTodo, ExternalLink, WifiOff, Inbox,
} from 'lucide-react'
import { getTodos, updateTodo, type Todo } from '../api/client'
import {
  getBridgeStatus, getAutoTodos, setAutoTodoStatus, subscribeBridgeEvents,
  decideAutoTodo, type AutoTodo, type BridgeEvent,
} from '../api/bridge'
import { useToast } from './Toast'
// TodoApprovalToast 已由 Electron 主进程的桌面顶层弹窗取代，不再在应用内渲染
import { DATA_REFRESH_MS } from '../config/refresh'
import { useVisibleInterval } from '../hooks/useVisibleInterval'

type LocalTodo = Pick<Todo, 'id' | 'title' | 'category' | 'status' | 'priority' | 'due_date'>

/**
 * 右下悬浮球 + 右侧抽屉看板。
 * 合并显示两类待办：
 *  - 本地：ChallengeDaily 原有 /api/todos（手动建的清单）
 *  - 自动：屏幕追踪系统识别出的待办（经 /api/bridge 代理到线上同步服务）
 * 悬浮球常驻、抽屉点外部/ESC 收起，状态记忆在 localStorage。
 */
export default function TodoDock() {
  const [open, setOpen] = useState(false)
  const [local, setLocal] = useState<LocalTodo[]>([])
  const [auto, setAuto] = useState<AutoTodo[]>([])
  const [proposed, setProposed] = useState<AutoTodo[]>([])
  // SSE 只广播「新插入」，不回放历史；用 ref 记住已见过的 id，避免重复插入待确认区。
  const seenInsert = useRef<Set<number>>(new Set())
  const [bridgeEnabled, setBridgeEnabled] = useState(false)
  const [bridgeMsg, setBridgeMsg] = useState('')
  const [loading, setLoading] = useState(false)
  const [showDone, setShowDone] = useState(false)
  const [busy, setBusy] = useState<number | null>(null)
  const toast = useToast()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await getTodos('pending')
      setLocal(r.todos as LocalTodo[])
    } catch {
      toast.error('本地待办加载失败')
    }
    try {
      const st = await getBridgeStatus()
      setBridgeEnabled(!!st.enabled)
      if (!st.enabled) {
        setBridgeMsg(st.reason || '同步服务不可用')
        setAuto([])
        setProposed([])
      } else {
        const [rp, rq] = await Promise.all([
          getAutoTodos('pending'),
          getAutoTodos('proposed'),
        ])
        setAuto(rp.todos || [])
        setProposed(rq.todos || [])
        setBridgeMsg('')
      }
    } catch {
      setBridgeEnabled(false)
      setBridgeMsg('同步服务连接失败')
      setAuto([])
      setProposed([])
    }
    setLoading(false)
  }, [toast])

  // load 依赖 toast，而 ToastProvider 的 value 每次渲染都新建对象，故 load 身份不稳定。
  // 用 ref 保存最新引用，让 SSE 订阅 / 挂载拉取都不必反复重建。
  const loadRef = useRef(load)
  loadRef.current = load

  // 常驻 SSE 订阅：新待办刚被识别（insert 事件）就进抽屉「待确认」区，
  // 不依赖抽屉是否打开。已见过的 id 不重复插入。
  useEffect(() => {
    const stop = subscribeBridgeEvents((e: BridgeEvent) => {
      if (e.action === 'insert' && e.detail) {
        const d = e.detail
        if (seenInsert.current.has(d.id)) return
        seenInsert.current.add(d.id)
        setProposed(prev => prev.some(x => x.id === d.id) ? prev : [d, ...prev])
      } else if (e.action === 'status') {
        // 审批 / TTL 超时忽略 / 其它设备操作 → 都要即时刷新本地视图，
        // 否则过期的 proposed 会变成「看得见点不动」的僵尸条目。
        setProposed(prev => prev.filter(x => x.id !== e.id))
        setAuto(prev => prev.filter(x => x.id !== e.id))
        // 任何 status 变更都复核一次，保证与服务端一致
        loadRef.current()
      }
    })
    return stop
  }, [])

  // 挂载即拉一次（不依赖抽屉是否打开）：保证红点/待审数正确。
  // 用 didMount ref 保证「只拉一次」，避免 load 身份不稳定导致重复请求。
  const didMount = useRef(false)
  useEffect(() => {
    if (didMount.current) return
    didMount.current = true
    loadRef.current()
  }, [])
  useVisibleInterval(load, DATA_REFRESH_MS)

  // ESC 关闭
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open])

  const doneLocal = async (t: LocalTodo) => {
    setBusy(t.id)
    try {
      await updateTodo(t.id, { status: 'completed' } as Partial<Todo>)
      setLocal(prev => prev.filter(x => x.id !== t.id))
      toast.success('已完成')
    } catch { toast.error('操作失败') }
    setBusy(null)
  }

  const actAuto = async (t: AutoTodo, status: 'done' | 'dismissed') => {
    if (busy === -t.id) return
    setBusy(-t.id)
    try {
      const res = await setAutoTodoStatus(t.id, status)
      // 不管 changed 是否为 true（TTL 过期后重复忽略 changed=false），都从本地移除
      setAuto(prev => prev.filter(x => x.id !== t.id))
      setProposed(prev => prev.filter(x => x.id !== t.id))
      toast.success(status === 'done' ? '已完成' : '已忽略')
      // 从服务端复核一次，避免僵尸条目复活
      loadRef.current()
      return res
    } catch {
      toast.error('操作失败，请重试')
    } finally {
      setBusy(null)
    }
  }

  // 审批（从弹窗或抽屉的待审区）：approve 加入待办 / reject 忽略
  const decide = async (t: AutoTodo, action: 'approve' | 'reject') => {
    setBusy(-t.id)
    try {
      await decideAutoTodo(t.id, action)
      setProposed(prev => prev.filter(x => x.id !== t.id))
      if (action === 'approve') {
        setAuto(prev => [{ ...t, status: 'pending' }, ...prev])
        toast.success('已加入待办')
      } else {
        toast.success('已忽略')
      }
    } catch { toast.error('操作失败，请稍后重试') }
    setBusy(null)
  }

  const pendingCount = local.length + auto.length + proposed.length

  return (
    <>
      {/* 应用内浮动审批卡已停用：桌面顶层弹窗由 Electron 主进程的
          todo-popup.cjs 提供（alwaysOnTop，主窗口不开也能看见）。
          抽屉里的「待确认」区仍可就地审批，这里不再重复弹一张卡。 */}

      {/* 悬浮球 */}
      <button
        onClick={() => setOpen(v => !v)}
        title="待办看板（点击展开/收起）"
        aria-label="待办看板"
        className="fixed bottom-6 right-6 z-[60] w-14 h-14 rounded-full shadow-lg flex items-center justify-center transition-transform hover:scale-105 active:scale-95"
        style={{ background: 'var(--cd-green)', color: '#fff' }}
      >
        {open ? <X size={22} /> : <CheckSquare size={24} />}
        {!open && pendingCount > 0 && (
          <span
            className="absolute -top-1 -right-1 min-w-[20px] h-5 px-1 rounded-full text-[11px] font-bold flex items-center justify-center"
            style={{ background: '#ef4444', color: '#fff' }}
          >{pendingCount > 99 ? '99+' : pendingCount}</span>
        )}
      </button>

      {/* 遮罩（点外部收起，半透明但不挡交互） */}
      {open && (
        <div className="fixed inset-0 z-[55] bg-black/20" onClick={() => setOpen(false)} />
      )}

      {/* 右侧抽屉 */}
      <aside
        className="fixed top-0 right-0 h-full z-[58] flex flex-col shadow-2xl transition-transform duration-300"
        style={{
          width: 'min(420px, 92vw)',
          background: 'var(--cd-bg)',
          borderLeft: '1px solid var(--cd-border)',
          transform: open ? 'translateX(0)' : 'translateX(100%)',
        }}
        aria-hidden={!open}
      >
        {/* 头部 */}
        <div className="px-5 py-4 flex items-center gap-2" style={{ borderBottom: '1px solid var(--cd-border)' }}>
          <ListTodo size={20} style={{ color: 'var(--cd-green)' }} />
          <h2 className="text-base font-semibold flex-1" style={{ color: 'var(--cd-text)' }}>待办看板</h2>
          <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: 'var(--cd-bg)', color: 'var(--cd-text-tertiary)' }}>
            {pendingCount} 待处理
          </span>
          <button onClick={load} title="刷新" className="p-1.5 rounded hover:opacity-70" style={{ color: 'var(--cd-text-tertiary)' }}>
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <button onClick={() => setOpen(false)} title="收起" className="p-1.5 rounded hover:opacity-70" style={{ color: 'var(--cd-text-tertiary)' }}>
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {/* ── 待审（新识别，等用户决定要不要进待办）── */}
          {bridgeEnabled && proposed.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-2">
                <Inbox size={15} style={{ color: 'var(--cd-green)' }} />
                <h3 className="text-sm font-semibold" style={{ color: 'var(--cd-text)' }}>待确认</h3>
                <span className="text-xs px-1.5 py-0.5 rounded-full"
                      style={{ background: 'var(--cd-green)', color: '#fff' }}>{proposed.length}</span>
                <span className="text-xs ml-auto" style={{ color: 'var(--cd-text-tertiary)' }}>5 分钟未处理自动忽略</span>
              </div>
              <ul className="space-y-2">
                {proposed.map(t => (
                  <li key={t.id} className="p-3 rounded-lg"
                      style={{ background: 'var(--cd-bg)', border: '1px solid var(--cd-green)' }}>
                    <div className="text-sm font-medium" style={{ color: 'var(--cd-text)' }}>{t.todo}</div>
                    <div className="text-[11px] mt-1" style={{ color: 'var(--cd-text-tertiary)' }}>
                      {t.project} · {t.source_ts || t.created_at.slice(5, 16)}
                    </div>
                    {t.basis && <div className="text-[11px] mt-1 italic" style={{ color: 'var(--cd-text-tertiary)' }}>依据：{t.basis}</div>}
                    <div className="flex gap-2 mt-2">
                      <button disabled={busy === -t.id} onClick={() => decide(t, 'approve')}
                        className="flex-1 py-1.5 rounded-lg text-xs text-white disabled:opacity-50"
                        style={{ background: 'var(--cd-green)' }}>加入待办</button>
                      <button disabled={busy === -t.id} onClick={() => decide(t, 'reject')}
                        className="flex-1 py-1.5 rounded-lg text-xs disabled:opacity-50"
                        style={{ border: '1px solid var(--cd-border)', color: 'var(--cd-text)' }}>忽略</button>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* ── 自动识别（已加入待办的 pending）── */}
          <section>
            <div className="flex items-center gap-2 mb-2">
              <Sparkles size={15} style={{ color: 'var(--cd-green)' }} />
              <h3 className="text-sm font-semibold" style={{ color: 'var(--cd-text)' }}>自动识别</h3>
              <span className="text-xs" style={{ color: 'var(--cd-text-tertiary)' }}>
                {auto.length} 条
              </span>
            </div>
            {!bridgeEnabled ? (
              <div className="flex items-center gap-2 text-xs px-3 py-3 rounded-lg"
                   style={{ background: 'var(--cd-bg)', color: 'var(--cd-text-tertiary)' }}>
                <WifiOff size={14} /> {bridgeMsg || '未启用'}（不影响本地待办）
              </div>
            ) : auto.length === 0 ? (
              <div className="text-xs px-3 py-3 rounded-lg" style={{ background: 'var(--cd-bg)', color: 'var(--cd-text-tertiary)' }}>
                暂无自动识别的待办
              </div>
            ) : (
              <ul className="space-y-2">
                {auto.map(t => (
                  <li key={t.id} className="p-3 rounded-lg" style={{ background: 'var(--cd-bg)', border: '1px solid var(--cd-border)' }}>
                    <div className="flex items-start gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium" style={{ color: 'var(--cd-text)' }}>{t.todo}</div>
                        <div className="text-[11px] mt-1" style={{ color: 'var(--cd-text-tertiary)' }}>
                          {t.project} · {t.source_ts || t.created_at.slice(5, 16)}
                          {t.confidence === 'high' && ' · 高置信'}
                        </div>
                        {t.basis && (
                          <div className="text-[11px] mt-1 italic" style={{ color: 'var(--cd-text-tertiary)' }}>依据：{t.basis}</div>
                        )}
                      </div>
                      <div className="flex gap-1 shrink-0">
                        <button disabled={busy === -t.id} onClick={() => actAuto(t, 'done')}
                          title="完成" className="p-1.5 rounded hover:opacity-70" style={{ color: 'var(--cd-green)' }}>
                          <Check size={15} />
                        </button>
                        <button disabled={busy === -t.id} onClick={() => actAuto(t, 'dismissed')}
                          title="忽略（以后不再出现）" className="p-1.5 rounded hover:opacity-70" style={{ color: 'var(--cd-text-tertiary)' }}>
                          <Ban size={15} />
                        </button>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* ── 本地待办 ── */}
          <section>
            <div className="flex items-center gap-2 mb-2">
              <CheckSquare size={15} style={{ color: 'var(--cd-green)' }} />
              <h3 className="text-sm font-semibold flex-1" style={{ color: 'var(--cd-text)' }}>本地待办</h3>
              <span className="text-xs" style={{ color: 'var(--cd-text-tertiary)' }}>{local.length} 条</span>
              <a href="#/todos" onClick={() => setOpen(false)} title="打开完整清单"
                 className="p-1 rounded hover:opacity-70" style={{ color: 'var(--cd-text-tertiary)' }}>
                <ExternalLink size={14} />
              </a>
            </div>
            {local.length === 0 ? (
              <div className="text-xs px-3 py-3 rounded-lg" style={{ background: 'var(--cd-bg)', color: 'var(--cd-text-tertiary)' }}>
                暂无待办，去「待办清单」新建一条吧
              </div>
            ) : (
              <ul className="space-y-2">
                {local.map(t => (
                  <li key={t.id} className="p-3 rounded-lg flex items-center gap-2"
                      style={{ background: 'var(--cd-bg)', border: '1px solid var(--cd-border)' }}>
                    <button disabled={busy === t.id} onClick={() => doneLocal(t)}
                      title="标记完成" className="w-5 h-5 rounded-full border-2 shrink-0 hover:opacity-70"
                      style={{ borderColor: 'var(--cd-green)' }} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm truncate" style={{ color: 'var(--cd-text)' }}>{t.title}</div>
                      <div className="text-[11px] mt-0.5" style={{ color: 'var(--cd-text-tertiary)' }}>
                        {t.category}{t.due_date ? ` · 截止 ${t.due_date}` : ''}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* 已完成折叠区（预留，避免抽屉内容过多） */}
          <button onClick={() => setShowDone(v => !v)}
            className="w-full flex items-center justify-center gap-1 text-xs py-2 rounded-lg"
            style={{ color: 'var(--cd-text-tertiary)', background: 'var(--cd-bg)' }}>
            {showDone ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            {showDone ? '收起说明' : '关于看板'}
          </button>
          {showDone && (
            <div className="text-[11px] leading-relaxed px-3 py-2 rounded-lg"
                 style={{ background: 'var(--cd-bg)', color: 'var(--cd-text-tertiary)' }}>
              自动识别来自屏幕追踪系统：定时截图 → 视觉模型判断在做什么 → 文本模型归纳出有依据的待办，
              经同步服务汇总。每条都带时间与依据，可核对后完成或忽略；忽略后相似候选不再出现。
              「本地待办」是你在 ChallengeDaily 手动建的任务，点圆圈即可标记完成。
            </div>
          )}
        </div>

        <div className="px-5 py-3 text-[11px] text-center" style={{ borderTop: '1px solid var(--cd-border)', color: 'var(--cd-text-tertiary)' }}>
          每 30 秒自动刷新 · ESC 或点外部收起
        </div>
      </aside>
    </>
  )
}
