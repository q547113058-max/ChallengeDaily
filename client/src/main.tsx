import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { initLogger } from './api/logger'
import './index.css'

// 最先安装全局日志采集：捕获 window.onerror / unhandledrejection / console.error，
// 并批量上传到服务器，方便远程排查 bug（必须在 React 渲染前安装）。
initLogger()

// 顶层 Suspense 边界：App 内部所有 lazy() 页面在异步加载时都有边界接住，
// 避免在没有 startTransition 的同步渲染里挂起而升级为 React error #426
// ("A component suspended while responding to synchronous input")，
// 进而把整棵 UI 替换成错误/空白。
// 不启用 StrictMode：其开发期双重渲染会放大 lazy + 同步状态切换的竞态。
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.Suspense fallback={<div className="flex h-screen items-center justify-center bg-cd-bg text-cd-text-tertiary text-sm">正在加载…</div>}>
    <App />
  </React.Suspense>,
)
