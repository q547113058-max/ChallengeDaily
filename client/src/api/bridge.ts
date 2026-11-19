// ── 屏幕追踪自动待办（经后端 /api/bridge 代理到线上同步服务）──
import { request, resolveApiUrl, getApiTokenSync } from './core'

export interface AutoTodo {
  id: number
  project: string
  todo: string
  basis: string
  source_ts: string
  confidence: 'high' | 'medium'
  status: 'proposed' | 'pending' | 'done' | 'dismissed'
  created_at: string
  last_seen_at: string
  proposed_at?: string | null
}

export async function getBridgeStatus(): Promise<{ ok: boolean; enabled: boolean; reason?: string }> {
  return request('/api/bridge/status') as Promise<{ ok: boolean; enabled: boolean; reason?: string }>
}

export async function decideAutoTodo(
  id: number,
  action: 'approve' | 'reject',
): Promise<{ ok: boolean; id: number; status: string }> {
  return request(`/api/bridge/todos/${id}/${action}`, { method: 'POST', body: '{}' }) as Promise<{ ok: boolean; id: number; status: string }>
}

/** 订阅 SSE。注意 EventSource 不能自定义 header，故 token 由后端代理注入。 */
export function subscribeBridgeEvents(
  onEvent: (e: BridgeEvent) => void,
): () => void {
  // EventSource 不能带自定义 header，token 走 query param（后端 /api/bridge/events 已自行校验）
  const tok = getApiTokenSync()
  const url = resolveApiUrl(`/api/bridge/events${tok ? `?token=${encodeURIComponent(tok)}` : ''}`)
  const es = new EventSource(url)
  es.onmessage = (ev) => {
    try { onEvent(JSON.parse(ev.data)) } catch { /* 忽略心跳/坏包 */ }
  }
  return () => es.close()
}

export interface BridgeEvent {
  rev: number
  action: 'insert' | 'refresh' | 'status' | 'error' | 'disabled'
  id?: number
  status?: string
  ts?: string
  detail?: AutoTodo
  error?: string
}

export async function getAutoTodos(status = 'pending'): Promise<{ todos: AutoTodo[]; rev: number }> {
  return request(`/api/bridge/todos?status=${status}`) as Promise<{ todos: AutoTodo[]; rev: number }>
}

export async function setAutoTodoStatus(
  id: number,
  status: 'done' | 'dismissed',
): Promise<{ ok: boolean; id: number; status: string }> {
  return request(`/api/bridge/todos/${id}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  }) as Promise<{ ok: boolean; id: number; status: string }>
}
