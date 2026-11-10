/// <reference types="vite/client" />

/** 后端连接配置（读回；token 不返回明文） */
interface BackendConfigView {
  mode: 'local' | 'remote'
  url: string
  hasToken: boolean
  envOverride: boolean
  restartRequired: boolean
}

/** 写入后端连接配置 */
interface BackendConfigInput {
  mode: 'local' | 'remote'
  url: string
  token: string
}

/** 与 electron/updater.cjs 的 getState() 结构保持一致 */
interface UpdateState {
  status: 'idle' | 'checking' | 'available' | 'not-available' | 'downloading' | 'downloaded' | 'error'
  supported: boolean
  version: string | null
  currentVersion: string
  releaseNotes: string | null
  releaseDate: string | null
  progress: {
    percent: number
    transferred: number
    total: number
    bytesPerSecond: number
  } | null
  error: string | null
  checkedAt: number | null
}

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
    onUpdaterState: (cb: (state: UpdateState) => void) => () => void
    updaterGetState: () => Promise<UpdateState>
    updaterCheck: () => Promise<UpdateState>
    updaterDownload: () => Promise<UpdateState>
    updaterQuitAndInstall: () => Promise<boolean>
    backendConfigGet: () => Promise<BackendConfigView>
    backendConfigSet: (cfg: BackendConfigInput) => Promise<{ ok: boolean; error?: string; restartRequired?: boolean }>
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
