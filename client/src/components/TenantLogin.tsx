import { useState } from 'react'
import { Building2, LockKeyhole, Loader2, LogIn } from 'lucide-react'
import { tenantLogin } from '../api/client'

/**
 * 租户登录页：启动最前面的拦截层。
 * 只在该客户端需要登录（云端多租户且本地无有效会话）时由 App 挂载。
 */
export default function TenantLogin({ onLogin }: { onLogin: (tenantId: string) => void }) {
  const [tenantId, setTenantId] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    if (!tenantId.trim() || !password || busy) return
    setBusy(true); setError('')
    try {
      const res = await tenantLogin(tenantId, password)
      if (res.ok) {
        onLogin(res.tenant_id || tenantId.trim())
      } else {
        setError(res.error || '登录失败')
        setPassword('')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[110] bg-cd-bg flex items-center justify-center select-none">
      <div className="w-[360px] max-w-[90vw]">
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-cd-accent/10 flex items-center justify-center mx-auto mb-4">
            <Building2 size={30} className="text-cd-accent" />
          </div>
          <h1 className="text-xl font-semibold text-cd-text">登录工作空间</h1>
          <p className="text-xs text-cd-text-tertiary mt-2">
            输入管理员分配的租户 ID 与登录密码
          </p>
        </div>
        <div className="space-y-4 bg-cd-panel rounded-xl p-6 border border-cd-border">
          <div>
            <label className="block text-xs text-cd-text-secondary mb-1.5">租户 ID</label>
            <div className="relative">
              <Building2 size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-cd-text-tertiary" />
              <input
                value={tenantId}
                onChange={e => { setTenantId(e.target.value); setError('') }}
                onKeyDown={e => e.key === 'Enter' && submit()}
                placeholder="例如 acme"
                autoFocus
                className="w-full bg-cd-bg border border-cd-border rounded-lg pl-10 pr-3 py-3 text-sm text-cd-text placeholder:text-cd-text-tertiary focus:outline-none focus:border-cd-accent/60"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs text-cd-text-secondary mb-1.5">登录密码</label>
            <div className="relative">
              <LockKeyhole size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-cd-text-tertiary" />
              <input
                type="password"
                value={password}
                onChange={e => { setPassword(e.target.value); setError('') }}
                onKeyDown={e => e.key === 'Enter' && submit()}
                placeholder="输入密码"
                className="w-full bg-cd-bg border border-cd-border rounded-lg pl-10 pr-3 py-3 text-sm text-cd-text placeholder:text-cd-text-tertiary focus:outline-none focus:border-cd-accent/60"
              />
            </div>
          </div>
          {error && <div className="text-xs text-red-500 text-center">{error}</div>}
          <button
            onClick={submit}
            disabled={!tenantId.trim() || !password || busy}
            className="w-full py-3 rounded-lg bg-cd-accent text-white font-medium flex items-center justify-center gap-2 hover:opacity-90 transition disabled:opacity-40"
          >
            {busy ? <><Loader2 size={16} className="animate-spin" /> 登录中...</> : <><LogIn size={16} /> 登录</>}
          </button>
        </div>
        <p className="text-center text-[11px] text-cd-text-tertiary mt-5">
          登录信息保存在本机，下次启动自动登录
        </p>
      </div>
    </div>
  )
}
