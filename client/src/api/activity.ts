// ── 活动采集、状态、设置、健康检查 ──
import { request, getApiToken, resolveApiUrl, ensureBaseUrl, _triggerDownload, setApiToken } from './core'
import { saveTenantSession, clearTenantSession } from './tenantSession'
import type { CollectorStatus, TodayStats, Activity, ActivityPage, ActivitiesResponse, AppUsage, AppCategoryRule, BackendSettings, DailyCredibility, ReportContent } from './types-activity'

/** 获取采集器状态 */
export async function getStatus(): Promise<CollectorStatus> {
  const data = await request('/api/status')
  return data as CollectorStatus
}

/**
 * 获取数据同步状态（云端只读节点用）。
 * 返回 last_push：本机 Windows 采集器最后一次推送数据的时间。
 * 后端未部署该接口时返回 null，调用方需容错。
 */
export async function getSyncStatus(): Promise<{ last_push: string | null; last_push_ts?: string } | null> {
  try {
    const data = await request('/api/sync/status', {}, 8000)
    return data as { last_push: string | null; last_push_ts?: string }
  } catch {
    return null
  }
}

/** 是否为「云端只读快照」模式（无本地采集器，不能开始/暂停记录） */
export function isReadOnlySnapshot(status: CollectorStatus | null): boolean {
  return status?.mode === 'synced-snapshot' || status?.mode === 'server-only'
}

/** 当前租户信息（多租户云端；旧版服务端无此接口时返回 null） */
export interface TenantInfo {
  role: 'tenant' | 'admin' | string
  tenant_id?: string
  name?: string
  enabled?: boolean
  created_at?: string
  token_hint?: string
}
export async function getTenantInfo(): Promise<TenantInfo | null> {
  try {
    const data = await request('/api/tenant/me', {}, 8000)
    return data as TenantInfo
  } catch {
    return null
  }
}

/** 租户登录结果 */
export interface TenantLoginResult {
  ok: boolean
  error?: string
  tenant_id?: string
  name?: string
}

/**
 * 租户登录：租户 ID + 密码。
 * 登录接口本身不需要 token，用裸 fetch 避免触发后端连接状态机。
 * 成功后把 token 注入请求层并持久化到本地会话。
 */
export async function tenantLogin(tenantId: string, password: string): Promise<TenantLoginResult> {
  try {
    await ensureBaseUrl()
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 10000)
    let res: Response
    try {
      res = await fetch(resolveApiUrl('/api/auth/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant_id: tenantId.trim(), password }),
        signal: controller.signal,
      })
    } finally {
      clearTimeout(timer)
    }
    const data = await res.json().catch(() => ({}))
    if (!res.ok || !data.token) {
      return { ok: false, error: data.error || '登录失败，请检查租户 ID 与密码' }
    }
    // 注入 token + 持久化登录态
    setApiToken(data.token)
    saveTenantSession({ tenant_id: data.tenant_id, token: data.token, loginAt: new Date().toISOString() })
    return { ok: true, tenant_id: data.tenant_id }
  } catch (e: any) {
    return { ok: false, error: e?.message || '无法连接服务器，请稍后重试' }
  }
}

/** 退出租户登录 */
export function tenantLogout(): void {
  clearTenantSession()
  setApiToken('')
}

/**
 * 探测服务端是否要求租户登录。
 * 用裸 fetch（带当前 session token，若有）：
 *  - 服务端无 /api/tenant/me（旧版单租户）→ false
 *  - 已登录（role=tenant/admin）→ false
 *  - 未登录（401）→ true
 */
export async function isTenantLoginRequired(): Promise<boolean> {
  try {
    await ensureBaseUrl()
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 8000)
    let res: Response
    try {
      const token = await getApiToken()
      res = await fetch(resolveApiUrl('/api/tenant/me'), {
        headers: token ? { 'X-API-Token': token } : {},
        signal: controller.signal,
      })
    } finally {
      clearTimeout(timer)
    }
    if (res.status === 404) return false   // 旧服务端无此接口
    if (res.ok) {
      const j = await res.json().catch(() => ({}))
      // admin 或已登录租户都算通过
      return !(j.role === 'tenant' || j.role === 'admin')
    }
    if (res.status === 401) return true     // 需要登录
    return false
  } catch {
    return false   // 网络异常不拦截，交给健康检查处理
  }
}

/** 获取今日统计 */
export async function getTodayStats(): Promise<TodayStats> {
  const data = await request('/api/stats/today')
  return data as TodayStats
}

/** 获取指定日期统计 */
export async function getDateStats(date: string): Promise<TodayStats> {
  const data = await request(`/api/stats/date/${date}`)
  return data as TodayStats
}

/** 获取活动列表（支持分页） */
export async function getActivities(date?: string, page?: number, perPage?: number): Promise<ActivityPage> {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  if (page) params.set('page', String(page))
  if (perPage) params.set('per_page', String(perPage))
  const qs = params.toString()
  const data = await request(`/api/activities${qs ? '?' + qs : ''}`) as ActivitiesResponse
  // 兼容旧版后端（无 pagination 字段）
  if (!data.pagination) {
    return {
      activities: data.activities || [],
      pagination: { page: 1, per_page: data.activities?.length || 50, total: data.activities?.length || 0, total_pages: 1, has_more: false }
    }
  }
  return data as ActivityPage
}

/** 获取应用使用分布 */
export async function getAppUsage(date?: string): Promise<AppUsage[]> {
  const params = date ? `?date=${date}` : ''
  const data = await request(`/api/app-usage${params}`) as { apps: AppUsage[] }
  return data.apps || []
}

/** 手动截图 */
export async function captureNow(): Promise<{ ok: boolean }> {
  const data = await request('/api/capture', { method: 'POST' })
  return data as { ok: boolean }
}

/** 健康检查（轻量模式：跳过磁盘/DB/AI检查，仅确认进程存活） */
export async function healthCheck(): Promise<{ status: string }> {
  const data = await request('/api/health?quick=1', {}, 5000)
  return data as { status: string }
}

/** 启动阶段健康检查（绕过 request 状态机，不影响断连计数）
 *  用于 App.tsx 的初始轮询，避免启动阶段的多次失败被误判为"后端断开"
 */
export async function startupHealthCheck(): Promise<boolean> {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 5000)
    // 使用统一解析器：浏览器 shell 走页面同源 /api 代理（支持远程访问），
    // Electron 走 127.0.0.1:<port> 直连。
    await ensureBaseUrl()
    const res = await fetch(resolveApiUrl('/api/health?quick=1'), {
      signal: controller.signal,
    })
    clearTimeout(timeoutId)
    return res.ok
  } catch {
    return false
  }
}

/** 获取后端设置 */
export async function getSettings(): Promise<BackendSettings> {
  const data = await request('/api/settings') as Partial<BackendSettings>
  // 云端只读节点(server-only)的 /api/settings 是精简占位，缺少多个字段。
  // 在此统一补齐默认值，避免调用方（如 Settings 的 exclude_apps.join）拿到
  // undefined 而崩溃。
  const s = data || {}
  return {
    exclude_apps: Array.isArray(s.exclude_apps) ? s.exclude_apps : [],
    screenshot_interval_sec: typeof s.screenshot_interval_sec === 'number' ? s.screenshot_interval_sec : 60,
    work_start_hour: typeof s.work_start_hour === 'number' ? s.work_start_hour : 9,
    work_end_hour: typeof s.work_end_hour === 'number' ? s.work_end_hour : 18,
    custom_report_instructions: s.custom_report_instructions || '',
    ai_enabled: s.ai_enabled ?? false,
    ai_base_url: s.ai_base_url || 'https://open.bigmodel.cn/api/paas/v4',
    ai_vision_model: s.ai_vision_model || (s as any).ai_model || 'glm-4.1v-thinking-flash',
    ai_text_model: s.ai_text_model || (s as any).ai_model || 'glm-4-flash',
    ...(s as any),  // 保留后端返回的其他字段（如 ai_api_key_set）
  } as BackendSettings
}

/** 更新后端设置 */
export async function updateSettings(settings: Partial<BackendSettings>): Promise<{ status: string; settings?: BackendSettings }> {
  const data = await request('/api/settings', {
    method: 'POST',
    body: JSON.stringify(settings),
  })
  // server-only 节点返回 {status:'ok', mode:'server-only'}，无 settings 字段
  return data as { status: string; settings?: BackendSettings }
}

/** 暂停采集器 */
export async function pauseCollector(): Promise<{ status: string; paused: boolean }> {
  const data = await request('/api/collector/pause', { method: 'POST' })
  return data as { status: string; paused: boolean }
}

/** 恢复采集器 */
export async function resumeCollector(): Promise<{ status: string; paused: boolean }> {
  const data = await request('/api/collector/resume', { method: 'POST' })
  return data as { status: string; paused: boolean }
}

/** 获取指定日期报告 */
export async function getReportByDate(date: string): Promise<ReportContent> {
  const data = await request(`/api/report/date/${date}`)
  return data as ReportContent
}

/** 测试 AI API 连接 */
export async function testAiConnection(apiKey: string, baseUrl: string, model: string): Promise<{ ok: boolean; message: string }> {
  const data = await request('/api/ai/test', {
    method: 'POST',
    body: JSON.stringify({ api_key: apiKey, base_url: baseUrl, model }),
  })
  return data as { ok: boolean; message: string }
}

// ── 导出功能 ──

/** 导出活动记录 CSV（安全下载：使用 header 传 token，不暴露于 URL） */
export async function downloadExportActivities(start: string, end: string): Promise<void> {
  const token = await getApiToken()
  const res = await fetch(resolveApiUrl(`/api/export/activities?start=${start}&end=${end}`), {
    headers: token ? { 'X-API-Token': token } : {},
  })
  if (!res.ok) throw new Error(`导出失败: HTTP ${res.status}`)
  const blob = await res.blob()
  _triggerDownload(blob, `activities_${start}_${end}.csv`)
}

/** 导出应用使用时长 CSV（安全下载） */
export async function downloadExportAppUsage(start: string, end: string): Promise<void> {
  const token = await getApiToken()
  const res = await fetch(resolveApiUrl(`/api/export/app-usage?start=${start}&end=${end}`), {
    headers: token ? { 'X-API-Token': token } : {},
  })
  if (!res.ok) throw new Error(`导出失败: HTTP ${res.status}`)
  const blob = await res.blob()
  _triggerDownload(blob, `app_usage_${start}_${end}.csv`)
}

/** 导出历史报告（CSV / JSON） */
export async function downloadExportReports(start: string, end: string, format: 'csv' | 'json' = 'csv'): Promise<void> {
  const token = await getApiToken()
  const res = await fetch(resolveApiUrl(`/api/exports/reports?format=${format}&start=${start}&end=${end}`), {
    headers: token ? { 'X-API-Token': token } : {},
  })
  if (!res.ok) throw new Error(`导出失败: HTTP ${res.status}`)
  const blob = await res.blob()
  _triggerDownload(blob, `reports_${start}_${end}.${format}`)
}

/** 导出活动明细聚合 CSV（多日期范围） */
export async function downloadExportActivitiesDetail(start: string, end: string): Promise<void> {
  const token = await getApiToken()
  const res = await fetch(resolveApiUrl(`/api/exports/activities-detail?start=${start}&end=${end}`), {
    headers: token ? { 'X-API-Token': token } : {},
  })
  if (!res.ok) throw new Error(`导出失败: HTTP ${res.status}`)
  const blob = await res.blob()
  _triggerDownload(blob, `activities_detail_${start}_${end}.csv`)
}

// ── 活动 CRUD ──

/** 更新活动记录（分类/摘要） */
export async function updateActivity(id: number, data: { category?: string; summary?: string }): Promise<{ status: string; id: number }> {
  const result = await request(`/api/activities/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
  return result as { status: string; id: number }
}

/** 删除活动记录（软删除，支持 undo） */
export async function deleteActivity(id: number): Promise<{ status: string; id: number; deleted: boolean }> {
  const result = await request(`/api/activities/${id}`, { method: 'DELETE' })
  return result as { status: string; id: number; deleted: boolean }
}

/** 撤销删除活动记录 */
export async function undoDeleteActivity(id: number): Promise<{ status: string; id: number; restored: boolean }> {
  const result = await request(`/api/activities/${id}/undo`, { method: 'POST' })
  return result as { status: string; id: number; restored: boolean }
}

/** 手动补录活动记录 */
export async function createActivity(data: {
  timestamp: string
  category: string
  summary?: string
  app_name?: string
  window_title?: string
  duration_min?: number
}): Promise<{ status: string }> {
  const result = await request('/api/activities', {
    method: 'POST',
    body: JSON.stringify(data),
  })
  return result as { status: string }
}

/** 搜索活动记录
 *
 * 二选一：
 * - date：单日检索（默认今天，旧行为）
 * - range.startDate / range.endDate：日期范围检索，优先于 date；只传其一表示单侧不限制
 */
export async function searchActivities(
  q: string,
  date?: string,
  range?: { startDate?: string; endDate?: string },
): Promise<Activity[]> {
  const { formatLocalDate } = await import('./utils')
  const params = new URLSearchParams({ q })
  if (range?.startDate || range?.endDate) {
    if (range.startDate) params.set('startDate', range.startDate)
    if (range.endDate) params.set('endDate', range.endDate)
  } else {
    params.set('date', date || formatLocalDate(new Date()))
  }
  const data = await request(`/api/activities/search?${params.toString()}`) as { activities: Activity[] }
  return data.activities || []
}

// ── 备份/恢复/通知 ──

/** 获取备份信息 */
export async function getBackupInfo(): Promise<{ db_size_mb: number; activities_count: number; reports_count: number }> {
  return request('/api/backup/info') as Promise<{ db_size_mb: number; activities_count: number; reports_count: number }>
}

/** 从备份文件恢复数据 */
export async function restoreBackup(file: File): Promise<{ status: string; restored_files: string[] }> {
  const token = await getApiToken()
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(resolveApiUrl('/api/backup/restore'), {
    method: 'POST',
    headers: token ? { 'X-API-Token': token } : {},
    body: formData,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }))
    throw new Error(data.error || '恢复失败')
  }
  return res.json()
}

/** 通知类型：info | success | warning | error */
export type NotifyType = 'info' | 'success' | 'warning' | 'error'
/** 通知分类：report | collector | ai | disk | sync | todo | system */
export type NotifyCategory = 'report' | 'collector' | 'ai' | 'disk' | 'sync' | 'todo' | 'system'

export interface AppNotification {
  id: number
  title: string
  body: string
  type: NotifyType
  category: NotifyCategory
  created_at: string
  read_at: string | null
}

/**
 * 获取通知列表（**不修改已读状态**）。
 * @param opts.sinceId 只取 id 大于该值的（增量轮询）
 * @param opts.unreadOnly 只要未读
 */
export async function getNotifications(opts: { sinceId?: number; unreadOnly?: boolean; limit?: number } = {}): Promise<{ notifications: AppNotification[]; count: number }> {
  const p = new URLSearchParams()
  if (opts.sinceId) p.set('since_id', String(opts.sinceId))
  if (opts.unreadOnly) p.set('unread_only', '1')
  if (opts.limit) p.set('limit', String(opts.limit))
  const qs = p.toString()
  return request(`/api/notifications${qs ? `?${qs}` : ''}`) as Promise<{ notifications: AppNotification[]; count: number }>
}

/** 标记已读：传 ids 或 all */
export async function markNotificationsRead(opts: { ids?: number[]; all?: boolean }): Promise<{ status: string }> {
  return request('/api/notifications/read', {
    method: 'POST',
    body: JSON.stringify(opts),
  }) as Promise<{ status: string }>
}

/** 未读数量（侧边栏/悬浮球红点用） */
export async function getUnreadNotificationCount(): Promise<{ count: number }> {
  return request('/api/notifications/unread_count') as Promise<{ count: number }>
}

// ── 应用分类规则 ──

/** 获取所有应用分类规则 */
export async function getAppRules(): Promise<{ rules: AppCategoryRule[] }> {
  return request('/api/app-rules') as Promise<{ rules: AppCategoryRule[] }>
}

/** 获取所有已记录应用及其规则 */
export async function getKnownApps(): Promise<{ apps: { app_name: string; rule?: AppCategoryRule }[] }> {
  return request('/api/app-rules/known') as Promise<{ apps: { app_name: string; rule?: AppCategoryRule }[] }>
}

/** 创建或更新应用分类规则 */
export async function updateAppRule(rule: Partial<AppCategoryRule> & { app_name: string }): Promise<{ status: string; rule: AppCategoryRule }> {
  return request('/api/app-rules', {
    method: 'POST',
    body: JSON.stringify(rule),
  }) as Promise<{ status: string; rule: AppCategoryRule }>
}

/** 删除应用分类规则 */
export async function deleteAppRule(appName: string): Promise<{ status: string; deleted: boolean }> {
  return request(`/api/app-rules/${encodeURIComponent(appName)}`, { method: 'DELETE' }) as Promise<{ status: string; deleted: boolean }>
}

/** 获取应用图标 URL（图标不敏感，无需 token） */
export async function getAppIconUrl(appName: string): Promise<string> {
  return resolveApiUrl(`/api/icons/${encodeURIComponent(appName)}`)
}

// ── 日报简要统计 ──

export async function getDailyCredibility(): Promise<DailyCredibility> {
  return await request('/api/credibility/daily-report') as DailyCredibility
}
