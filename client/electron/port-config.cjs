/**
 * 客户端本地后端端口（单一数据源）
 *
 * 历史值为 58888，与「源码方式运行的 Python 后端」默认端口相同。
 * 当开发机上同时跑源码后端时，打包版客户端的本地反向代理会因端口占用
 * 起不来（EADDRINUSE）。因此客户端统一改用 58889，两者可并存。
 *
 * 引用方：
 *   - electron/main.cjs        BACKEND_PORT / 健康检查 / 代理监听
 *   - electron/csp.cjs         connect-src 白名单
 *   - src/api/core.ts          前端 BASE_URL 默认值（经 getBackendPort IPC 覆盖）
 *   - vite.config.js 注入的 meta CSP（由 csp.cjs 生成）
 */
const BACKEND_PORT = 58889

module.exports = { BACKEND_PORT }
