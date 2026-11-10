/**
 * 远程后端反向代理（仅 remote 模式启用）
 *
 * 目的：后端已部署在别处时，客户端机器上不跑 Python。但前端 core.ts 的
 * BASE_URL 与 CSP 都写死 http://127.0.0.1:58888，改动前端会带来回归风险。
 * 因此在本机 127.0.0.1:58888 起一个轻量 HTTP 代理，把 /api/* 转发到远端，
 * 并在服务端注入 X-API-Token —— token 不进入渲染进程。
 *
 * 特性：
 *   - 透传 method / 请求体 / Content-Type / 自定义头（含 SSE 的流式响应，不缓冲）
 *   - 支持 http 与 https 上游
 *   - 健康检查 /api/health 同样转发（isBackendRunning 的心跳因此有效）
 *   - 端口被占用时明确报错，不静默降级
 */

const http = require('http')
const https = require('https')
const { URL } = require('url')

let _server = null
let _cfg = null

function _upstream() {
  return new URL(_cfg.url)
}

function start(cfg, port, log = console.log) {
  if (_server) return Promise.resolve()
  _cfg = cfg
  const upstream = _upstream()
  const client = upstream.protocol === 'https:' ? https : http

  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      // 只代理 /api/*；其余请求返回 404，避免把本机变成开放代理
      if (!req.url || !req.url.startsWith('/api/')) {
        res.writeHead(404, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ error: 'only /api/* is proxied' }))
        return
      }

      const targetPath = `${upstream.pathname.replace(/\/+$/, '')}${req.url}`
      const headers = { ...req.headers }
      delete headers.host
      delete headers['x-api-token'] // 不接受渲染层伪造的 token
      delete headers['content-length'] // 由上游按实际 body 重新计算
      if (_cfg.token) headers['x-api-token'] = _cfg.token

      const upstreamReq = client.request(
        {
          protocol: upstream.protocol,
          hostname: upstream.hostname,
          port: upstream.port || (upstream.protocol === 'https:' ? 443 : 80),
          path: targetPath,
          method: req.method,
          headers,
          timeout: 60000,
        },
        (upstreamRes) => {
          // 透传状态码与响应头；流式 pipe 保证 SSE / 大响应不被缓冲
          res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers)
          upstreamRes.pipe(res)
        },
      )

      upstreamReq.on('timeout', () => {
        upstreamReq.destroy(new Error('upstream timeout'))
      })
      upstreamReq.on('error', (err) => {
        log('[RemoteProxy] upstream error:', err?.message || err)
        if (!res.headersSent) {
          res.writeHead(502, { 'Content-Type': 'application/json' })
        }
        if (!res.writableEnded) {
          res.end(JSON.stringify({ error: 'backend unreachable', detail: String(err?.message || err) }))
        }
      })
      req.pipe(upstreamReq)
    })

    server.on('error', (err) => {
      log('[RemoteProxy] server error:', err?.message || err)
      if (!_server) reject(err)
    })
    server.listen(port, '127.0.0.1', () => {
      _server = server
      log(`[RemoteProxy] listening on 127.0.0.1:${port} -> ${cfg.url}`)
      resolve()
    })
  })
}

function stop() {
  if (!_server) return
  try {
    _server.close()
  } catch (_) {}
  _server = null
}

module.exports = { start, stop, isRunning: () => Boolean(_server) }
