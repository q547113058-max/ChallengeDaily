import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'url'
import path from 'path'
import { createRequire } from 'node:module'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
// CSP 单一数据源（与 electron/main.cjs 用同一份，避免双份维护）
const require = createRequire(import.meta.url)
const { buildCSP } = require('./electron/csp.cjs')
const { BACKEND_PORT } = require('./electron/port-config.cjs')
const fs = require('node:fs')

/**
 * 决定 meta CSP 需要放行的远端 origin。
 *
 * 历史坑：之前只在 backend-default.json 为 direct 模式时才注入，
 * 但该文件在源码仓库里是 local 占位，导致手工 `vite build` / `electron .`
 * 产出的 dist 不含云端 origin，file:// 页面请求被 CSP 拦，表现为
 *「后端服务未启动」。现在改为无条件注入：
 *   1) 优先 CD_BACKEND_ORIGIN 环境变量（CI / dev-launch 设置）
 *   2) 其次 backend-default.json 的 direct.url
 *   3) 兜底默认云端地址 —— 保证任何构建方式都能连云端
 */
function readDirectOrigins() {
  const origins = []
  const add = (u) => {
    try {
      if (!u) return
      const o = new URL(u).origin
      if (!origins.includes(o)) origins.push(o)
    } catch (_) {}
  }
  add(process.env.CD_BACKEND_ORIGIN)
  try {
    const p = path.join(__dirname, 'backend-default.json')
    if (fs.existsSync(p)) {
      const cfg = JSON.parse(fs.readFileSync(p, 'utf8').replace(/^\uFEFF/, ''))
      if (cfg && cfg.url) add(cfg.url)
    }
  } catch (_) {}
  add('http://193.112.246.85')   // 兜底：当前部署的云端只读节点
  console.log('[vite][csp] connect-src 追加远端 origin:', origins.join(', '))
  return origins
}

/**
 * Vite 插件：把 CSP 注入 index.html 的 <!--CSP_META--> 占位符
 *
 * 生产环境以 file:// 加载，Electron 的响应头 CSP 对 file 协议不生效，
 * 因此 HTML 里必须有一份 meta CSP —— 但内容不能手写，否则又变成双份维护。
 */
function injectCSP(isServe) {
  return {
    name: 'inject-csp',
    transformIndexHtml(html) {
      const extra = isServe ? [] : readDirectOrigins()
      const meta =
        `<meta http-equiv="Content-Security-Policy" content="${buildCSP({ dev: isServe, extraConnectSrc: extra })}">`
      if (!html.includes('<!--CSP_META-->')) {
        // 宁可构建失败，也不能静默产出一份没有 CSP 的页面
        throw new Error('index.html 缺少 <!--CSP_META--> 占位符，CSP 注入失败')
      }
      return html.replace('<!--CSP_META-->', meta)
    }
  }
}

/**
 * Vite 插件：移除构建产物中的 crossorigin 属性
 * 在 Electron file:// 协议下，crossorigin 属性会导致浏览器将本地文件视为跨域请求，
 * 从而阻断动态 import()（懒加载页面全部报 "Failed to fetch dynamically imported module"）
 */
function removeCrossorigin() {
  return {
    name: 'remove-crossorigin',
    transformIndexHtml(html) {
      return html
        .replace(/ crossorigin=""/g, '')
        .replace(/ crossorigin/g, '')
    }
  }
}

export default defineConfig(({ command }) => ({
  // command: 'serve'（开发）| 'build'（打包）—— 开发期需放宽 script-src 以支持 HMR
  plugins: [react(), removeCrossorigin(), injectCSP(command === 'serve')],
  // 与 electron/port-config.cjs 同源，避免前端 BASE_URL 默认值写死端口
  define: {
    __BACKEND_PORT__: JSON.stringify(BACKEND_PORT),
  },
  base: './',
  root: '.',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1000,
    // 禁用 modulepreload：在 Electron file:// 下预加载链接不可靠，
    // 且 preload 链也带 crossorigin 属性会引发同样问题
    modulePreload: false,
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, 'index.html'),
      },
      output: {
        manualChunks: {
          // React 核心
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          // Markdown 渲染 + recharts 图表
          'vendor-md-chart': ['react-markdown', 'remark-gfm', 'recharts'],
          // UI 图标
          'vendor-lucide': ['lucide-react'],
          // 日期处理
          'vendor-dayjs': ['dayjs'],
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
  },
}))
