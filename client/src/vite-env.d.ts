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
    onNavigateTo: (cb: (path: string) => void) => void
    getAutoStart: () => Promise<boolean>
    setAutoStart: (enabled: boolean) => Promise<boolean>
    windowsHello?: (reason?: string) => Promise<{ success: boolean; error?: string }>
  }
}

declare module 'lunar-javascript'
