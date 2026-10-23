/**
 * 窗口大小调整手柄组件
 *
 * 在窗口的四个角 + 四条边添加透明的拖动区域，允许用户自由调整窗口大小：
 * - 四角：同时改变宽高（nwse / nesw 光标）
 * - 四边：仅改变单方向尺寸（ns-resize / ew-resize）
 *
 * 拖动结束后把最终尺寸写入系统设置（windowSize），下次启动沿用。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { bridgeService } from '@/services/bridge'
import { useFullscreenStore } from '@/stores/useFullscreenStore'
import { useSettingsStore } from '@/stores/useSettingsStore'

type Handle = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'
  | 'top' | 'bottom' | 'left' | 'right'

interface ResizeState {
  isResizing: boolean
  corner: Handle | null
  startX: number
  startY: number
  startWidth: number
  startHeight: number
  startWindowX: number
  startWindowY: number
}

const HANDLE_SIZE = 16
/** 最小窗口尺寸（逻辑像素）——需与后端 min_size / resizeWindowWithPosition 保持一致 */
const MIN_WIDTH = 1024
const MIN_HEIGHT = 640

export function ResizeHandles() {
  const { isFullscreen } = useFullscreenStore()
  const { updateSystemSettings } = useSettingsStore()
  const [resizeState, setResizeState] = useState<ResizeState>({
    isResizing: false,
    corner: null,
    startX: 0,
    startY: 0,
    startWidth: 0,
    startHeight: 0,
    startWindowX: 0,
    startWindowY: 0,
  })

  const animationFrameRef = useRef<number | null>(null)
  const pendingResizeRef = useRef<{
    width: number
    height: number
    x: number
    y: number
  } | null>(null)

  const getCursorStyle = (handle: Handle): string => {
    switch (handle) {
      case 'top-left':
      case 'bottom-right':
        return 'nwse-resize'
      case 'top-right':
      case 'bottom-left':
        return 'nesw-resize'
      case 'top':
      case 'bottom':
        return 'ns-resize'
      case 'left':
      case 'right':
        return 'ew-resize'
    }
  }

  const handleMouseDown = useCallback((e: React.MouseEvent, handle: Handle) => {
    e.preventDefault()
    e.stopPropagation()

    const dpr = window.devicePixelRatio || 1
    const startX = e.screenX / dpr
    const startY = e.screenY / dpr
    const startWidth = window.outerWidth
    const startHeight = window.outerHeight
    const startWindowX = window.screenX
    const startWindowY = window.screenY

    setResizeState({
      isResizing: true,
      corner: handle,
      startX,
      startY,
      startWidth,
      startHeight,
      startWindowX,
      startWindowY,
    })
  }, [])

  const saveWindowSize = useCallback(async (width: number, height: number) => {
    try {
      const windowSizeString = `${width}x${height}`
      console.log(`[ResizeHandles] 保存窗口大小: ${windowSizeString}`)
      await updateSystemSettings({ windowSize: windowSizeString })
      console.log(`[ResizeHandles] 窗口大小保存成功`)
    } catch (error) {
      console.error('[ResizeHandles] 保存窗口大小失败:', error)
    }
  }, [updateSystemSettings])

  useEffect(() => {
    if (!resizeState.isResizing) return

    const {
      corner,
      startX,
      startY,
      startWidth,
      startHeight,
      startWindowX,
      startWindowY,
    } = resizeState

    const performResize = async (width: number, height: number, x: number, y: number) => {
      try {
        await bridgeService.resizeWindowWithPosition(width, height, x, y)
      } catch (error) {
        console.error('[ResizeHandles] 调整窗口大小失败:', error)
      }
    }

    const handleMouseMove = (e: MouseEvent) => {
      const dpr = window.devicePixelRatio || 1
      const deltaX = (e.screenX / dpr) - startX
      const deltaY = (e.screenY / dpr) - startY

      let newWidth = startWidth
      let newHeight = startHeight
      let newX = startWindowX
      let newY = startWindowY

      switch (corner) {
        case 'top-left':
          newWidth = Math.max(MIN_WIDTH, startWidth - deltaX)
          newHeight = Math.max(MIN_HEIGHT, startHeight - deltaY)
          newX = startWindowX + (startWidth - newWidth)
          newY = startWindowY + (startHeight - newHeight)
          break
        case 'top-right':
          newWidth = Math.max(MIN_WIDTH, startWidth + deltaX)
          newHeight = Math.max(MIN_HEIGHT, startHeight - deltaY)
          newX = startWindowX
          newY = startWindowY + (startHeight - newHeight)
          break
        case 'bottom-left':
          newWidth = Math.max(MIN_WIDTH, startWidth - deltaX)
          newHeight = Math.max(MIN_HEIGHT, startHeight + deltaY)
          newX = startWindowX + (startWidth - newWidth)
          newY = startWindowY
          break
        case 'bottom-right':
          newWidth = Math.max(MIN_WIDTH, startWidth + deltaX)
          newHeight = Math.max(MIN_HEIGHT, startHeight + deltaY)
          newX = startWindowX
          newY = startWindowY
          break
        // 四条边：仅改变单方向尺寸
        case 'top':
          newHeight = Math.max(MIN_HEIGHT, startHeight - deltaY)
          newY = startWindowY + (startHeight - newHeight)
          break
        case 'bottom':
          newHeight = Math.max(MIN_HEIGHT, startHeight + deltaY)
          break
        case 'left':
          newWidth = Math.max(MIN_WIDTH, startWidth - deltaX)
          newX = startWindowX + (startWidth - newWidth)
          break
        case 'right':
          newWidth = Math.max(MIN_WIDTH, startWidth + deltaX)
          break
      }

      const roundedWidth = Math.round(newWidth)
      const roundedHeight = Math.round(newHeight)
      const roundedX = Math.round(newX)
      const roundedY = Math.round(newY)

      pendingResizeRef.current = {
        width: roundedWidth,
        height: roundedHeight,
        x: roundedX,
        y: roundedY,
      }

      if (!animationFrameRef.current) {
        animationFrameRef.current = requestAnimationFrame(() => {
          animationFrameRef.current = null
          if (pendingResizeRef.current) {
            performResize(
              pendingResizeRef.current.width,
              pendingResizeRef.current.height,
              pendingResizeRef.current.x,
              pendingResizeRef.current.y
            )
          }
        })
      }
    }

    const handleMouseUp = async () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current)
        animationFrameRef.current = null
      }

      if (pendingResizeRef.current) {
        await performResize(
          pendingResizeRef.current.width,
          pendingResizeRef.current.height,
          pendingResizeRef.current.x,
          pendingResizeRef.current.y
        )

        await saveWindowSize(
          pendingResizeRef.current.width,
          pendingResizeRef.current.height
        )
      }

      setResizeState((prev) => ({
        ...prev,
        isResizing: false,
        corner: null,
      }))
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)

    document.body.style.cursor = resizeState.corner
      ? getCursorStyle(resizeState.corner)
      : 'default'
    document.body.style.userSelect = 'none'

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''

      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current)
        animationFrameRef.current = null
      }
    }
  }, [resizeState, saveWindowSize])

  if (isFullscreen) {
    return null
  }

  const handleStyle: React.CSSProperties = {
    position: 'fixed',
    zIndex: 9999,
    pointerEvents: 'auto',
  }

  const handles: { handle: Handle; style: React.CSSProperties }[] = [
    // 四角
    {
      handle: 'top-left',
      style: { ...handleStyle, top: 0, left: 0, width: HANDLE_SIZE, height: HANDLE_SIZE, cursor: 'nwse-resize' },
    },
    {
      handle: 'top-right',
      style: { ...handleStyle, top: 0, right: 0, width: HANDLE_SIZE, height: HANDLE_SIZE, cursor: 'nesw-resize' },
    },
    {
      handle: 'bottom-left',
      style: { ...handleStyle, bottom: 0, left: 0, width: HANDLE_SIZE, height: HANDLE_SIZE, cursor: 'nesw-resize' },
    },
    {
      handle: 'bottom-right',
      style: { ...handleStyle, bottom: 0, right: 0, width: HANDLE_SIZE, height: HANDLE_SIZE, cursor: 'nwse-resize' },
    },
    // 四边（角部区域留给四角手柄，避免抢占点击）
    {
      handle: 'top',
      style: { ...handleStyle, top: 0, left: HANDLE_SIZE, right: HANDLE_SIZE, height: HANDLE_SIZE, cursor: 'ns-resize' },
    },
    {
      handle: 'bottom',
      style: { ...handleStyle, bottom: 0, left: HANDLE_SIZE, right: HANDLE_SIZE, height: HANDLE_SIZE, cursor: 'ns-resize' },
    },
    {
      handle: 'left',
      style: { ...handleStyle, top: HANDLE_SIZE, bottom: HANDLE_SIZE, left: 0, width: HANDLE_SIZE, cursor: 'ew-resize' },
    },
    {
      handle: 'right',
      style: { ...handleStyle, top: HANDLE_SIZE, bottom: HANDLE_SIZE, right: 0, width: HANDLE_SIZE, cursor: 'ew-resize' },
    },
  ]

  return (
    <>
      {handles.map(({ handle, style }) => (
        <div
          key={handle}
          style={style}
          onMouseDown={(e) => handleMouseDown(e, handle)}
          className="resize-handle"
        />
      ))}
    </>
  )
}
