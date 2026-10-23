/**
 * useBilibiliLastUpdate - B 站 UP 主最新投稿时间（预取 + 缓存模式）
 *
 * - 挂载即读后端磁盘缓存（秒回）；无缓存值时订阅预取进度
 * - 后端 prefetch 线程多轮收敛（5s 间隔 + 轮间退避），结果持久化
 * - 页面打开时先显示已缓存的博主，几分钟内未获取的逐个补齐
 */

import { useEffect, useState } from 'react'

/** 从 space.bilibili.com/{mid} 链接提取 UID */
export function extractBilibiliMid(link: string): string | null {
  if (!link) return null
  const m = link.match(/space\.bilibili\.com\/(\d+)/)
  return m ? m[1] : null
}

export function useBilibiliLastUpdate(
  link: string,
  platform: string
): { pubdate: number | null; loading: boolean } {
  const [pubdate, setPubdate] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)

  const mid = platform === 'bilibili' ? extractBilibiliMid(link) : null

  useEffect(() => {
    if (!mid || !window.pywebview?.api) {
      setPubdate(null)
      return
    }

    let cancelled = false
    let pollTimer: ReturnType<typeof setTimeout> | null = null

    const readCache = async (): Promise<boolean> => {
      try {
        const res = await window.pywebview.api.get_bilibili_last_update(mid)
        if (cancelled) return true
        if (res?.success && res.pubdate) {
          setPubdate(res.pubdate)
          setLoading(false)
          return true // 拿到了
        }
        return false
      } catch {
        if (!cancelled) setLoading(false)
        return true // 接口异常，停止轮询
      }
    }

    setLoading(true)
    readCache().then((hasValue) => {
      if (cancelled || hasValue) return
      // 无缓存值：轮询等待后台预取补齐（预取由 Grid 挂载时触发）
      const poll = async () => {
        const got = await readCache()
        if (cancelled) return
        if (got) return
        pollTimer = setTimeout(poll, 15000) // 15s 轮询预取进度
      }
      pollTimer = setTimeout(poll, 8000)
    })

    return () => {
      cancelled = true
      if (pollTimer) clearTimeout(pollTimer)
    }
  }, [mid])

  return { pubdate, loading }
}
