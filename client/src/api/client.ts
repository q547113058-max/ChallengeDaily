// ── API 聚合器：重新导出所有模块，保持向后兼容 ──
// 所有现有 `from '../api/client'` 导入无需修改

// ── 核心基础设施 ──
export { request, getBaseUrl, getApiToken, ensureBaseUrl, getBackendState, onBackendStateChange, _triggerDownload } from './core'

// ── 常量 ──
export { CATEGORY_COLORS, CATEGORIES, POMODORO_SIZES, LONG_BREAK_INTERVAL } from './constants'
export type { PomodoroSizeConfig } from './constants'

// ── 工具函数 ──
export { formatLocalDate, getTodayStr, formatLocalTimestamp, getWeekStart, getWeekDates, getMonthKey } from './utils'

// ── 活动类型 ──
export type { CollectorStatus, TodayStats, VisibleWindow, Activity, ReportContent, AppUsageContent, AppUsage, AppCategoryRule, BackendSettings, ActivityPage, ActivitiesResponse, PomodoroSummary, DailyCredibility } from './types-activity'

// ── 活动 API ──
export { getStatus, getTodayStats, getDateStats, getActivities, getAppUsage, captureNow, healthCheck, startupHealthCheck, getSettings, updateSettings, pauseCollector, resumeCollector, getReportByDate, testAiConnection, downloadExportActivities, downloadExportAppUsage, downloadExportReports, downloadExportActivitiesDetail, updateActivity, deleteActivity, undoDeleteActivity, createActivity, searchActivities, getBackupInfo, restoreBackup, getNotifications, getAppRules, getKnownApps, updateAppRule, deleteAppRule, getAppIconUrl, getPomodoroSummary, getDailyCredibility } from './activity'

// ── 报告 API ──
export { generateDailyReport, generateWeeklyReport, generateMonthlyReport, getCustomTemplates, saveCustomTemplate, deleteCustomTemplate, getDailyReportContent, getReportChannels, saveReportChannels, testReportChannel, submitReportToChannels, scoreReportQuality, searchReports, getDeepInsights, exportReportAsObsidian } from './report'
export type { CustomTemplate, ReportChannelConfig, ReportQualityDimension, ReportQualityResult, ReportSearchResult, DeepInsights } from './report'

// ── 番茄钟 API ──
export { startPomodoro, stopPomodoro, getPomodoroSessions, getPomodoroStats, getPomodoroQuality, checkPomodoroDistraction, getSmartDuration, getPomodoroReport } from './pomodoro'
export type { PomodoroSession, PomodoroQuality, SmartDurationResult, PomodoroReport } from './pomodoro'

// ── 统计 API ──
export { getHourlyStats, getTrendStats, getRhythmStats, getRecentHeatmap, getDistractionHeatmap, getCalendarView, getSankeyData } from './stats'
export type { RecentHeatmapDay, DistractionHeatmapEntry, CalendarDay, CalendarViewData, SankeyLink } from './stats'

// ── 画像 API ──
export { getProfile, getDistilledProfile, saveProfile, addCorrection, deleteCorrection, getDailyProfile, generateDailyProfile, getWeeklyContext, getDeepInsight, getProfileAnalyses, getProfileAnalysisByType, triggerProfileAnalysis } from './profile'
export type { UserProfile, UserCorrection, DailyProfile, ProfileData, DistilledAppItem, DistilledProfile, DeepInsightFramework, DeepInsightFinding, DeepInsightSummary, DeepInsightData, ProfileAnalysisItem, ProfileAnalysesResponse, TriggerAnalysisResult, TriggerAnalysisResponse } from './profile'

// ── 待办/周计划 API ──
export { getTodos, createTodo, updateTodo, deleteTodo, getMonthPlan, getWeekPlan, getUnassignedTodos, assignTodo, unassignTodo, updateTaskTime, splitTask, updatePlanMeta, getWeekPlanStats, getMonthPlanStats, getTodayTodos, addTodoProgress } from './todo'
export type { Todo, TaskLevel, TodoV2, MonthTask, MonthPlanData, WeekPlanData, WeekPlanStats, MonthPlanStats } from './todo'


// ── 集成功能 ──
export { getWebhooks, addWebhook, deleteWebhook, testWebhook, toggleWebhook, triggerAutoReport, getAutoReportConfig, updateAutoReportConfig, importTogglCsv, importRescueTimeCsv, wipeAllData, getSeason, getSeasonHistory, downloadBackup, getHealthCoverage, getHealthSystemEvents, getSamplingDeviation, getQuote, getMorningInsights, getCountdowns, createCountdown, deleteCountdown, getGoals, createGoal, updateGoal, deleteGoal, getMoodHeatmap, getGoalProgress, getGoalSummary, previewImport, executeImport, getHabits, createHabit, logHabit, deleteHabit, updateHabit, autoCheckHabits, getHabitRecommendations, getHabitStats, getDailyCard, getDailyCardText, getPreferences, updatePreferences, resetPreferences, getAuditLogs, getAuditStats, cleanupAuditLogs, listCalendarSubscriptions, addCalendarSubscription, updateCalendarSubscription, removeCalendarSubscription, refreshCalendarAll, getCalendarTodayEvents, getCalendarUpcomingEvents, getCalendarCurrentMeeting, listGitRepositories, addGitRepository, removeGitRepository, getGitCodeReport, getGitWeeklyReport, getLocalModelStatus, getLocalModelConfig, updateLocalModelConfig, listLocalModels, testLocalModel, searchMemory, getMemoryStatus, getMemoryList, deleteMemory, triggerIndexing, triggerExtraction } from './integration'
export type { Webhook, AutoReportConfig, ImportResult, WipeResult, SeasonAchievement, SeasonData, SeasonHistoryItem, SystemSession, HealthCoverage, HealthSystemEvents, SamplingDeviation, MorningInsight, Countdown, Goal, MoodEntry, ImportPreview, ImportResultV2, Habit, HabitLog, HabitSuggestion, HabitStats, DailyCardData, UserPreferences, AuditLog, AuditStats, CalendarSubscription, CalendarEvent, GitRepository, GitCodeReport, LocalModelConfig, LocalModelStatus, MemoryItem, MemorySearchResult, MemoryStatus } from './integration'
