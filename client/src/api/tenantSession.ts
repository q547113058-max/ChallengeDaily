// ── 租户登录态（本地持久化）────────────────────────────────────────────
// 为什么存 localStorage 而不是 serverStorage：
//   读取 /api/client-state 本身就需要 X-API-Token，若登录态也放服务端
//   会形成「先有鸡还是先有蛋」。因此登录凭据必须在本地，登录成功后
//   注入 core 的 token，后续业务状态照常走 serverStorage。

const SESSION_KEY = 'cd_tenant_session_v1'

export interface TenantSession {
  tenant_id: string
  token: string
  name?: string
  loginAt?: string
}

export function loadTenantSession(): TenantSession | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY)
    if (!raw) return null
    const obj = JSON.parse(raw)
    if (!obj || !obj.tenant_id || !obj.token) return null
    return obj as TenantSession
  } catch {
    return null
  }
}

export function saveTenantSession(s: TenantSession): void {
  localStorage.setItem(SESSION_KEY, JSON.stringify(s))
}

export function clearTenantSession(): void {
  localStorage.removeItem(SESSION_KEY)
}

export function getSessionToken(): string {
  return loadTenantSession()?.token || ''
}
