/**
 * 资产库瀑布流网格 - 横向瀑布流布局
 */

import { useRef, useCallback, forwardRef, useImperativeHandle, useMemo, useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useAssetStore } from '@/stores/useAssetStore'
import { AssetCard } from './AssetCard'
import { AssetFolderCard } from './AssetFolderCard'
import type { Asset } from '@/mocks/asset'

export interface AssetMasonryGridRef {
  getCardRefs: () => Map<string, HTMLDivElement>
}

interface AssetMasonryGridProps {
  onImageClick?: (asset: Asset) => void
  onImageDoubleClick?: (asset: Asset) => void
  onImageContextMenu?: (e: React.MouseEvent, asset: Asset) => void
}

const SKELETON_HEIGHTS = [320, 280, 400, 350, 260, 380, 300, 420, 340, 290, 360, 310]
const GAP = 20

/**
 * 首屏渲染的卡片数，以及每次滚动到底追加多少张。
 *
 * 原实现一次性把全部资产渲染成 DOM：3000 个 AssetCard 意味着 3000 棵组件子树
 * 同时挂载，首屏就要几百 MB 内存和数秒卡顿，滚动更是持续掉帧。
 * 改为渐进渲染后，DOM 节点数只与"已滚动到的位置"相关，与资产总量脱钩。
 */
const INITIAL_RENDER_COUNT = 120
const RENDER_BATCH_SIZE = 120

export const AssetMasonryGrid = forwardRef<AssetMasonryGridRef, AssetMasonryGridProps>(
  function AssetMasonryGrid({ onImageClick, onImageDoubleClick, onImageContextMenu }, ref) {
    const { t } = useTranslation()
    const {
      isLoading,
      setSelectedCategoryId,
      clearSelection,
      setBatchMode,
      isBatchMode,
      thumbnailSize
    } = useAssetStore()
    const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map())
    const containerRef = useRef<HTMLDivElement>(null)
    const sentinelRef = useRef<HTMLDivElement>(null)
    const [columnCount, setColumnCount] = useState(4)
    // 当前已渲染的资产数量（渐进渲染游标）
    const [renderCount, setRenderCount] = useState(INITIAL_RENDER_COUNT)

    useImperativeHandle(ref, () => ({
      getCardRefs: () => cardRefs.current
    }))

    const registerCardRef = useCallback((id: string, el: HTMLDivElement | null) => {
      if (el) {
        cardRefs.current.set(id, el)
      } else {
        cardRefs.current.delete(id)
      }
    }, [])

    // 过滤 / 排序结果做记忆化。
    // 原实现直接在 body 里调 getFilteredAssets() + getGalleryItems()，
    // 每次渲染都会重跑 5 轮 filter + 一次全量 sort + 全量 map，
    // 资产上千时单次重渲染就要几百毫秒，滚动和选中态变化都会明显卡顿。
    const filteredAssets = useAssetStore((s) => s.getFilteredAssets())
    const galleryItems = useAssetStore((s) => s.getGalleryItems())

    const folderItems = useMemo(
      () => galleryItems.filter((item) => item.kind === 'folder'),
      [galleryItems]
    )

    // 过滤条件变化（换分类 / 搜索 / 筛选）时，渲染游标要归位，
    // 否则会停在上一批的深度上，看起来像"没加载出来"。
    useEffect(() => {
      setRenderCount(INITIAL_RENDER_COUNT)
    }, [filteredAssets])

    // 滚到底部继续渲染下一批
    useEffect(() => {
      const sentinel = sentinelRef.current
      if (!sentinel || renderCount >= filteredAssets.length) return

      const observer = new IntersectionObserver(
        (entries) => {
          if (entries[0]?.isIntersecting) {
            setRenderCount((prev) =>
              Math.min(prev + RENDER_BATCH_SIZE, filteredAssets.length)
            )
          }
        },
        { rootMargin: '800px' }
      )
      observer.observe(sentinel)
      return () => observer.disconnect()
    }, [renderCount, filteredAssets.length])

    useEffect(() => {
      const updateColumnCount = () => {
        if (containerRef.current) {
          const containerWidth = containerRef.current.offsetWidth - 48
          const count = Math.max(1, Math.floor((containerWidth + GAP) / (thumbnailSize + GAP)))
          setColumnCount(count)
        }
      }
      
      updateColumnCount()
      window.addEventListener('resize', updateColumnCount)
      return () => window.removeEventListener('resize', updateColumnCount)
    }, [thumbnailSize])

    const columns = useMemo(() => {
      const safeColumnCount = Math.max(1, columnCount)
      const result: Asset[][] = Array.from({ length: safeColumnCount }, () => [])
      const columnHeights: number[] = Array(safeColumnCount).fill(0)
      
      // 只对"已进入渲染窗口"的资产分列，保证 DOM 数量可控
      for (const asset of filteredAssets.slice(0, renderCount)) {
        if (!asset || !asset.width || !asset.height) continue
        
        const minHeightIndex = columnHeights.indexOf(Math.min(...columnHeights))
        if (minHeightIndex >= 0 && result[minHeightIndex]) {
          result[minHeightIndex].push(asset)
          columnHeights[minHeightIndex] += asset.height / asset.width
        }
      }
      
      return result
    }, [filteredAssets, columnCount, renderCount])

    const folderGridStyle = useMemo(() => ({
      gridTemplateColumns: `repeat(${Math.max(1, columnCount)}, minmax(0, 1fr))`
    }), [columnCount])

    const handleOpenFolder = useCallback((categoryId: string) => {
      clearSelection()
      setBatchMode(false)
      setSelectedCategoryId(categoryId)
    }, [clearSelection, setBatchMode, setSelectedCategoryId])

    const skeletonHeights = useMemo(() => SKELETON_HEIGHTS, [])

    if (isLoading) {
      return (
        <div ref={containerRef} className="flex gap-5 p-6">
          {Array.from({ length: columnCount }).map((_, colIndex) => (
            <div key={colIndex} className="flex flex-1 flex-col gap-5">
              {Array.from({ length: 3 }).map((_, i) => (
                <div
                  key={i}
                  className="rounded-lg bg-surface-active"
                  style={{ height: `${skeletonHeights[(colIndex * 3 + i) % skeletonHeights.length]}px` }}
                >
                  <div className="h-full animate-pulse rounded-lg bg-surface-active" />
                </div>
              ))}
            </div>
          ))}
        </div>
      )
    }

    if (filteredAssets.length === 0) {
      if (folderItems.length > 0) {
        return (
          <div ref={containerRef} className="p-6">
            <div className="grid gap-5" style={folderGridStyle}>
              {folderItems.map((item) => (
                <AssetFolderCard
                  key={item.category.id}
                  category={item.category}
                  assetCount={item.assetCount}
                  onOpen={handleOpenFolder}
                />
              ))}
            </div>
          </div>
        )
      }

      return (
        <div ref={containerRef} className="flex h-full items-center justify-center">
          <div className="text-center">
            <p className="text-muted-foreground">{t('asset.noAssets')}</p>
          </div>
        </div>
      )
    }

    return (
      <div ref={containerRef} className="p-6">
        {folderItems.length > 0 && (
          <div className="mb-6 grid gap-5" style={folderGridStyle}>
            {folderItems.map((item) => (
              <AssetFolderCard
                key={item.category.id}
                category={item.category}
                assetCount={item.assetCount}
                onOpen={handleOpenFolder}
              />
            ))}
          </div>
        )}

        {filteredAssets.length > 0 && (
          <div className="flex gap-5">
            {columns.map((column, colIndex) => (
              <div key={colIndex} className="flex flex-1 flex-col gap-5">
                {column.map((asset) => (
                  <AssetCard
                    key={asset.id}
                    asset={asset}
                    ref={(el) => registerCardRef(asset.id, el)}
                    onClick={() => onImageClick?.(asset)}
                    onDoubleClick={() => onImageDoubleClick?.(asset)}
                    onContextMenu={(e) => onImageContextMenu?.(e, asset)}
                    isBatchMode={isBatchMode}
                  />
                ))}
              </div>
            ))}
          </div>
        )}

        {/* 滚动哨兵：进入视口就渲染下一批 */}
        {renderCount < filteredAssets.length && (
          <div ref={sentinelRef} className="h-px w-full" aria-hidden="true" />
        )}
      </div>
    )
  }
)
