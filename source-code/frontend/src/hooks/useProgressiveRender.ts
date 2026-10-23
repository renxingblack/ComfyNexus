/**
 * useProgressiveRender - 万级列表渐进渲染 Hook
 *
 * 首屏只渲染 INITIAL_RENDER_COUNT 条，滚动接近底部时按批追加。
 * DOM 节点数与数据总量脱钩，万级数据下保持流畅滚动。
 *
 * 用法：
 *   const { rendered, sentinelRef, hasMore } = useProgressiveRender(filteredItems)
 *   ...
 *   {rendered.map(item => <Card key={item.id} />)}
 *   {hasMore && <div ref={sentinelRef} className="h-px" />}
 *
 * 注意：deps 变化（数据/过滤条件变化）时渲染游标自动归位，
 * 调用方只需把 useMemo 后的过滤结果传进来。
 */

import { useEffect, useMemo, useRef, useState } from 'react'

interface Options {
  /** 首屏渲染条数 */
  initialCount?: number
  /** 每批追加条数 */
  batchSize?: number
  /** 触底预加载距离（px） */
  rootMargin?: string
}

export function useProgressiveRender<T>(
  items: readonly T[],
  options: Options = {}
) {
  const { initialCount = 100, batchSize = 100, rootMargin = '600px' } = options

  const [renderCount, setRenderCount] = useState(initialCount)
  const sentinelRef = useRef<HTMLDivElement>(null)

  // 数据源变化（含过滤条件变化导致的数组引用变化）时游标归位，
  // 避免停在上一批深度导致"看起来没加载出来"
  useEffect(() => {
    setRenderCount(initialCount)
  }, [items, initialCount])

  const hasMore = renderCount < items.length

  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel || !hasMore) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setRenderCount((prev) => Math.min(prev + batchSize, items.length))
        }
      },
      { rootMargin }
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [hasMore, items.length, batchSize, rootMargin])

  const rendered = useMemo(
    () => (renderCount >= items.length ? items : items.slice(0, renderCount)),
    [items, renderCount]
  )

  return { rendered, sentinelRef, hasMore, renderCount }
}
