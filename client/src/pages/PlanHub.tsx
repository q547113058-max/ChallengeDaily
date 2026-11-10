import { lazy, Suspense } from 'react'
import { useNavigate } from 'react-router-dom'
import { CalendarDays, Target } from 'lucide-react'

// 计划中心：把「计划排期」和「长期目标」收成一个入口 + 两个页签。
// 目标 → 周 → 日 是一个连续的心智路径，不该是两个并列的一级页。
const WeekPlan = lazy(() => import('./WeekPlan'))
const Goals = lazy(() => import('./Goals'))

export type PlanTab = 'schedule' | 'goals'

const TABS: { key: PlanTab; label: string; to: string; icon: typeof CalendarDays }[] = [
  { key: 'schedule', label: '计划排期', to: '/week-plan', icon: CalendarDays },
  { key: 'goals', label: '长期目标', to: '/goals', icon: Target },
]

export default function PlanHub({ tab }: { tab: PlanTab }) {
  const navigate = useNavigate()

  return (
    <div>
      <div className="mb-5 flex items-center gap-1 border-b border-cd-border">
        {TABS.map((t) => {
          const active = t.key === tab
          const Icon = t.icon
          return (
            <button
              key={t.key}
              onClick={() => navigate(t.to)}
              className={`-mb-px flex items-center gap-1.5 border-b-2 px-3.5 py-2 text-sm transition-colors ${
                active
                  ? 'border-cd-orange font-medium text-cd-text'
                  : 'border-transparent text-cd-text-secondary hover:text-cd-text'
              }`}
            >
              <Icon size={14} />
              {t.label}
            </button>
          )
        })}
      </div>

      <Suspense fallback={<div className="py-10 text-sm text-cd-text-secondary">加载中…</div>}>
        {tab === 'schedule' && <WeekPlan />}
        {tab === 'goals' && <Goals />}
      </Suspense>
    </div>
  )
}
