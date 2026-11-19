import { useState, useEffect, useRef } from 'react'
import { Quote } from 'lucide-react'
import { getQuote } from '../api/client'
import { DATA_REFRESH_MS } from '../config/refresh'
import { useVisibleInterval } from '../hooks/useVisibleInterval'

export default function QuoteBar() {
  const [quote, setQuote] = useState('')
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    getQuote()
      .then(data => { if (aliveRef.current) setQuote(data.quote) })
      .catch(() => {})
    return () => { aliveRef.current = false }
  }, [])

  // 仅页面可见时刷新语录（隐藏时定时器真正停止）
  useVisibleInterval(() => {
    getQuote()
      .then(data => { if (aliveRef.current) setQuote(data.quote) })
      .catch(() => {})
  }, DATA_REFRESH_MS)

  if (!quote) return null

  return (
    <div className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-purple-500/5 to-gold/5 rounded-lg border border-purple-400/10">
      <Quote size={14} className="text-purple-400 shrink-0" />
      <p className="text-sm text-cd-text-secondary italic">{quote}</p>
    </div>
  )
}
