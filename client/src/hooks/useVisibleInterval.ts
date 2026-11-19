import { useEffect, useRef } from 'react'

/**
 * 仅在页面可见时运行的定时器。
 *
 * 与「定时器照常跑、回调里判断 document.hidden」不同：不可见时会**真正清除定时器**，
 * 后台不再有任何空转。恢复可见时立即执行一次，再重建定时器。
 *
 * @param callback  每次触发要执行的函数（会通过 ref 拿到最新引用，无需担心闭包陈旧）
 * @param intervalMs 间隔毫秒；传 undefined/0 表示不启用
 * @param options.runOnVisible 恢复可见时是否立即执行一次（默认 true）
 *
 * @example
 *   useVisibleInterval(() => refresh(), DATA_REFRESH_MS)
 */
export function useVisibleInterval(
  callback: () => void,
  intervalMs: number | undefined,
  options: { runOnVisible?: boolean } = {},
): void {
  const { runOnVisible = true } = options
  // 用 ref 保存最新回调，避免因回调身份变化而反复重建定时器
  const cbRef = useRef(callback)
  cbRef.current = callback

  useEffect(() => {
    if (!intervalMs || intervalMs <= 0) return

    let timer: ReturnType<typeof setInterval> | null = null
    let disposed = false

    const start = () => {
      if (disposed || timer) return
      timer = setInterval(() => {
        if (!document.hidden) cbRef.current()
      }, intervalMs)
    }
    const stop = () => {
      if (timer) { clearInterval(timer); timer = null }
    }

    const onVisibility = () => {
      if (document.hidden) {
        // 不可见：彻底停掉，不产生任何后台请求
        stop()
      } else {
        // 恢复可见：先立即执行一次，再继续定时
        if (runOnVisible) cbRef.current()
        start()
      }
    }

    // 初始：只有可见才启动
    if (!document.hidden) start()
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      disposed = true
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [intervalMs, runOnVisible])
}
