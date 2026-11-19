import { useEffect, useState } from 'react'
import { Sparkles, Check, X, Clock } from 'lucide-react'
import { decideAutoTodo, type AutoTodo } from '../api/bridge'
import { useToast } from './Toast'

const TTL_SEC = 300 // 与服务端 TODO_SYNC_PROPOSED_TTL 保持一致

type Props = {
  item: AutoTodo
  onDone: (id: number) => void
}

/** 审批弹窗：有新识别的待办时从右下角滑入，倒计时结束自动忽略。 */
export default function TodoApprovalToast({ item, onDone }: Props) {
  const [left, setLeft] = useState(TTL_SEC)
  const [busy, setBusy] = useState(false)
  const toast = useToast()

  useEffect(() => {
    setLeft(TTL_SEC)
    const t = setInterval(() => setLeft(v => Math.max(0, v - 1)), 1000)
    return () => clearInterval(t)
  }, [item.id])

  // 倒计时归零：视为「超时自动忽略」（服务端也会在 TTL 后自动 dismiss）
  useEffect(() => {
    if (left === 0 && !busy) {
      onDone(item.id)
    }
  }, [left, busy, item.id, onDone])

  const decide = async (action: 'approve' | 'reject') => {
    setBusy(true)
    try {
      await decideAutoTodo(item.id, action)
      toast.success(action === 'approve' ? '已加入待办' : '已忽略')
      onDone(item.id)
    } catch {
      toast.error('操作失败，请稍后重试')
      setBusy(false)
    }
  }

  const mm = String(Math.floor(left / 60)).padStart(2, '0')
  const ss = String(left % 60).padStart(2, '0')

  return (
    <div
      className="fixed bottom-24 right-6 z-[70] w-[340px] max-w-[92vw] rounded-xl shadow-2xl p-4"
      style={{ background: 'var(--cd-bg)', border: '1px solid var(--cd-border)' }}
      role="dialog"
      aria-label="待办审批"
    >
      <div className="flex items-start gap-2">
        <Sparkles size={16} className="mt-0.5 shrink-0" style={{ color: 'var(--cd-green)' }} />
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold mb-1" style={{ color: 'var(--cd-green)' }}>
            识别到一条新待办 · 待确认
          </div>
          <div className="text-sm font-medium leading-snug" style={{ color: 'var(--cd-text)' }}>
            {item.todo}
          </div>
          <div className="text-[11px] mt-1" style={{ color: 'var(--cd-text-tertiary)' }}>
            {item.project} · {item.confidence === 'high' ? '高置信' : '中等置信'}
          </div>
          {item.basis && (
            <div className="text-[11px] mt-1 italic" style={{ color: 'var(--cd-text-tertiary)' }}>
              依据：{item.basis}
            </div>
          )}
        </div>
        <button onClick={() => onDone(item.id)} title="暂不处理（超时后自动忽略）"
          className="p-1 rounded hover:opacity-70 shrink-0" style={{ color: 'var(--cd-text-tertiary)' }}>
          <X size={15} />
        </button>
      </div>

      <div className="flex items-center gap-2 mt-3">
        <button disabled={busy} onClick={() => decide('approve')}
          className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm font-medium text-white disabled:opacity-50"
          style={{ background: 'var(--cd-green)' }}>
          <Check size={15} /> 加入待办
        </button>
        <button disabled={busy} onClick={() => decide('reject')}
          className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm disabled:opacity-50"
          style={{ background: 'var(--cd-bg)', border: '1px solid var(--cd-border)', color: 'var(--cd-text)' }}>
          <X size={15} /> 忽略
        </button>
      </div>

      <div className="flex items-center justify-center gap-1 mt-2 text-[11px]"
           style={{ color: 'var(--cd-text-tertiary)' }}>
        <Clock size={11} /> {mm}:{ss} 后未处理将自动忽略
      </div>
      <div className="h-1 mt-2 rounded-full overflow-hidden" style={{ background: 'var(--cd-border)' }}>
        <div className="h-full transition-all duration-1000"
             style={{ width: `${(left / TTL_SEC) * 100}%`, background: 'var(--cd-green)' }} />
      </div>
    </div>
  )
}
