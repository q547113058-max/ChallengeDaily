const { contextBridge, ipcRenderer } = require('electron')

// P20-8: 统一 IPC 监听器管理 — 每个注册的 listener 都返回反注册函数
// 防止组件卸载后 ipcRenderer 仍持有回调引用导致内存泄漏与重复触发
function _makeManagedListener(channel) {
  return (cb) => {
    const handler = (_e, data) => cb(data)
    ipcRenderer.on(channel, handler)
    // 返回反注册函数，前端 useEffect cleanup 中调用
    return () => {
      try {
        ipcRenderer.removeListener(channel, handler)
      } catch (_) {
        /* ignore */
      }
    }
  }
}

contextBridge.exposeInMainWorld('electronAPI', {
  // 窗口控制
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
  close: () => ipcRenderer.send('window-close'),
  show: () => ipcRenderer.send('window-show'),


  // 后端端口
  getBackendPort: () => ipcRenderer.invoke('get-backend-port'),

  // direct 模式：渲染层应直连的完整后端地址（空串 = 走本机端口代理）
  getBackendUrl: () => ipcRenderer.invoke('get-backend-url'),

  // API Token（通过 IPC 从主进程读取，兼容 Electron 31 sandbox 模式）
  getApiToken: () => ipcRenderer.invoke('get-api-token'),

  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  onBackendCrash: _makeManagedListener('backend-crash'),

  // 在线更新（electron-updater）：状态订阅 + 只读状态 + 触发操作
  onUpdaterState: _makeManagedListener('updater-state'),
  updaterGetState: () => ipcRenderer.invoke('updater-get-state'),
  updaterCheck: () => ipcRenderer.invoke('updater-check'),
  updaterDownload: () => ipcRenderer.invoke('updater-download'),
  updaterQuitAndInstall: () => ipcRenderer.invoke('updater-quit-and-install'),

  // 后端连接配置（local / remote）：读回不含 token 明文；写入需重启生效
  backendConfigGet: () => ipcRenderer.invoke('backend-config-get'),
  backendConfigSet: (cfg) => ipcRenderer.invoke('backend-config-set', cfg),

  // 监听来自主进程的消息
  onCollectorAction: _makeManagedListener('collector-action'),
  onGenerateReport: _makeManagedListener('generate-report'),

  // 桌面通知
  showNotification: ({ title, body }) => ipcRenderer.send('show-notification', { title, body }),

  // Windows 系统定位（主进程调用 PowerShell）
  getWindowsLocation: () => ipcRenderer.invoke('get-windows-location'),

  // 主进程导航指令（全局快捷键→跳转页面）
  onNavigateTo: _makeManagedListener('navigate-to'),

  // 开机自启动
  getAutoStart: () => ipcRenderer.invoke('get-auto-start'),
  setAutoStart: (enabled) => ipcRenderer.invoke('set-auto-start', enabled),

  // Windows Hello 生物识别（应用级隐私锁）
  // 返回 { success: boolean, error?: string }；不可用时返回 success:false
  windowsHello: (reason) => ipcRenderer.invoke('windows-hello', reason),
})
