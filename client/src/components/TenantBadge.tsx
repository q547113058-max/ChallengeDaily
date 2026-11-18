import { useEffect, useState } from 'react'
import { Building2 } from 'lucide-react'
import { getTenantInfo, type TenantInfo } from '../api/client'

/**
 * 当前租户标识：从云端 /api/tenant/me 读取。
 * - 多租户云端：显示租户名 + token 提示
 * - 旧版服务端（无该接口）或本机模式：静默隐藏
 */
export default function TenantBadge() {
  const [info, setInfo] = useState<TenantInfo | null>(null)

  useEffect(() => {
    let alive = true
    getTenantInfo().then(t => { if (alive && t && t.role === 'tenant') setInfo(t) })
    return () => { alive = false }
  }, [])

  if (!info) return null

  return (
    <div
      className="flex items-center gap-1.5 px-3 pt-2 pb-1 text-[11px] text-cd-text-tertiary"
      title={`租户 ID: ${info.tenant_id || ''}\nToken: ${info.token_hint || ''}\n创建于: ${info.created_at || ''}`}
    >
      <Building2 size={12} />
      <span className="truncate">{info.name || info.tenant_id}</span>
      {info.enabled === false && <span className="text-cd-red">· 已停用</span>}
    </div>
  )
}
