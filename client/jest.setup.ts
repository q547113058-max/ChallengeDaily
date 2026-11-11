/** Jest 测试环境初始化 */
import '@testing-library/jest-dom'

const { BACKEND_PORT } = require('./electron/port-config.cjs')

// ── Mock Electron API（组件测试中依赖 window.electronAPI）──
const mockElectronAPI = {
  showNotification: jest.fn(),
  getBackendPort: jest.fn().mockResolvedValue(BACKEND_PORT),
  getApiToken: jest.fn().mockResolvedValue(''),
}

;(global as any).electronAPI = mockElectronAPI
;(window as any).electronAPI = mockElectronAPI
