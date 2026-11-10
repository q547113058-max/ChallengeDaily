import { useCallback, useEffect, useState } from 'react'
import { Server, Globe, KeyRound, Save, AlertCircle, CheckCircle, RotateCcw } from 'lucide-react'
import { useToast } from './Toast'

/**
 * 后端连接设置：本地后端（默认） / 远程后端（后端已部署在别处，本机只装客户端）。
 * 保存后需重启应用才生效（主进程在启动时决定 spawn Python 还是起本地代理）。
 * token 只写不读：读回接口只返回 hasToken，避免明文经 IPC 暴露给渲染层。
 */
export default function BackendConnectionSettings() {
  const toast = useToast()
  const api = typeof window !== 'undefined' ? window.electronAPI : undefined
  const [mode, setMode] = useState<'local' | 'remote'>('local')
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [hasToken, setHasToken] = useState(false)
  const [envOverride, setEnvOverride] = useState(false)
  const [saving, setSaving] = useState(false)
  const [supported, setSupported] = useState(true)

  useEffect(() => {
    if (!api?.backendConfigGet) { setSupported(false); return }
    api.backendConfigGet().then((c) => {
      setMode(c.mode)
      setUrl(c.url)
      setHasToken(c.hasToken)
      setEnvOverride(c.envOverride)
    }).catch(() => {})
  }, [api])

  const doSave = useCallback(async () => {
    if (!api?.backendConfigSet || saving) return
    if (mode === 'remote' && !url.trim()) {
      toast.error('远程模式必须填写后端地址')
      return
    }
    setSaving(true)
    try {
      // token 留空表示沿用已保存的 token（后端读回不含明文）
      const res = await api.backendConfigSet({ mode, url: url.trim(), token: token.trim() })
      if (!res.ok) {
        toast.error(res.error || '保存失败')
      } else {
        setToken('')
        setHasToken(Boolean(token.trim()) || hasToken)
        toast.success('已保存，重启应用后生效')
      }
    } catch (e) {
      toast.error(`保存失败：${String(e)}`)
    } finally {
      setSaving(false)
    }
  }, [api, mode, url, token, saving, toast, hasToken])

  if (!supported) return null

  return (
    <div className="rounded-lg border border-cd-border bg-cd-bg-secondary/50 p-3 space-y-3">
      <div className="flex items-center gap-2">
        <Server size={14} className="text-cd-green" />
        <p className="text-xs font-medium text-cd-text">后端连接</p>
      </div>
      <p className="text-[11px] text-cd-text-tertiary">
        默认在本机运行后端。若后端已部署在其他机器，选择「远程后端」，本机只装客户端。
      </p>

      <div className="flex gap-2">
        {(['local', 'remote'] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            disabled={envOverride}
            className={`flex-1 py-1.5 rounded-lg text-xs font-medium border transition-colors disabled:opacity-50 ${
              mode === m
                ? 'bg-cd-green-light text-cd-green border-cd-green'
                : 'bg-cd-bg-secondary text-cd-text-secondary border-cd-border hover:bg-cd-hover'
            }`}
          >
            {m === 'local' ? '本机后端' : '远程后端'}
          </button>
        ))}
      </div>

      {mode === 'remote' && (
        <div className="space-y-2">
          <label className="block">
            <span className="flex items-center gap-1.5 text-[11px] text-cd-text-secondary mb-1">
              <Globe size={11} /> 后端地址
            </span>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={envOverride}
              placeholder="http://192.168.1.10:58888"
              className="w-full px-2.5 py-1.5 rounded-lg text-xs bg-cd-bg border border-cd-border text-cd-text placeholder:text-cd-text-tertiary focus:outline-none focus:ring-1 focus:ring-cd-green disabled:opacity-50"
            />
          </label>
          <label className="block">
            <span className="flex items-center gap-1.5 text-[11px] text-cd-text-secondary mb-1">
              <KeyRound size={11} /> API Token
              {hasToken && <span className="text-cd-green">（已保存，留空则不修改）</span>}
            </span>
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              disabled={envOverride}
              placeholder={hasToken ? '••••••••（已保存）' : '后端 X-API-Token'}
              className="w-full px-2.5 py-1.5 rounded-lg text-xs bg-cd-bg border border-cd-border text-cd-text placeholder:text-cd-text-tertiary focus:outline-none focus:ring-1 focus:ring-cd-green disabled:opacity-50"
            />
          </label>
          <p className="flex items-start gap-1.5 text-[10px] text-cd-text-tertiary">
            <AlertCircle size={11} className="mt-0.5 shrink-0" />
            客户端会在本机 127.0.0.1:58888 起一个反向代理转发请求，Token 只保存在主进程，不会发给页面。
          </p>
        </div>
      )}

      {envOverride && (
        <p className="flex items-center gap-1.5 text-[11px] text-amber-400">
          <AlertCircle size={12} /> 配置已由环境变量锁定，界面不可修改
        </p>
      )}

      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[10px] text-cd-text-tertiary">
          <RotateCcw size={11} /> 修改后需重启应用
        </p>
        <button
          onClick={doSave}
          disabled={saving || envOverride}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-cd-green hover:bg-cd-green-dark text-white disabled:opacity-50 transition-colors"
        >
          {saving ? <CheckCircle size={12} /> : <Save size={12} />}
          保存
        </button>
      </div>
    </div>
  )
}
