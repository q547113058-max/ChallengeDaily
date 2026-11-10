import { useState, useEffect, useRef, lazy, Suspense, type ReactNode } from 'react'
import { HashRouter, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import TitleBar from './components/TitleBar'
import { ErrorBoundary } from './components/ErrorBoundary'
import { ToastProvider } from './components/Toast'
import { ThemeProvider } from './components/ThemeContext'
import { BackendStatusBar } from './components/shared'
import { getNotifications, startupHealthCheck } from './api/client'
import { serverStorage, loadServerState, isServerStorageLoaded, initServerStorageLifecycle } from './api/clientState'
import { useAppLock, LockScreen } from './components/AppLock'
import { CommandPalette, useCommandPaletteShortcut } from './components/CommandPalette'
import { ShortcutHelp, useShortcutHelpShortcut } from './components/ShortcutHelp'

// 懒加载页面组件 — 减少首屏加载体积
// 精简后只保留 4 个一级入口 + 设置里的两个分析页
const Overview = lazy(() => import('./pages/Overview'))
const Timeline = lazy(() => import('./pages/Timeline'))
const ReportsHub = lazy(() => import('./pages/ReportsHub'))
const Settings = lazy(() => import('./pages/Settings'))
const AgentPage = lazy(() => import('./pages/Agent'))
const Onboarding = lazy(() => import('./pages/Onboarding'))
const Legal = lazy(() => import('./pages/Legal'))
const DeepProfile = lazy(() => import('./pages/DeepProfile'))
const Health = lazy(() => import('./pages/Health'))
const Todos = lazy(() => import('./pages/Todos'))
const Habits = lazy(() => import('./pages/Habits'))
const PlanHub = lazy(() => import('./pages/PlanHub'))
const AppRecords = lazy(() => import('./pages/AppRecords'))

// 首次启动流程：法律协议 → 新手引导 → 主界面
type FirstLaunchPhase = 'legal' | 'onboarding' | 'done'

export default function App() {
  const [backendReady, setBackendReady] = useState(false)
  const [checking, setChecking] = useState(true)
  // 服务器状态（原 localStorage 数据）是否已加载：未加载前不渲染主体，
  // 避免同步读取拿到空值导致主题/首启/应用锁状态错乱。
  const [stateLoaded, setStateLoaded] = useState(() => isServerStorageLoaded())
  const [firstLaunchPhase, setFirstLaunchPhase] = useState<FirstLaunchPhase>('done')
  const { locked, unlock } = useAppLock()
  const [cmdPaletteOpen, setCmdPaletteOpen] = useState(false)
  useCommandPaletteShortcut(() => setCmdPaletteOpen(true))
  const [shortcutHelpOpen, setShortcutHelpOpen] = useState(false)
  useShortcutHelpShortcut(() => setShortcutHelpOpen(true))

  useEffect(() => {
    let isCancelled = false
    let attempts = 0
    let timerId: ReturnType<typeof setTimeout> | null = null
    // E9: 启动阶段最大重试：30次1秒 + 30次3秒 ≈ 2分钟（从6分钟缩短）
    const PHASE1_ATTEMPTS = 30
    const MAX_ATTEMPTS = 60

    const scheduleNext = (delay: number) => {
      if (isCancelled) return
      if (timerId !== null) clearTimeout(timerId)
      timerId = setTimeout(async () => {
        if (isCancelled) return
        attempts++
        try {
          // 使用 startupHealthCheck（原始 fetch），不经过 request() 状态机
          // 避免启动阶段的正常等待被误判为"后端断开"
          const ok = await startupHealthCheck()
          if (isCancelled) return
          if (ok) {
            setBackendReady(true)
            setChecking(false)
            return
          }
        } catch {
          // startupHealthCheck 内部已 catch，不会到这里
        }
        if (isCancelled) return
        if (attempts === PHASE1_ATTEMPTS) {
          // 1 秒轮询仍失败，切换到 3 秒轮询
          setChecking(false)
          scheduleNext(3000)
          return
        }
        if (attempts >= MAX_ATTEMPTS) {
          // 达到上限，停止轮询，由 ErrorScreen 提供手动重试
          setChecking(false)
          return
        }
        // 根据当前阶段决定延迟
        const currentDelay = attempts < PHASE1_ATTEMPTS ? 1000 : 3000
        scheduleNext(currentDelay)
      }, delay)
    }

    scheduleNext(1000)
    return () => {
      isCancelled = true
      if (timerId !== null) clearTimeout(timerId)
    }
  }, [])

  // 后端就绪后，把服务器上的客户端状态一次性拉到内存缓存（含旧 localStorage 迁移）
  useEffect(() => {
    if (!backendReady || stateLoaded) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null
    const attempt = async () => {
      try {
        await loadServerState()
        if (!cancelled) setStateLoaded(true)
      } catch {
        // 加载失败（如 token 尚未就绪）：1 秒后重试，最多约 30 秒
        if (!cancelled) timer = setTimeout(attempt, 1000)
      }
    }
    initServerStorageLifecycle()
    void attempt()
    return () => { cancelled = true; if (timer) clearTimeout(timer) }
  }, [backendReady, stateLoaded])

  // 状态加载完成后再判定首启流程（全部读服务器缓存，同步）
  useEffect(() => {
    if (backendReady && stateLoaded) {
      const legalDone = serverStorage.getItem('cd_legal_accepted')
      const onboardingDone = serverStorage.getItem('cd_onboarding_done')
      if (!legalDone) {
        setFirstLaunchPhase('legal')
      } else if (!onboardingDone) {
        setFirstLaunchPhase('onboarding')
      } else {
        setFirstLaunchPhase('done')
      }
    }
  }, [backendReady, stateLoaded])

  const handleLegalAccepted = () => {
    serverStorage.setItem('cd_legal_accepted', '1')
    const onboardingDone = serverStorage.getItem('cd_onboarding_done')
    if (!onboardingDone) {
      setFirstLaunchPhase('onboarding')
    } else {
      setFirstLaunchPhase('done')
    }
  }

  const handleOnboardingComplete = () => {
    serverStorage.setItem('cd_onboarding_done', '1')
    setFirstLaunchPhase('done')
  }

  // ── 桌面通知轮询 ──
  const notifiedIds = useRef(new Set<number>())
  useEffect(() => {
    if (!backendReady) return
    const poll = async () => {
      try {
        const { notifications } = await getNotifications()
        for (const n of notifications) {
          if (!notifiedIds.current.has(n.id)) {
            notifiedIds.current.add(n.id)
            // 通过 Electron 弹出系统通知
            if (window.electronAPI?.showNotification) {
              window.electronAPI.showNotification({ title: n.title, body: n.body })
            }
          }
        }
      } catch {
        // 通知轮询失败不影响主流程
      }
    }
    // 优化：从 30 秒调整为 60 秒，窗口隐藏时暂停轮询
    poll()
    const interval = setInterval(() => {
      if (!document.hidden) poll()
    }, 60000)
    // 窗口恢复可见时立即检查一次
    const onVisible = () => { if (!document.hidden) poll() }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [backendReady])

  return (
    <ThemeProvider>
      <ToastProvider>
        <ErrorBoundary>
          {/* 应用级隐私锁：启动锁 + 闲置锁 */}
          {locked && <LockScreen onUnlock={unlock} />}
          <div className="flex flex-col h-screen bg-cd-bg">
            <TitleBar />
          <BackendStatusBar />
          <div className="flex flex-1 overflow-hidden">
            {checking || (backendReady && !stateLoaded) ? (
              <LoadingScreen />
            ) : !backendReady ? (
              <ErrorScreen />
            ) : firstLaunchPhase === 'legal' ? (
              <Suspense fallback={<PageSpinner />}>
                <Legal onAccept={handleLegalAccepted} />
              </Suspense>
            ) : firstLaunchPhase === 'onboarding' ? (
              <Onboarding onComplete={handleOnboardingComplete} />
            ) : (
              <HashRouter>
                <CommandPalette open={cmdPaletteOpen} onClose={() => setCmdPaletteOpen(false)} />
                <ShortcutHelp open={shortcutHelpOpen} onClose={() => setShortcutHelpOpen(false)} />
                <ElectronNavigationBridge />
                <Sidebar />
                <main className="flex-1 overflow-auto bg-cd-bg p-6">
                  <RouteErrorBoundary>
                    <Suspense fallback={<PageSpinner />}>
                      <Routes>
                        <Route path="/" element={<Overview />} />
                        <Route path="/timeline" element={<Timeline />} />
                        <Route path="/report" element={<ReportsHub tab="generate" />} />
                        <Route path="/history" element={<ReportsHub tab="history" />} />
                        <Route path="/export" element={<ReportsHub tab="export" />} />
                        <Route path="/week-plan" element={<PlanHub tab="schedule" />} />
                        <Route path="/todos" element={<Todos />} />
                        <Route path="/apps" element={<AppRecords />} />
                        <Route path="/agent" element={<AgentPage />} />
                        <Route path="/settings" element={<Settings />} />
                        <Route path="/profile" element={<DeepProfile />} />
                        <Route path="/deep-insight" element={<DeepProfile />} />
                        <Route path="/goals" element={<PlanHub tab="goals" />} />
                        <Route path="/habits" element={<Habits />} />
                        <Route path="/health" element={<Health />} />
                        {/* 精简后合并的入口：旧链接重定向，避免书签失效 */}
                        <Route path="/dashboard" element={<Navigate to="/" replace />} />
                        <Route path="/daily-cards" element={<Navigate to="/report" replace />} />
                        <Route path="/countdowns" element={<Navigate to="/goals" replace />} />
                        <Route path="/heatmap" element={<Navigate to="/timeline" replace />} />
                        <Route path="/calendar" element={<Navigate to="/timeline" replace />} />
                        <Route path="/app-tags" element={<Navigate to="/apps" replace />} />
                        <Route path="*" element={<NotFoundPage />} />
                      </Routes>
                    </Suspense>
                  </RouteErrorBoundary>
                </main>
              </HashRouter>
            )}
          </div>
        </div>
      </ErrorBoundary>
    </ToastProvider>
  </ThemeProvider>
  )
}

function PageSpinner() {
  return (
    <div className="flex items-center justify-center py-20">
      <div className="w-6 h-6 border-3 border-cd-green border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

/** P13-4：监听来自 Electron 主进程的导航/快捷键事件 */
function ElectronNavigationBridge() {
  const navigate = useNavigate()
  useEffect(() => {
    if (!window.electronAPI) return
    // 监听全局快捷键导航（全局快捷键→跳转页面）
    const onNav = (path: string) => {
      const pathMap: Record<string, string> = {
        report: '/report',
        overview: '/',
        habits: '/habits',
      }
      const target = pathMap[path] || path
      navigate(target)
    }
    // 使用通用事件监听（onNavigateTo 已在 preload 声明）
    if (window.electronAPI?.onNavigateTo) {
      window.electronAPI.onNavigateTo(onNav)
    }
    return () => { /* IPC 监听器随组件卸载自动清理 */ }
  }, [navigate])
  return null
}

/** 绑定到当前路由的 ErrorBoundary：路由切换时自动清除错误状态 */
function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const location = useLocation()
  return (
    <ErrorBoundary resetKey={location.pathname}>
      {children}
    </ErrorBoundary>
  )
}

function LoadingScreen() {
  return (
    <div className="flex-1 flex items-center justify-center bg-cd-bg">
      <div className="text-center">
        <div className="w-10 h-10 border-4 border-cd-green border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-cd-text-tertiary text-sm">正在连接后端服务...</p>
      </div>
    </div>
  )
}

function ErrorScreen() {
  const [retrying, setRetrying] = useState(false)
  const [autoRetries, setAutoRetries] = useState(0)
  const maxAutoRetries = 20

  // 自动重试：后端可能还在启动中，每3秒自动探测一次
  useEffect(() => {
    if (autoRetries >= maxAutoRetries) return
    const timer = setTimeout(async () => {
      const ok = await startupHealthCheck()
      if (ok) {
        window.location.reload()
      } else {
        setAutoRetries(prev => prev + 1)
      }
    }, 3000)
    return () => clearTimeout(timer)
  }, [autoRetries])

  const handleRetry = async () => {
    setRetrying(true)
    try {
      const ok = await startupHealthCheck()
      if (ok) {
        window.location.reload()
      } else {
        setRetrying(false)
      }
    } catch {
      setRetrying(false)
    }
  }

  return (
    <div className="flex-1 flex items-center justify-center bg-cd-bg">
      <div className="text-center max-w-md">
        <div className="text-5xl mb-4">⚠️</div>
        <h2 className="text-lg font-semibold text-cd-text mb-2">后端服务未启动</h2>
        <p className="text-cd-text-secondary text-sm mb-4">
          桌面客户端正在自动启动后端，请稍候...
          {autoRetries < maxAutoRetries && (
            <span className="block mt-1 text-cd-text-tertiary">
              自动重连中（第 {autoRetries + 1} 次探测）
            </span>
          )}
        </p>
        <button
          onClick={handleRetry}
          disabled={retrying}
          className="bg-cd-green text-white px-4 py-2 rounded-lg text-sm hover:opacity-90 disabled:opacity-50"
        >
          {retrying ? '正在重连...' : '手动重连'}
        </button>
      </div>
    </div>
  )
}

function NotFoundPage() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center">
        <div className="text-6xl font-bold text-cd-text-tertiary mb-4">404</div>
        <h2 className="text-lg font-semibold text-cd-text mb-2">页面不存在</h2>
        <a href="#/" className="text-cd-green hover:underline text-sm">返回首页</a>
      </div>
    </div>
  )
}
