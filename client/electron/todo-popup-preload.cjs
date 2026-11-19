// 桌面审批弹窗专用最小 preload：只暴露 3 个 API，不污染主窗口 electronAPI。
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('todoPopup', {
  decide: (id, action) => ipcRenderer.send('todo-popup:decide', { id, action }),
  dismiss: () => ipcRenderer.send('todo-popup:dismiss'),
  ready: () => ipcRenderer.send('todo-popup:ready'),
  onData: (cb) => {
    const h = (_e, data) => cb(data)
    ipcRenderer.on('todo-popup:data', h)
    return () => ipcRenderer.removeListener('todo-popup:data', h)
  },
})
