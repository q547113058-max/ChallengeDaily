import { lazy, Suspense } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileText, History, Download } from 'lucide-react'

// 报告中心：把「生成 / 历史 / 导出」三个页面收成一个入口 + 三个页签。
// 路由仍然是 /report、/history、/export，旧链接和书签都还能用。
const Report = lazy(() => import('./Report'))
const HistoryReports = lazy(() => import('./HistoryReports'))
const ExportCenter = lazy(() => import('./ExportCenter'))

export type ReportsTab = 'generate' | 'history' | 'export'

const TABS: { key: ReportsTab; label: string; to: string; icon: typeof FileText }[] = [
  { key: 'generate', label: '生成报告', to: '/report', icon: FileText },
  { key: 'history', label: '历史报告', to: '/history', icon: History },
  { key: 'export', label: '数据导出', to: '/export', icon: Download },
]

export default function ReportsHub({ tab }: { tab: ReportsTab }) {
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
        {tab === 'generate' && <Report />}
        {tab === 'history' && <HistoryReports />}
        {tab === 'export' && <ExportCenter />}
      </Suspense>
    </div>
  )
}
