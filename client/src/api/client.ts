// ── API 聚合器：重新导出所有模块，保持向后兼容 ──
// 所有现有 `from '../api/client'` 导入无需修改

// ── 核心基础设施 ──
export { request, getBaseUrl, resolveApiUrl, getApiToken, getApiTokenSync, ensureBaseUrl, getBackendState, onBackendStateChange, _triggerDownload } from './core'

// 服务器状态存储（替代 localStorage）：启动引导 + 同步缓存
export { serverStorage, loadServerState, isServerStorageLoaded, onServerStorageReady, initServerStorageLifecycle, getServerStorageError } from './clientState'

// 前端日志采集与上传（错误/告警/埋点 → 服务器）
export { initLogger, flushLogs, logError, logWarn, logInfo, logDebug,
         setLoggerTenant, pendingLogCount } from './logger'
export type { LogLevel, LogEntry } from './logger'

// ── 常量 ──
export { CATEGORY_COLORS, CATEGORIES } from './constants'

// ── 工具函数 ──
export { formatLocalDate, getTodayStr, formatLocalTimestamp, getWeekStart, getWeekDates, getMonthKey } from './utils'

// ── 活动类型 ──
export type { CollectorStatus, TodayStats, VisibleWindow, Activity, ReportContent, AppUsageContent, AppUsage, AppCategoryRule, BackendSettings, ActivityPage, ActivitiesResponse, DailyCredibility } from './types-activity'

// ── 活动 API ──
export { getStatus, getSyncStatus, isReadOnlySnapshot, getTenantInfo, tenantLogin, tenantLogout, isTenantLoginRequired, getTodayStats, getDateStats, getActivities, getAppUsage, captureNow, healthCheck, startupHealthCheck, getSettings, updateSettings, pauseCollector, resumeCollector, getReportByDate, testAiConnection, downloadExportActivities, downloadExportAppUsage, downloadExportReports, downloadExportActivitiesDetail, updateActivity, deleteActivity, undoDeleteActivity, createActivity, searchActivities, getBackupInfo, restoreBackup, getNotifications, markNotificationsRead, getUnreadNotificationCount, getAppRules, getKnownApps, updateAppRule, deleteAppRule, getAppIconUrl, getDailyCredibility } from './activity'
export type { AppNotification, NotifyType, NotifyCategory, TenantInfo, TenantLoginResult } from './activity'
export { loadTenantSession, saveTenantSession, clearTenantSession } from './tenantSession'
export type { TenantSession } from './tenantSession'

// ── 报告 API ──
export { generateDailyReport, generateWeeklyReport, generateMonthlyReport, getCustomTemplates, saveCustomTemplate, deleteCustomTemplate, getDailyReportContent, getReportChannels, saveReportChannels, testReportChannel, submitReportToChannels, scoreReportQuality, searchReports, getDeepInsights, exportReportAsObsidian } from './report'
export type { CustomTemplate, ReportChannelConfig, ReportQualityDimension, ReportQualityResult, ReportSearchResult, DeepInsights } from './report'

// ── 统计 API ──
export { getHourlyStats, getTrendStats, getRhythmStats, getRecentHeatmap, getCalendarView, getSankeyData } from './stats'
export type { RecentHeatmapDay, CalendarDay, CalendarViewData, SankeyLink } from './stats'

// ── 画像 API ──
export { getProfile, getDistilledProfile, saveProfile, addCorrection, deleteCorrection, getDailyProfile, generateDailyProfile, getWeeklyContext, getDeepInsight, getProfileAnalyses, getProfileAnalysisByType, triggerProfileAnalysis, getExperienceProfile, rebuildExperience } from './profile'
export type { UserProfile, UserCorrection, DailyProfile, ProfileData, DistilledAppItem, DistilledProfile, DeepInsightFramework, DeepInsightFinding, DeepInsightSummary, DeepInsightData, ProfileAnalysisItem, ProfileAnalysesResponse, TriggerAnalysisResult, TriggerAnalysisResponse, ExperienceProfile, ExpProject, ExpEpisode, ExpSkill, ExpCollaborator, ExpHabit } from './profile'

// ── 待办/周计划 API ──
export { getTodos, createTodo, updateTodo, deleteTodo, getMonthPlan, getWeekPlan, getUnassignedTodos, assignTodo, unassignTodo, updateTaskTime, splitTask, updatePlanMeta, getWeekPlanStats, getMonthPlanStats, getTodayTodos, addTodoProgress } from './todo'
export type { Todo, TaskLevel, TodoV2, MonthTask, MonthPlanData, WeekPlanData, WeekPlanStats, MonthPlanStats } from './todo'


// ── 集成功能 ──
export { getWebhooks, addWebhook, deleteWebhook, testWebhook, toggleWebhook, triggerAutoReport, getAutoReportConfig, updateAutoReportConfig, importTogglCsv, importRescueTimeCsv, wipeAllData, downloadBackup, getHealthCoverage, getHealthSystemEvents, getSamplingDeviation, getQuote, getGoals, createGoal, updateGoal, deleteGoal, getMoodHeatmap, getGoalProgress, getGoalSummary, previewImport, executeImport, getHabits, createHabit, logHabit, deleteHabit, updateHabit, autoCheckHabits, getHabitRecommendations, getHabitStats, getPreferences, updatePreferences, resetPreferences, getAuditLogs, getAuditStats, cleanupAuditLogs, listGitRepositories, addGitRepository, removeGitRepository, getGitCodeReport, getGitWeeklyReport } from './integration'
export type { Webhook, AutoReportConfig, ImportResult, WipeResult, SystemSession, HealthCoverage, HealthSystemEvents, SamplingDeviation, Goal, MoodEntry, ImportPreview, ImportResultV2, Habit, HabitLog, HabitSuggestion, HabitStats, UserPreferences, AuditLog, AuditStats, GitRepository, GitCodeReport } from './integration'
