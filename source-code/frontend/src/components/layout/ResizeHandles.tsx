/**
 * 窗口四角缩放手柄
 *
 * 设计要点（v1.3.0 二次修复）：
 * - **只有四个角**可拖动，四条边不响应（用户明确要求）。
 * - **为什么必须由前端布热区**（本轮关键教训）：
 *   之前试图用窗口级 `WM_NCHITTEST` 钩子返回 HTTOPLEFT 等命中码，
 *   以为 Windows 就会自动进入缩放缓动环。实测证明行不通 ——
 *   `WindowFromPoint` 打在窗口四角，返回的是 `Chrome_RenderWidgetHostHWND`，
 *   即 WebView2 铺满了整个客户区。鼠标落在四角命中的是**子窗口**，
 *   主窗口的 WndProc 根本不会被调用，那个钩子在真实鼠标下是死代码。
 *   所以角部热区必须由 DOM 提供，命中后再主动通知后端。
 * - 拖动本身仍交给系统：mousedown 时把角告诉后端，后端发送
 *   `WM_NCLBUTTONDOWN(HTCORNER, 真实屏幕坐标)`，Windows 自己进入
 *   模态缩放缓动环（鼠标捕获、逐帧尺寸、最小尺寸约束全在 UI 线程同步完成），
 *   前端全程不做逐帧 IPC，因此既跟手又不会假死。
 * - 拖动结束后由 window resize 事件（防抖）把最终尺寸写回设置。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { bridgeService } from '@/services/bridge'
import { useFullscreenStore } from '@/stores/useFullscreenStore'
import { useSettingsStore } from '@/stores/useSettingsStore'

type Corner = 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'

/**
 * 角部热区边长（CSS 像素）。
 *
 * 取 18 而不是更小：窗口有圆角时最外侧 1~2px 会被 DWM 裁掉，
 * 太小会「明明点在角上却没命中」。又不能太大，
 * 否则会盖住标题栏右上角的「关闭」按钮。
 */
const CORNER_SIZE = 18
/** 尺寸写回设置的防抖时长 */
const SAVE_DEBOUNCE_MS = 600

const CURSORS: Record<Corner, string> = {
  'top-left': 'nwse-resize',
  'top-right': 'nesw-resize',
  'bottom-left': 'nesw-resize',
  'bottom-right': 'nwse-resize',
}

export function ResizeHandles() {
  const { isFullscreen } = useFullscreenStore()
  const updateSystemSettings = useSettingsStore((s) => s.updateSystemSettings)
  // 最大化时不画热区：最大化窗口本就不允许拖动缩放，
  // 画上去只会让鼠标在角落变成缩放箭头，误导用户。
  const [isMaximized, setIsMaximized] = useState(false)
  const saveTimerRef = useRef<number | null>(null)

  // 跟踪窗口最大化状态。窗口尺寸变化（含最大化/还原、系统级 Aero Snap）
  // 都会触发 resize 事件，在这里同步查询一次真实状态即可。
  useEffect(() => {
    let alive = true
    const sync = async () => {
      try {
        const res = await bridgeService.isMaximized()
        if (alive) setIsMaximized(!!res)
      } catch {
        /* 查询失败时保持原状，不影响缩放 */
      }
    }
    void sync()
    let timer: number | null = null
    const onResize = () => {
      if (timer !== null) window.clearTimeout(timer)
      timer = window.setTimeout(() => void sync(), 250)
    }
    window.addEventListener('resize', onResize)
    return () => {
      alive = false
      window.removeEventListener('resize', onResize)
      if (timer !== null) window.clearTimeout(timer)
    }
  }, [])

  /**
   * 拖动结束（或用户手动改窗口大小）后把真实尺寸写回设置
   *
   * **必须排除最大化状态**（本轮实测的坑）：
   *   本应用启动时是设计成总是最大化的（main.py reset_window_state 步骤4
   *   显式 SW_MAXIMIZE）。最大化会触发 resize 事件，若不加判断，
   *   600ms 后就把 `1920x1032`（屏幕工作区）写进 settings.appearance.windowSize，
   *   **直接覆盖用户上次拖出来的尺寸**。表现为：
   *     - 用户拖成 1024x640 → 设置里正确写入 1024x640；
   *     - 重开应用（自动最大化）→ 设置被悄悄改写成 1920x1032；
   *     - 点「还原」→ 回到 1920x1032，用户以为"缩放根本没保存"。
   *   注释早就写了"最大化 / 全屏状态下不写回"，但代码只判断了 isFullscreen，
   *   漏了 isMaximized —— 注释与实现不一致，靠实测才发现。
   *
   * 另：这里读的是 `window.outerWidth/outerHeight`，最大化时它就是屏幕工作区尺寸，
   * 所以不能靠"尺寸是否等于屏幕"来判断，只能靠最大化状态本身。
   */
  const scheduleSave = useCallback(() => {
    if (saveTimerRef.current !== null) {
      window.clearTimeout(saveTimerRef.current)
    }
    saveTimerRef.current = window.setTimeout(() => {
      saveTimerRef.current = null
      // 全屏 / 最大化状态下都不写回，否则会把「还原尺寸」覆盖成屏幕尺寸
      if (isFullscreen) return
      if (isMaximized) return
      // 双保险：查询一次真实最大化状态，防止 isMaximized 状态因事件时序滞后。
      // （resize 事件可能先于 sync() 完成，此时 state 还是旧值。）
      void bridgeService
        .isMaximized()
        .then((mx) => {
          if (mx) return
          if (window.outerWidth <= 0 || window.outerHeight <= 0) return
          const size = `${Math.round(window.outerWidth)}x${Math.round(window.outerHeight)}`
          return updateSystemSettings({ windowSize: size })
        })
        .catch((err) => {
          console.warn('[ResizeHandles] 保存窗口大小失败:', err)
        })
    }, SAVE_DEBOUNCE_MS)
  }, [isFullscreen, isMaximized, updateSystemSettings])

  useEffect(() => {
    // 原生缩放在拖动过程中由系统连续改变窗口尺寸；
    // 这里只做「结束后落盘」，不做任何逐帧处理。
    window.addEventListener('resize', scheduleSave)
    return () => {
      window.removeEventListener('resize', scheduleSave)
      if (saveTimerRef.current !== null) {
        window.clearTimeout(saveTimerRef.current)
        saveTimerRef.current = null
      }
    }
  }, [scheduleSave])

  const handleMouseDown = useCallback(
    (e: React.MouseEvent, corner: Corner) => {
      if (e.button !== 0) return
      e.preventDefault()
      e.stopPropagation()

      // 交给后端轮询缩放（后端读 GetCursorPos，不受 WebView2 抢鼠标捕获影响）
      void bridgeService.startNativeResize(corner).catch((err) => {
        console.warn('[ResizeHandles] 启动缩放失败:', err)
      })

      // **必须显式通知后端结束**。
      //
      // 后端轮询原本靠 GetAsyncKeyState(VK_LBUTTON) 判断松手，但它读的是
      // 物理按键状态：触摸板轻点、远程输入、以及合成事件下读数恒为"已松开"，
      // 轮询会第 0 帧就退出（实测日志 `左键已松开，结束（0 帧）`）。
      //
      // 用 window 级一次性监听而不是元素上的 onMouseUp：
      // 拖动过程中鼠标很快离开 18px 热区，元素收不到 mouseup，
      // 只有 window 级监听才可靠。
      const finish = () => {
        window.removeEventListener('mouseup', finish, true)
        window.removeEventListener('blur', finish, true)
        void bridgeService.stopNativeResize().catch(() => {
          /* 结束信号丢失时后端有 160ms 连续松开兜底，忽略即可 */
        })
      }
      window.addEventListener('mouseup', finish, true)
      // 窗口失焦（如 Alt+Tab 切走）也要结束，否则后端线程会一直轮询
      window.addEventListener('blur', finish, true)
    },
    []
  )

  // 全屏 / 最大化状态下不提供角部手柄
  if (isFullscreen || isMaximized) return null

  const base: React.CSSProperties = {
    position: 'fixed',
    zIndex: 9999,
    width: CORNER_SIZE,
    height: CORNER_SIZE,
    pointerEvents: 'auto',
    // 避免拖动时选中文字
    WebkitUserSelect: 'none',
    userSelect: 'none',
    // 只负责命中，不产生任何视觉
    background: 'transparent',
  }

  const corners: Corner[] = ['top-left', 'top-right', 'bottom-left', 'bottom-right']

  return (
    <>
      {corners.map((corner) => {
        const pos: React.CSSProperties = {}
        if (corner.startsWith('top')) pos.top = 0
        else pos.bottom = 0
        if (corner.endsWith('left')) pos.left = 0
        else pos.right = 0

        return (
          <div
            key={corner}
            className="resize-handle"
            style={{ ...base, ...pos, cursor: CURSORS[corner] }}
            onMouseDown={(e) => handleMouseDown(e, corner)}
          />
        )
      })}
    </>
  )
}
