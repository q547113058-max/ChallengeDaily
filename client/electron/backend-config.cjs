/**
 * ChallengeDaily 后端连接配置
 *
 * 两种模式：
 *   - local  （默认，行为与历史版本完全一致）：Electron 启动本地 Python 后端进程。
 *   - remote ：后端已部署在另一台机器/服务器上，本机只装客户端。
 *             Electron 不起 Python，改起一个 127.0.0.1:58888 的本地反向代理，
 *             把 /api/* 转发到远端并注入 X-API-Token。前端 core.ts 无需改动。
 *
 * 配置优先级（高 → 低）：
 *   1. 环境变量 CHALLENGE_DAILY_BACKEND_MODE / _URL / _TOKEN（便于批量部署 / 免 UI 配置）
 *   2. userData/backend-config.json
 *   3. 默认值 { mode: 'local' }
 *
 * 安全：token 只存在主进程侧，绝不通过 IPC/渲染层暴露。
 */

const fs = require('fs')
const path = require('path')
const { app } = require('electron')

const CONFIG_FILE = () => path.join(app.getPath('userData'), 'backend-config.json')

const DEFAULTS = { mode: 'local', url: '', token: '' }

function _sanitize(raw) {
  const mode = raw?.mode === 'remote' ? 'remote' : 'local'
  let url = typeof raw?.url === 'string' ? raw.url.trim().replace(/\/+$/, '') : ''
  // 只允许 http/https，且必须是可解析的绝对地址
  if (url) {
    try {
      const u = new URL(url)
      if (u.protocol !== 'http:' && u.protocol !== 'https:') url = ''
      else url = `${u.protocol}//${u.host}${u.pathname.replace(/\/+$/, '')}`
    } catch (_) {
      url = ''
    }
  }
  const token = typeof raw?.token === 'string' ? raw.token.trim() : ''
  return { mode, url, token }
}

/** 读取配置（含环境变量覆盖）。 */
function loadConfig() {
  let file = {}
  try {
    if (fs.existsSync(CONFIG_FILE())) {
      file = JSON.parse(fs.readFileSync(CONFIG_FILE(), 'utf-8'))
    }
  } catch (e) {
    console.error('[BackendConfig] read failed, using defaults:', e?.message || e)
  }

  const merged = {
    mode: process.env.CHALLENGE_DAILY_BACKEND_MODE || file.mode || DEFAULTS.mode,
    url: process.env.CHALLENGE_DAILY_BACKEND_URL || file.url || DEFAULTS.url,
    token: process.env.CHALLENGE_DAILY_BACKEND_TOKEN || file.token || DEFAULTS.token,
  }
  const cfg = _sanitize(merged)
  // remote 但没给有效 URL 时回退 local，避免起一个必然不可用的代理
  if (cfg.mode === 'remote' && !cfg.url) {
    console.warn('[BackendConfig] remote mode requested but no valid URL, falling back to local')
    cfg.mode = 'local'
  }
  return cfg
}

/** 保存配置到 userData（环境变量不会被写回）。 */
function saveConfig(raw) {
  const cfg = _sanitize(raw)
  try {
    const dir = app.getPath('userData')
    fs.mkdirSync(dir, { recursive: true })
    fs.writeFileSync(CONFIG_FILE(), JSON.stringify(cfg, null, 2), 'utf-8')
    return cfg
  } catch (e) {
    console.error('[BackendConfig] save failed:', e?.message || e)
    return null
  }
}

/** 供 CSP 使用：remote 模式下需要放行的 origin（如 http://10.0.0.5:58888）。 */
function remoteOrigin() {
  const cfg = loadConfig()
  if (cfg.mode !== 'remote' || !cfg.url) return null
  try {
    return new URL(cfg.url).origin
  } catch (_) {
    return null
  }
}

module.exports = { loadConfig, saveConfig, remoteOrigin, DEFAULTS }
