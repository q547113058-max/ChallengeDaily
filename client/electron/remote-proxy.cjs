/**
 * 远程后端反向代理（仅 remote 模式启用）
 *
 * 目的：后端已部署在别处时，客户端机器上不跑 Python。但前端 core.ts 的
 * BASE_URL 与 CSP 都写死 http://127.0.0.1:58888，改动前端会带来回归风险。
 * 因此在本机 127.0.0.1:58888 起一个轻量 HTTP 代理，把 /api/* 转发到远端，
 * 并在服务端注入 X-API-Token —— token 不进入渲染进程。
 *
 * 特性：
 *   - 透传 method / 请求体 / 实体头（SSE 等流式响应用 pipe 转发，但会剔除逐跳头）
 *   - 支持 http 与 https 上游
 *   - 健康检查 /api/health 同样转发
 *   - CORS 预检本地直接应答，不转发（避免上游 204 + Connection: close 破坏连接）
 *   - 端口被占用时明确报错，不静默降级
 *
 * 实现要点（踩过的坑）：
 *   1) 请求体必须「读完整再发」，不能用 req.pipe(upstreamReq) 同时保留
 *      content-length —— Node 会在 pipe 数据到达前就按长度结束请求，上游收到
 *      不一致的 body 返回畸形 400（表现为 PATCH flush 一直失败、GET 正常）。
 *   2) 上游响应头必须剔除逐跳头（transfer-encoding / connection 等），否则
 *      下游 Node 二次编码导致 HTTP 报文损坏。
 *   3) 不接受渲染层伪造的 x-api-token，统一用配置里的 token 覆盖。
 */

const http = require('http')
const https = require('https')
const { URL } = require('url')

let _server = null
let _cfg = null

// 逐跳头（hop-by-hop）不能透传给下游，否则 Node 会重复编码导致响应损坏
const HOP_BY_HOP = new Set([
  'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailer', 'transfer-encoding', 'upgrade',
])

const MAX_BODY = 8 * 1024 * 1024 // 8MB，与后端 MAX_BODY 同量级

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

      // CORS 预检本地直接应答：转发到上游既无必要，上游的 204 + Connection: close
      // 还会让下游连接复用出问题。
      if (req.method === 'OPTIONS') {
        res.writeHead(204, {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Headers': 'Content-Type, X-API-Token',
          'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
          'Access-Control-Max-Age': '86400',
          'Content-Length': '0',
        })
        res.end()
        return
      }

      const targetPath = `${upstream.pathname.replace(/\/+$/, '')}${req.url}`
      const headers = { ...req.headers }
      delete headers.host
      delete headers['x-api-token'] // 不接受渲染层伪造的 token
      delete headers['content-length']
      delete headers['transfer-encoding']
      for (const k of HOP_BY_HOP) delete headers[k]
      if (_cfg.token) headers['x-api-token'] = _cfg.token

      // 收集完整请求体后再发，避免 pipe 与 content-length 的竞态
      const chunks = []
      let size = 0
      let aborted = false
      req.on('data', (c) => {
        size += c.length
        if (size > MAX_BODY) {
          aborted = true
          res.writeHead(413, { 'Content-Type': 'application/json' })
          res.end(JSON.stringify({ error: 'request body too large' }))
          req.destroy()
          return
        }
        chunks.push(c)
      })
      req.on('end', () => {
        if (aborted || res.writableEnded) return
        const body = Buffer.concat(chunks)
        if (body.length) headers['content-length'] = String(body.length)
        else delete headers['content-length']

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
            if (res.writableEnded) { upstreamRes.resume(); return }
            const outHeaders = {}
            for (const [k, v] of Object.entries(upstreamRes.headers)) {
              if (!HOP_BY_HOP.has(k.toLowerCase())) outHeaders[k] = v
            }
            res.writeHead(upstreamRes.statusCode || 502, outHeaders)
            upstreamRes.pipe(res)
          },
        )

        upstreamReq.on('timeout', () => upstreamReq.destroy(new Error('upstream timeout')))
        upstreamReq.on('error', (err) => {
          log('[RemoteProxy] upstream error:', err?.message || err)
          if (!res.headersSent) res.writeHead(502, { 'Content-Type': 'application/json' })
          if (!res.writableEnded) {
            res.end(JSON.stringify({ error: 'backend unreachable', detail: String(err?.message || err) }))
          }
        })
        if (body.length) upstreamReq.write(body)
        upstreamReq.end()
      })
      req.on('error', (err) => {
        log('[RemoteProxy] request error:', err?.message || err)
        if (!res.writableEnded) res.end()
      })
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
  try { _server.close() } catch (_) {}
  _server = null
}

module.exports = { start, stop, isRunning: () => Boolean(_server) }
