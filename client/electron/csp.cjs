/**
 * Content-Security-Policy 单一数据源（Single Source of Truth）
 *
 * 为什么需要这个文件：
 *   生产环境通过 loadFile() 以 file:// 加载页面，Electron 的 onHeadersReceived
 *   对 file 协议不生效，此时只有 HTML 里的 <meta> CSP 起作用；
 *   开发环境通过 loadURL('http://localhost:5173') 加载，响应头 CSP 与 meta CSP
 *   同时生效（浏览器取交集）。
 *   两条路径都必须存在，因此过去在 index.html 和 main.cjs 各写了一份，
 *   改一处漏一处就会产生"本地能跑、打包后请求被拦"的怪问题。
 *
 * 现在两处都由本文件生成：
 *   - main.cjs            require('./csp.cjs') 生成响应头 CSP
 *   - vite.config.js      构建/开发期注入 <meta> CSP（见 injectCSP 插件）
 * 修改白名单只需改这里。
 */

const { BACKEND_PORT } = require('./port-config.cjs')

/** connect-src 白名单：本地后端 + 第三方 API */
const CONNECT_SRC = [
  `http://127.0.0.1:${BACKEND_PORT}`,
  `http://localhost:${BACKEND_PORT}`,
  'http://localhost:5173',
  'https://wttr.in',
  'https://api.open-meteo.com',
  'https://geocoding-api.open-meteo.com',
  'https://api.bigdatacloud.net',
  'https://qifu-api.baidubce.com',
  'https://pv.sohu.com',
  'https://int.dpool.sina.com.cn',
  'https://nominatim.openstreetmap.org',
  'https://ipapi.co',
  'https://ipinfo.io',
  'https://ip-api.com',
  'https://apis.map.qq.com',
  'https://open.bigmodel.cn',
]

/**
 * 主窗口 / 页面 CSP
 * @param {{ dev?: boolean }} opts dev=true 时放宽 script-src（Vite HMR 需要 unsafe-inline）
 */
function buildCSP({ dev = false } = {}) {
  return [
    "default-src 'self'",
    dev ? "script-src 'self' 'unsafe-inline'" : "script-src 'self'",
    // TODO(P0-02): style-src 仍保留 'unsafe-inline'，存在 CSS data exfiltration 风险。
    // 未改用 nonce 的原因：React 内联样式（style={{...}}）会生成 style 属性，
    // CSP3 规定当 style-src 含 nonce 时 'unsafe-inline' 会被忽略，导致所有内联
    // style 属性被拦截、UI 渲染崩溃。要彻底移除需先把内联样式迁到 CSS 类。
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "img-src 'self' data: blob: http: https:",
    "font-src 'self' data: https://fonts.gstatic.com",
    `connect-src 'self' ${CONNECT_SRC.join(' ')}`,
    "media-src 'none'",
    "object-src 'none'",
    "frame-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join('; ') + ';'
}

/**
 * 子窗口（宠物 / 悬浮窗等）基线 CSP
 * 仅作下限保护，避免主窗口已加固而子窗口裸奔
 */
function buildBaseCSP({ dev = false } = {}) {
  return [
    "default-src 'self'",
    dev ? "script-src 'self' 'unsafe-inline'" : "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src 'self' http://127.0.0.1:${BACKEND_PORT} http://localhost:5173 http://localhost:${BACKEND_PORT}`,
    "media-src 'none'",
    "object-src 'none'",
    "frame-src 'none'",
  ].join('; ') + ';'
}

module.exports = { buildCSP, buildBaseCSP, CONNECT_SRC }
