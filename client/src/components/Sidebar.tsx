import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  FileText,
  Clock,
  AppWindow,
  History,
  Bot,
  Settings as SettingsIcon,
  HelpCircle,
  Pause,
  Play,
  Loader2,
  CheckSquare,
  CalendarDays,
  Flame,
  Download,
  Target,
  ChevronDown,
  type LucideIcon,
} from 'lucide-react'
import { useState, useEffect } from 'react'
import { getStatus, isReadOnlySnapshot, pauseCollector, resumeCollector, getTodayStats, type CollectorStatus, type TodayStats } from '../api/client'
import { useTheme } from './ThemeContext'

// ─── 精简后的导航结构 ──────────────────────────────
// 设计原则：一个功能只有一个出口。报告三合一（生成/历史/导出）、
// 日历并入时间线、应用标签并入应用记录；数据看板/每日卡片/倒数日/热力图下线。

type NavChild = { to: string; icon: LucideIcon; label: string; desc?: string }
type NavParent = {
  to: string
  icon: LucideIcon
  label: string
  desc: string
  children?: NavChild[]
}

const NAV_GROUPS: { label: string; items: NavParent[] }[] = [
  {
    // 执行组：今天做什么
    label: '执行',
    items: [
      {
        to: '/',
        icon: LayoutDashboard,
        label: '今日总览',
        desc: '工作时长、活动摘要、AI 洞察',
      },
      {
        to: '/todos',
        icon: CheckSquare,
        label: '待办清单',
        desc: '今日待办与子任务树形管理',
      },
      {
        to: '/habits',
        icon: Flame,
        label: '习惯追踪',
        desc: '每日习惯打卡与连续天数',
      },
    ],
  },
  {
    // 计划组：目标 → 周 → 日，一个入口两个页签
    label: '计划',
    items: [
      {
        to: '/week-plan',
        icon: CalendarDays,
        label: '目标与排期',
        desc: '长期目标与周/日排期',
        children: [
          { to: '/week-plan', icon: CalendarDays, label: '计划排期' },
          { to: '/goals', icon: Target, label: '长期目标' },
        ],
      },
    ],
  },
  {
    // 统计组：记录与产出（报告三合一，时间线含日历）
    label: '统计',
    items: [
      {
        to: '/report',
        icon: FileText,
        label: '报告中心',
        desc: '生成日报/周报/月报、历史与导出',
        children: [
          { to: '/report', icon: FileText, label: '生成报告' },
          { to: '/history', icon: History, label: '历史报告' },
          { to: '/export', icon: Download, label: '数据导出' },
        ],
      },
      {
        to: '/timeline',
        icon: Clock,
        label: '时间线',
        desc: '逐条记录与日历视图',
      },
      {
        to: '/apps',
        icon: AppWindow,
        label: '应用记录',
        desc: '应用时长、标签与分类规则',
      },
    ],
  },
]

const MORE_NAV = [
  { to: '/agent', icon: Bot, label: '智能代理' },
  { to: '/settings', icon: SettingsIcon, label: '设置' },
]

export default function Sidebar() {
  const [status, setStatus] = useState<CollectorStatus | null>(null)
  const [todayStats, setTodayStats] = useState<TodayStats | null>(null)
  const { sidebarTranslucent } = useTheme()
  // 记录展开的父项（按 to 唯一标识）；默认展开当前路由所属的父项
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    let isVisible = !document.hidden
    const refresh = () => {
      if (!isVisible) return
      getStatus().then(setStatus).catch(() => setStatus(null))
      getTodayStats().then(setTodayStats).catch(() => setTodayStats(null))
    }
    refresh()
    const interval = setInterval(refresh, 30000)
    const handleVisibility = () => {
      const wasHidden = !isVisible
      isVisible = !document.hidden
      if (wasHidden && isVisible) refresh()
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [])

  // 根据当前 hash 路由自动展开对应的父项
  useEffect(() => {
    const syncExpand = () => {
      const hash = window.location.hash.replace('#', '') || '/'
      for (const group of NAV_GROUPS) {
        for (const parent of group.items) {
          if (!parent.children) continue
          const match = parent.children.some(c => hash === c.to || hash.startsWith(c.to + '/'))
          if (match) {
            setExpanded(parent.to)
            return
          }
        }
      }
    }
    syncExpand()
    window.addEventListener('hashchange', syncExpand)
    return () => window.removeEventListener('hashchange', syncExpand)
  }, [])

  const handleToggleCollector = async () => {
    try {
      if (status?.running && !status?.paused) {
        await pauseCollector()
      } else {
        await resumeCollector()
      }
      const newStatus = await getStatus()
      setStatus(newStatus)
    } catch (err) {
      console.error('Toggle collector failed:', err)
    }
  }

  const toggleExpand = (to: string) => {
    setExpanded(prev => (prev === to ? null : to))
  }

  return (
    <nav
      className="w-56 border-r border-cd-border flex flex-col shrink-0 select-none"
      style={{
        background: sidebarTranslucent ? 'var(--cd-sidebar-bg, var(--cd-sidebar))' : 'var(--cd-sidebar)',
        backdropFilter: sidebarTranslucent ? 'var(--cd-sidebar-blur)' : 'none',
        WebkitBackdropFilter: sidebarTranslucent ? 'var(--cd-sidebar-blur)' : 'none',
      }}
    >
      {/* ─── 顶部状态 ───────────────── */}
      <div className="px-5 pt-5 pb-4">
        <button
          onClick={isReadOnlySnapshot(status) ? undefined : handleToggleCollector}
          disabled={isReadOnlySnapshot(status)}
          className={`flex items-center gap-2 w-full px-2.5 py-1.5 rounded-lg transition-colors ${
            isReadOnlySnapshot(status)
              ? 'cursor-default'
              : status !== null && !status?.running
                ? 'bg-cd-red/8 hover:bg-cd-red/15 border border-cd-red/15'
                : 'hover:bg-cd-hover'
          }`}
        >
          <span
            className={`w-2 h-2 rounded-full ${
              isReadOnlySnapshot(status) ? 'bg-cd-green' : status === null ? 'bg-cd-text-tertiary animate-pulse' : (status?.running && !status?.paused) ? 'bg-cd-green animate-pulse-soft' : 'bg-cd-red'
            }`}
          />
          <span className={`text-xs ${isReadOnlySnapshot(status) ? 'text-cd-text-secondary' : status !== null && !(status?.running && !status?.paused) ? 'text-cd-red font-medium' : 'text-cd-text-secondary'}`}>
            {isReadOnlySnapshot(status) ? '只读 · 本机同步' : status === null ? '连接中...' : (status?.running && !status?.paused) ? '正在记录' : '已暂停 — 点击开始'}
          </span>
          {isReadOnlySnapshot(status) ? null : status === null ? (
            <Loader2 size={12} className="text-cd-text-tertiary ml-auto animate-spin" />
          ) : (status?.running && !status?.paused) ? (
            <Pause size={12} className="text-cd-text-tertiary ml-auto" />
          ) : (
            <Play size={12} className="text-cd-red ml-auto" />
          )}
        </button>
        <WorkTimeDisplay stats={todayStats} />
      </div>

      {/* ─── 核心导航 ─────────────────────── */}
      <div className="flex-1 overflow-y-auto px-2">
        {NAV_GROUPS.map((group, gi) => (
          <div key={group.label} className={gi === 0 ? '' : 'mt-4 mb-2'}>
            <div className="px-3 text-[10px] font-medium text-cd-text-tertiary uppercase tracking-wider mb-1">
              {group.label}
            </div>
            <div className="space-y-0.5">
              {group.items.map((parent) => {
                // 无子菜单：直接渲染为普通链接
                if (!parent.children) {
                  return (
                    <NavLink
                      key={parent.to}
                      to={parent.to}
                      end={parent.to === '/'}
                      className={({ isActive }) =>
                        `flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] transition-colors ${
                          isActive
                            ? 'bg-cd-green-light text-cd-green font-medium'
                            : 'text-cd-text-secondary hover:bg-cd-hover hover:text-cd-text'
                        }`
                      }
                      title={parent.desc}
                    >
                      <parent.icon size={16} />
                      {parent.label}
                    </NavLink>
                  )
                }
                // 有子菜单：渲染为可折叠组
                const isExpanded = expanded === parent.to
                const hasActiveChild = parent.children.some(
                  c => window.location.hash.replace('#', '') === c.to
                )
                return (
                  <div key={parent.to}>
                    <button
                      onClick={() => toggleExpand(parent.to)}
                      className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] w-full transition-colors ${
                        hasActiveChild && isExpanded
                          ? 'text-cd-text font-medium'
                          : 'text-cd-text-secondary hover:bg-cd-hover hover:text-cd-text'
                      }`}
                      title={parent.desc}
                    >
                      <parent.icon size={16} />
                      <span className="flex-1 text-left">{parent.label}</span>
                      <ChevronDown
                        size={14}
                        className={`text-cd-text-tertiary transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                      />
                    </button>
                    {isExpanded && (
                      <div className="ml-4 mt-0.5 space-y-0.5 border-l border-cd-border pl-2">
                        {parent.children.map((child) => (
                          <NavLink
                            key={child.to + child.label}
                            to={child.to}
                            className={({ isActive }) =>
                              `flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[12px] transition-colors ${
                                isActive
                                  ? 'bg-cd-green-light text-cd-green font-medium'
                                  : 'text-cd-text-tertiary hover:bg-cd-hover hover:text-cd-text'
                              }`
                            }
                          >
                            <child.icon size={13} />
                            {child.label}
                          </NavLink>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        ))}

        {/* ─── 更多 ──────────────────────── */}
        <div className="mt-4 mb-2">
          <div className="px-3 text-[10px] font-medium text-cd-text-tertiary uppercase tracking-wider mb-1">
            更多
          </div>
          <div className="space-y-0.5">
            {MORE_NAV.map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to + label}
                to={to}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] transition-colors ${
                    isActive
                      ? 'bg-cd-green-light text-cd-green font-medium'
                      : 'text-cd-text-secondary hover:bg-cd-hover hover:text-cd-text'
                  }`
                }
              >
                <Icon size={16} />
                {label}
              </NavLink>
            ))}
          </div>
        </div>
      </div>

      {/* ─── 底部用户信息 ─────────────────────── */}
      <div className="px-4 py-3 border-t border-cd-border">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-full flex items-center justify-center bg-cd-green/20 shrink-0">
            <svg viewBox="0 0 24 24" className="w-4 h-4 text-cd-green" fill="currentColor">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
            </svg>
          </div>
          <div>
            <div className="text-xs text-cd-text font-medium leading-tight">橙紫Challenge</div>
            <div className="text-[10px] text-cd-gold leading-tight font-brand">Extreme Preview</div>
          </div>
        </div>
      </div>
    </nav>
  )
}

function WorkTimeDisplay({ stats }: { stats: TodayStats | null }) {
  if (!stats) return null

  const totalMin = stats.total_duration_min
  const hours = Math.floor(totalMin / 60)
  const mins = Math.round(totalMin % 60)
  const targetMin = 8 * 60
  const pct = Math.min(100, Math.round((totalMin / targetMin) * 100))
  const radius = 18
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (pct / 100) * circumference

  return (
    <div className="flex items-center gap-3 mt-2 px-2.5 py-2 rounded-lg bg-cd-bg-secondary">
      <svg width="44" height="44" viewBox="0 0 44 44" className="shrink-0">
        <circle
          cx="22" cy="22" r={radius}
          fill="none" stroke="var(--cd-border)" strokeWidth="3"
        />
        <circle
          cx="22" cy="22" r={radius}
          fill="none" stroke="var(--cd-green)" strokeWidth="3"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform="rotate(-90 22 22)"
          className="transition-all duration-700"
        />
        <text
          x="22" y="22"
          textAnchor="middle" dominantBaseline="central"
          className="text-[9px] font-bold fill-cd-green"
        >
          {pct}%
        </text>
      </svg>
      <div className="min-w-0">
        <div className="text-xs font-semibold text-cd-text">
          {hours > 0 ? `${hours}h ${mins}m` : `${mins}m`}
        </div>
        <div className="text-[10px] text-cd-text-tertiary">
          今日工作时长
        </div>
      </div>
    </div>
  )
}
