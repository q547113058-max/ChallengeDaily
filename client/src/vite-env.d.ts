/// <reference types="vite/client" />

interface Window {
  electronAPI?: {
    minimize: () => void
    maximize: () => void
    close: () => void
    show: () => void
    getBackendPort: () => Promise<number>
    getApiToken: () => Promise<string>
    getAppVersion: () => Promise<string>
    onBackendCrash: (cb: (data: { title: string; body: string; type: string }) => void) => void
    onCollectorAction: (cb: (data: string) => void) => void
    onGenerateReport: (cb: (data: string) => void) => void
    showNotification: (opts: { title: string; body: string }) => void
    getWindowsLocation: () => Promise<{ lat: number; lon: number; status?: string } | null>
    pomodoroWidgetUpdate: (data: { phase: string; remaining: number; totalSec: number; task: string; duration: number; completed?: number; total?: number; index?: number; distractions?: number }) => void
    pomodoroWidgetHide: () => void
    pomodoroWidgetClick: () => void
    onPomodoroTick: (cb: (data: { phase: string; remaining: number; totalSec: number; task: string; duration: number; completed?: number; total?: number; index?: number; distractions?: number }) => void) => void
    sendDistractionAlert: (data: { app: string; count: number }) => void
    onDistractionAlert: (cb: (data: { app: string; count: number }) => void) => void
    onNavigateTo: (cb: (path: string) => void) => void
    onToggleFocusMode?: (cb: () => void) => void
    getAutoStart: () => Promise<boolean>
    setAutoStart: (enabled: boolean) => Promise<boolean>
    windowsHello?: (reason?: string) => Promise<{ success: boolean; error?: string }>
  }
}

declare module 'lunar-javascript'
