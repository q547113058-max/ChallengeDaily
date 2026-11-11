/**
 * ChallengeDaily 后端连接配置
 *
 * 两种模式：
 *   - local  （源码默认，行为与历史版本完全一致）：Electron 启动本地 Python 后端进程。
 *   - remote ：后端已部署在另一台机器/服务器上，本机只装客户端。
 *             Electron 不起 Python，改起一个 127.0.0.1:<BACKEND_PORT> 的本地反向代理，
 *             把 /api/* 转发到远端并注入 X-API-Token。前端 core.ts 无需改动。
 *
 * 配置优先级（高 → 低）：
 *   1. 环境变量 CHALLENGE_DAILY_BACKEND_MODE / _URL / _TOKEN（批量部署 / 免 UI）
 *   2. userData/backend-config.json（用户在设置页保存的配置）
 *   3. resources/backend-default.json（随安装包分发的默认配置，由 CI 用 Secrets 注入）
 *   4. 内置默认值 { mode: 'local' }
 *
 * 设计要点：随包默认只作为「兜底」，用户一旦在设置页保存就写入 userData 并覆盖它；
 * 环境变量始终最高优先级。源码仓库不含任何真实地址/token。
 *
 * 安全：token 只存在主进程侧与包内资源文件，绝不通过 IPC/渲染层暴露。
 */

const fs = require('fs')
const path = require('path')
const { app } = require('electron')

const CONFIG_FILE = () => path.join(app.getPath('userData'), 'backend-config.json')
// 打包后 process.resourcesPath 指向 resources/；源码运行时回退到本文件同目录
const DEFAULT_FILE = () => path.join(process.resourcesPath || __dirname, 'backend-default.json')

const DEFAULTS = { mode: 'local', url: '', token: '' }

/** 合法模式：local（本机 Python）/ remote（本机代理转发云端）/ direct（渲染层直连云端） */
const VALID_MODES = ['local', 'remote', 'direct']

function _normalizeMode(raw) {
  const m = typeof raw === 'string' ? raw.trim().toLowerCase() : ''
  return VALID_MODES.includes(m) ? m : ''
}

function _sanitize(raw) {
  const mode = _normalizeMode(raw?.mode) || 'local'
  let url = typeof raw?.url === 'string' ? raw.url.trim().replace(/\/+$/, '') : ''
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

function _readJson(file) {
  try {
    if (fs.existsSync(file)) {
      // PowerShell Set-Content -Encoding UTF8 会写 BOM，JSON.parse 不接受，需先剥离
      const text = fs.readFileSync(file, 'utf-8').replace(/^\uFEFF/, '')
      return JSON.parse(text)
    }
  } catch (e) {
    console.error('[BackendConfig] read failed:', file, e?.message || e)
  }
  return {}
}

/** 读取配置（含随包默认与环境变量覆盖）。 */
function loadConfig() {
  const packaged = _readJson(DEFAULT_FILE())
  const file = _readJson(CONFIG_FILE())

  const merged = {
    mode: process.env.CHALLENGE_DAILY_BACKEND_MODE || file.mode || packaged.mode || DEFAULTS.mode,
    url: process.env.CHALLENGE_DAILY_BACKEND_URL || file.url || packaged.url || DEFAULTS.url,
    token: process.env.CHALLENGE_DAILY_BACKEND_TOKEN || file.token || packaged.token || DEFAULTS.token,
  }
  const cfg = _sanitize(merged)
  // remote / direct 都必须有有效 URL，否则回退 local，避免起一个必然不可用的链路
  if ((cfg.mode === 'remote' || cfg.mode === 'direct') && !cfg.url) {
    console.warn('[BackendConfig] %s mode requested but no valid URL, falling back to local', cfg.mode)
    cfg.mode = 'local'
  }
  return cfg
}

/** 保存配置到 userData（覆盖随包默认；环境变量不会被写回）。
 *  token 为空表示「不修改」，沿用当前生效配置的 token（可能来自随包默认）。 */
function saveConfig(raw) {
  const incoming = { ...(raw || {}) }
  if (!incoming.token) incoming.token = loadConfig().token
  const cfg = _sanitize(incoming)
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

/** 是否有随包默认配置（供设置页提示「已预置」）。 */
function hasPackagedDefault() {
  return Object.keys(_readJson(DEFAULT_FILE())).length > 0
}

/** 供 CSP 使用：remote 模式下需要放行的 origin。 */
function remoteOrigin() {
  const cfg = loadConfig()
  if (cfg.mode !== 'remote' || !cfg.url) return null
  try {
    return new URL(cfg.url).origin
  } catch (_) {
    return null
  }
}

module.exports = { loadConfig, saveConfig, remoteOrigin, hasPackagedDefault, DEFAULTS }
