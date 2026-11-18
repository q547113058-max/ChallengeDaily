/**
 * 自动待办桥接代理（direct 模式专用）
 *
 * 背景：direct 模式下渲染层把 /api/* 全部发到云端只读节点，而云端没有
 * /api/bridge/*（返回 501 server_only_mode）。自动待办看板因此永远拿不到数据、
 * 审批弹窗也永远不会出现。
 *
 * 这里在 127.0.0.1:<BACKEND_PORT>(58889) 起一个极小的反代，只接管
 * /api/bridge/*，映射到线上 todo-sync 服务，并在服务端注入 X-Todo-Token
 * —— 写 token 不进入渲染进程。主 API 仍直连云端，互不影响。
 *
 * 路径映射（与 routes/bridge.py 保持一致）：
 *   GET  /api/bridge/status              -> GET  /api/health        包装成 {enabled,...}
 *   GET  /api/bridge/todos?status=xxx    -> GET  /api/todos?status=xxx
 *   POST /api/bridge/todos/<id>/status   -> POST /api/todos/<id>/status
 *   POST /api/bridge/todos/<id>/approve  -> POST /api/todos/<id>/approve
 *   POST /api/bridge/todos/<id>/reject   -> POST /api/todos/<id>/reject
 *   GET  /api/bridge/events              -> GET  /api/events         SSE 流式透传
 *
 * 另外响应 /api/health 本地心跳：direct 模式的心跳探测 127.0.0.1:58889，
 * 之前一直失败并每 3 分钟打印 "Backend unresponsive, forcing restart..."。
 *
 * 配置（环境变量，均有内置默认值，与 run-challengedaily-web.bat 一致）：
 *   TODO_SYNC_URL     默认 http://193.112.246.85:18766
 *   TODO_SYNC_TOKEN   写 token
 *
 * 也可独立运行：node bridge-proxy.cjs（供不重启 App 时立即验证）。
 */

const http = require('http')
const https = require('https')
const { URL } = require('url')

const DEFAULT_UPSTREAM = 'http://193.112.246.85:18766'
const DEFAULT_TOKEN = '51500b289da5acb9419adc0580c2a4e22e76c34dc057f250'
// 本机采集端地址：AI 连接测试等只有它实现了真实逻辑，云端只读节点是 no-op
const DEFAULT_LOCAL_COLLECTOR = 'http://127.0.0.1:58888'

const HOP_BY_HOP = new Set([
  'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailer', 'transfer-encoding', 'upgrade',
])

// 只放行可信来源：file:// 页面的 Origin 是 "null"，开发态是 localhost:5173，
// direct 模式页面是云端只读节点。不要用 '*' —— 否则任意网站都能读到本机待办。
const ALLOWED_ORIGINS = new Set([
  'null',
  'http://127.0.0.1:58889',
  'http://localhost:58889',
  'http://localhost:5173',
  'http://193.112.246.85',
])

function corsFor(req) {
  const origin = req.headers.origin || ''
  return {
    'Access-Control-Allow-Origin': ALLOWED_ORIGINS.has(origin) ? origin : 'null',
    'Access-Control-Allow-Headers': 'Content-Type, X-API-Token',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
    'Access-Control-Max-Age': '86400',
    Vary: 'Origin',
  }
}

const MAX_BODY = 1024 * 1024

let _server = null

function _config() {
  return {
    upstream: (process.env.TODO_SYNC_URL || DEFAULT_UPSTREAM).trim().replace(/\/+$/, ''),
    local: (process.env.CD_LOCAL_COLLECTOR_URL || DEFAULT_LOCAL_COLLECTOR).trim().replace(/\/+$/, ''),
    token: (process.env.TODO_SYNC_TOKEN || DEFAULT_TOKEN).trim(),
  }
}

/** 把 /api/bridge/* 映射成 todo-sync 的真实路径。返回 null 表示不接管。 */
function _mapPath(rawUrl) {
  const q = rawUrl.indexOf('?')
  const path = q < 0 ? rawUrl : rawUrl.slice(0, q)
  const query = q < 0 ? '' : rawUrl.slice(q)

  if (path === '/api/bridge/status') return { path: '/api/health', wrap: true }
  if (path === '/api/bridge/todos') return { path: '/api/todos' + query }
  if (path === '/api/bridge/events') return { path: '/api/events', sse: true }

  const m = /^\/api\/bridge\/todos\/(\d+)\/(status|approve|reject)$/.exec(path)
  if (m) return { path: `/api/todos/${m[1]}/${m[2]}` }

  // ── 只在 Windows 采集端实现的接口：原样转发到本机 58888 ──
  // 云端只读节点没有 AI 引擎，这些接口返回空壳或 501。
  //   /api/ai/*          AI 连接测试
  //   /api/profile/*     深度画像（个人信息/蒸馏画像/每日画像/心理分析）
  //   /api/deep-insight* 深度洞察引擎
  //   /api/experience/*  经历档案
  if (path === '/api/ai/test' ||
      path.startsWith('/api/ai/') ||
      path === '/api/profile' || path.startsWith('/api/profile/') ||
      path === '/api/deep-insight' || path.startsWith('/api/deep-insight/') ||
      path === '/api/experience' || path.startsWith('/api/experience/')) {
    return { path: path + query, local: true }
  }
  return null
}

function handler(req, res, log) {
  const rawUrl = req.url || ''

  // CORS 预检：file:// 页面的 Origin 是 "null"，本地直接应答，不转发上游
  if (req.method === 'OPTIONS') {
    res.writeHead(204, { ...corsFor(req), 'Content-Length': '0' })
    res.end()
    return
  }

  // Electron 的本地心跳探测（127.0.0.1:58889/api/health）
  if (rawUrl.split('?')[0] === '/api/health') {
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', ...corsFor(req) })
    res.end(JSON.stringify({ status: 'ok', mode: 'bridge-proxy' }))
    return
  }

  const mapped = _mapPath(rawUrl)
  if (!mapped) {
    res.writeHead(404, { 'Content-Type': 'application/json; charset=utf-8', ...corsFor(req) })
    res.end(JSON.stringify({ ok: false, error: 'only /api/bridge/* is proxied' }))
    return
  }

  const cfg = _config()
  let upstream
  try {
    upstream = new URL(mapped.local ? cfg.local : cfg.upstream)
  } catch (_) {
    res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8', ...corsFor(req) })
    res.end(JSON.stringify({ ok: false, error: 'bad upstream URL' }))
    return
  }
  const client = upstream.protocol === 'https:' ? https : http

  // bridge 请求注入 todo-sync 写 token；本机采集端请求原样透传渲染层的 X-API-Token
  const headers = {
    'Content-Type': 'application/json; charset=utf-8',
    Accept: mapped.sse ? 'text/event-stream' : 'application/json',
  }
  if (mapped.local) {
    const inTok = req.headers['x-api-token']
    if (inTok) headers['X-API-Token'] = inTok
  } else {
    headers['X-Todo-Token'] = cfg.token
  }

  const chunks = []
  let size = 0
  let aborted = false
  req.on('data', (c) => {
    size += c.length
    if (size > MAX_BODY) {
      aborted = true
      res.writeHead(413, { 'Content-Type': 'application/json', ...corsFor(req) })
      res.end(JSON.stringify({ ok: false, error: 'body too large' }))
      req.destroy()
      return
    }
    chunks.push(c)
  })
  req.on('end', () => {
    if (aborted || res.writableEnded) return
    const body = Buffer.concat(chunks)
    if (body.length) headers['Content-Length'] = String(body.length)

    const upReq = client.request(
      {
        protocol: upstream.protocol,
        hostname: upstream.hostname,
        port: upstream.port || (upstream.protocol === 'https:' ? 443 : 80),
        path: mapped.path,
        method: req.method,
        headers,
        // SSE 不设超时；普通请求 15s
        timeout: mapped.sse ? 0 : 15000,
      },
      (upRes) => {
        if (res.writableEnded) { upRes.resume(); return }

        const outHeaders = { ...corsFor(req) }
        for (const [k, v] of Object.entries(upRes.headers)) {
          if (!HOP_BY_HOP.has(k.toLowerCase())) outHeaders[k] = v
        }

        // SSE：管道透传，保持长连接；客户端断开时关掉上游
        if (mapped.sse) {
          res.writeHead(upRes.statusCode || 502, outHeaders)
          upRes.pipe(res)
          res.on('close', () => upRes.destroy())
          return
        }

        // 非 SSE：收齐响应体（/api/bridge/status 需要包装）
        const parts = []
        upRes.on('data', (c) => parts.push(c))
        upRes.on('end', () => {
          if (res.writableEnded) return
          const text = Buffer.concat(parts).toString('utf8')
          const code = upRes.statusCode || 502
          let payload = text
          if (mapped.wrap) {
            let inner = {}
            try { inner = JSON.parse(text) } catch (_) { /* 上游非 JSON，原样放进 upstream */ }
            payload = JSON.stringify({
              ok: code === 200,
              enabled: code === 200,
              upstream: inner,
            })
          }
          res.writeHead(code, {
            'Content-Type': 'application/json; charset=utf-8',
            ...corsFor(req),
            'Content-Length': String(Buffer.byteLength(payload)),
          })
          res.end(payload)
        })
      },
    )

    upReq.on('timeout', () => upReq.destroy(new Error('upstream timeout')))
    upReq.on('error', (err) => {
      log('[BridgeProxy] upstream error:', err?.message || err)
      if (!res.headersSent) {
        res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8', ...corsFor(req) })
      }
      if (!res.writableEnded) {
        res.end(JSON.stringify({ ok: false, error: 'todo-sync unreachable', detail: String(err?.message || err) }))
      }
    })
    if (body.length) upReq.write(body)
    upReq.end()
  })
  req.on('error', () => { if (!res.writableEnded) res.end() })
}

function start(_cfg, port, log = console.log) {
  if (_server) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => handler(req, res, log))
    server.on('error', (err) => {
      // 端口已被占用：通常是独立跑的同一代理，视为已就绪，不阻断启动
      if (err.code === 'EADDRINUSE') {
        log(`[BridgeProxy] port ${port} already in use, assume running`)
        resolve()
        return
      }
      log('[BridgeProxy] server error:', err?.message || err)
      if (!_server) reject(err)
    })
    server.listen(port, '127.0.0.1', () => {
      _server = server
      const cfg = _config()
      log(`[BridgeProxy] listening on 127.0.0.1:${port} -> ${cfg.upstream}`)
      resolve()
    })
  })
}

function stop() {
  if (!_server) return
  try { _server.close() } catch (_) {}
  _server = null
}

module.exports = { start, stop, isRunning: () => Boolean(_server), _mapPath }

if (require.main === module) {
  const port = Number(process.env.CD_BRIDGE_PORT || 58889)
  start({}, port, (...a) => console.log(...a))
    .then(() => console.log('[BridgeProxy] ready'))
    .catch((e) => { console.error('[BridgeProxy] failed:', e); process.exit(1) })
}
