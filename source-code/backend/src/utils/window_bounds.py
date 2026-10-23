"""
窗口边界检查和自动调整工具
用于多显示器环境下防止窗口移出可视区域

注意：所有函数必须在主 UI 线程中调用，不能在后台线程中调用。
"""

import ctypes
import ctypes.wintypes as wintypes
from typing import Tuple, Optional
from backend.src.utils.logger import app_logger as logger


# ============================================================================
# Windows 结构体定义
# ============================================================================

class RECT(ctypes.Structure):
    """Windows RECT 结构体"""
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MONITORINFO(ctypes.Structure):
    """Windows MONITORINFO 结构体"""
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


class POINT(ctypes.Structure):
    """Windows POINT 结构体"""
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


# ============================================================================
# Win32 API 类型安全定义（64位系统兼容）
# 
# 重要：使用 ctypes.WinDLL 创建单独的 user32 实例，而不是使用 windll.user32
# 因为 windll.user32 是全局单例，设置 argtypes 会影响所有使用它的代码（包括 pywebview）
# ============================================================================

_user32 = ctypes.WinDLL("user32")

# MonitorFromWindow
_user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.MonitorFromWindow.restype = wintypes.HMONITOR

# MonitorFromPoint
_user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
_user32.MonitorFromPoint.restype = wintypes.HMONITOR

# GetMonitorInfoW
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL

# GetWindowRect
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL

# GetCursorPos
_user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
_user32.GetCursorPos.restype = wintypes.BOOL

# SetWindowPos
_user32.SetWindowPos.argtypes = [
    wintypes.HWND,      # hWnd
    wintypes.HWND,      # hWndInsertAfter
    ctypes.c_int,       # X
    ctypes.c_int,       # Y
    ctypes.c_int,       # cx
    ctypes.c_int,       # cy
    wintypes.UINT       # uFlags
]
_user32.SetWindowPos.restype = wintypes.BOOL

# FindWindowW
_user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.FindWindowW.restype = wintypes.HWND

# ShowWindow
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.ShowWindow.restype = wintypes.BOOL

# SetWindowLongPtrW（64 位必须用 Ptr 版本做子类化，不能用 SetWindowLongW）
_user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LPARAM]
_user32.SetWindowLongPtrW.restype = wintypes.LPARAM

# GetWindowLongPtrW
_user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowLongPtrW.restype = wintypes.LPARAM

# CallWindowProcW
_user32.CallWindowProcW.argtypes = [
    wintypes.LPARAM,   # lpPrevWndFunc
    wintypes.HWND,     # hWnd
    wintypes.UINT,     # Msg
    wintypes.WPARAM,   # wParam
    wintypes.LPARAM,   # lParam
]
_user32.CallWindowProcW.restype = wintypes.LPARAM


# ============================================================================
# 核心函数
# ============================================================================

def get_monitor_info(hwnd: int) -> Optional[dict]:
    """
    获取窗口所在显示器的信息
    
    关键：使用 MonitorFromWindow 获取窗口所在的显示器，
    而不是主显示器。这是多显示器支持的核心。
    
    Args:
        hwnd: 窗口句柄
        
    Returns:
        dict: {
            "monitor_rect": (left, top, right, bottom),  # 显示器完整区域
            "work_rect": (left, top, right, bottom),     # 工作区（排除任务栏）
            "is_primary": bool                            # 是否主显示器
        }
    """
    try:
        # 获取窗口所在的显示器（MONITOR_DEFAULTTONEAREST = 2）
        hmonitor = _user32.MonitorFromWindow(hwnd, 2)
        
        if not hmonitor:
            logger.warning("[WindowBounds] MonitorFromWindow 返回空")
            return None
        
        # 获取显示器信息
        monitor_info = MONITORINFO()
        monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
        
        if not _user32.GetMonitorInfoW(hmonitor, ctypes.byref(monitor_info)):
            logger.warning("[WindowBounds] GetMonitorInfoW 失败")
            return None
        
        return {
            "monitor_rect": (
                monitor_info.rcMonitor.left,
                monitor_info.rcMonitor.top,
                monitor_info.rcMonitor.right,
                monitor_info.rcMonitor.bottom,
            ),
            "work_rect": (
                monitor_info.rcWork.left,
                monitor_info.rcWork.top,
                monitor_info.rcWork.right,
                monitor_info.rcWork.bottom,
            ),
            "is_primary": bool(monitor_info.dwFlags & 1),  # MONITORINFOF_PRIMARY = 1
        }
    except Exception as e:
        logger.error(f"[WindowBounds] 获取显示器信息失败: {e}")
        return None


def get_window_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """
    获取窗口的当前位置和尺寸
    
    Args:
        hwnd: 窗口句柄
        
    Returns:
        Tuple[int, int, int, int]: (left, top, right, bottom)
    """
    try:
        rect = RECT()
        
        if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return (rect.left, rect.top, rect.right, rect.bottom)
        
        return None
    except Exception as e:
        logger.error(f"[WindowBounds] 获取窗口矩形失败: {e}")
        return None


def check_and_fix_window_bounds(hwnd: int, dpi_scale: float = 1.0) -> bool:
    """
    检查窗口是否超出当前显示器边界，并自动调整
    
    这是核心修复函数，会：
    1. 获取窗口当前位置
    2. 获取窗口所在显示器的工作区
    3. 检查窗口是否超出边界
    4. 自动调整窗口位置和尺寸
    
    注意：此函数必须在主 UI 线程中调用！
    
    Args:
        hwnd: 窗口句柄
        dpi_scale: DPI 缩放因子
        
    Returns:
        bool: 是否进行了调整
    """
    try:
        # 获取窗口当前位置
        window_rect = get_window_rect(hwnd)
        if not window_rect:
            logger.warning("[WindowBounds] 无法获取窗口位置")
            return False
        
        win_left, win_top, win_right, win_bottom = window_rect
        win_width = win_right - win_left
        win_height = win_bottom - win_top
        
        logger.debug(f"[WindowBounds] 窗口当前位置: ({win_left}, {win_top}, {win_right}, {win_bottom})")
        logger.debug(f"[WindowBounds] 窗口尺寸: {win_width}x{win_height}")
        
        # 获取窗口所在显示器信息
        monitor_info = get_monitor_info(hwnd)
        if not monitor_info:
            logger.warning("[WindowBounds] 无法获取显示器信息，跳过边界检查")
            return False
        
        work_rect = monitor_info["work_rect"]
        work_left, work_top, work_right, work_bottom = work_rect
        work_width = work_right - work_left
        work_height = work_bottom - work_top
        
        logger.debug(f"[WindowBounds] 工作区: ({work_left}, {work_top}, {work_right}, {work_bottom})")
        logger.debug(f"[WindowBounds] 工作区尺寸: {work_width}x{work_height}")
        
        # 检查窗口是否超出工作区
        needs_fix = False
        new_left = win_left
        new_top = win_top
        new_width = win_width
        new_height = win_height
        
        # 检查宽度是否超出
        if win_width > work_width:
            new_width = work_width
            needs_fix = True
            logger.info(f"[WindowBounds] 窗口宽度超出工作区，调整: {win_width} -> {new_width}")
        
        # 检查高度是否超出
        if win_height > work_height:
            new_height = work_height
            needs_fix = True
            logger.info(f"[WindowBounds] 窗口高度超出工作区，调整: {win_height} -> {new_height}")
        
        # 检查左边界
        if win_left < work_left:
            new_left = work_left
            needs_fix = True
            logger.info(f"[WindowBounds] 窗口左边界超出，调整: {win_left} -> {new_left}")
        
        # 检查右边界
        if win_right > work_right:
            new_left = work_right - new_width
            needs_fix = True
            logger.info(f"[WindowBounds] 窗口右边界超出，调整左边界: {win_left} -> {new_left}")
        
        # 检查上边界
        if win_top < work_top:
            new_top = work_top
            needs_fix = True
            logger.info(f"[WindowBounds] 窗口上边界超出，调整: {win_top} -> {new_top}")
        
        # 检查下边界
        if win_bottom > work_bottom:
            new_top = work_bottom - new_height
            needs_fix = True
            logger.info(f"[WindowBounds] 窗口下边界超出，调整上边界: {win_top} -> {new_top}")
        
        # 如果需要调整，执行调整
        if needs_fix:
            # SWP_NOZORDER = 0x0004, SWP_SHOWWINDOW = 0x0040
            flags = 0x0044
            _user32.SetWindowPos(hwnd, None, new_left, new_top, new_width, new_height, flags)
            
            logger.info(f"[WindowBounds] 窗口位置已调整: ({new_left}, {new_top}, {new_width}x{new_height})")
            return True
        
        logger.debug("[WindowBounds] 窗口位置正常，无需调整")
        return False
        
    except Exception as e:
        logger.error(f"[WindowBounds] 边界检查和调整失败: {e}", exc_info=True)
        return False


def reset_window_to_center(hwnd: int, default_width: int = 1680, default_height: int = 1080) -> bool:
    """
    将窗口重置到当前显示器中心，并恢复默认尺寸
    
    用于用户手动恢复窗口位置。
    同时重置窗口大小，解决窗口尺寸大于目标屏幕的问题。
    
    注意：此函数必须在主 UI 线程中调用！
    
    Args:
        hwnd: 窗口句柄
        default_width: 默认窗口宽度
        default_height: 默认窗口高度
        
    Returns:
        bool: 是否成功
    """
    try:
        # 获取窗口所在显示器信息
        monitor_info = get_monitor_info(hwnd)
        if not monitor_info:
            logger.warning("[WindowBounds] 无法获取显示器信息")
            return False
        
        work_rect = monitor_info["work_rect"]
        work_left, work_top, work_right, work_bottom = work_rect
        work_width = work_right - work_left
        work_height = work_bottom - work_top
        
        # 确保默认尺寸不超过工作区
        final_width = min(default_width, work_width)
        final_height = min(default_height, work_height)
        
        # 计算居中位置
        new_left = work_left + (work_width - final_width) // 2
        new_top = work_top + (work_height - final_height) // 2
        
        # 确保窗口不会超出边界
        new_left = max(work_left, min(new_left, work_right - final_width))
        new_top = max(work_top, min(new_top, work_bottom - final_height))
        
        # SWP_NOZORDER = 0x0004, SWP_SHOWWINDOW = 0x0040
        flags = 0x0044
        _user32.SetWindowPos(hwnd, None, new_left, new_top, final_width, final_height, flags)
        
        logger.info(f"[WindowBounds] 窗口已重置: 位置({new_left}, {new_top}), 尺寸{final_width}x{final_height}")
        return True
        
    except Exception as e:
        logger.error(f"[WindowBounds] 重置窗口位置失败: {e}", exc_info=True)
        return False


def find_window_by_title(title: str, max_retries: int = 10, retry_interval: float = 0.2) -> Optional[int]:
    """
    通过窗口标题查找窗口句柄（带重试机制）
    
    Args:
        title: 窗口标题
        max_retries: 最大重试次数
        retry_interval: 重试间隔（秒）
        
    Returns:
        Optional[int]: 窗口句柄，如果未找到返回 None
    """
    try:
        import time
        
        for attempt in range(max_retries):
            hwnd = _user32.FindWindowW(None, title)
            
            if hwnd and hwnd != 0:
                logger.debug(f"[WindowBounds] 找到窗口 '{title}': {hwnd} (尝试 {attempt + 1}/{max_retries})")
                return hwnd
            
            time.sleep(retry_interval)
        
        logger.warning(f"[WindowBounds] 未找到窗口 '{title}' (尝试 {max_retries} 次)")
        return None
        
    except Exception as e:
        logger.error(f"[WindowBounds] 查找窗口失败: {e}")
        return None


# ============================================================================
# 最大化约束到「工作区」（排除任务栏）
#
# 背景：本程序使用 frameless=True，pywebview 把窗口样式改成 WS_POPUP。
# 对于 WS_POPUP 窗口，Windows 默认的 WM_GETMINMAXINFO 会把「最大化尺寸」
# 设为整块显示器（rcMonitor），导致 SW_MAXIMIZE / window.maximize()
# 把窗口放大到覆盖任务栏的全屏——这不是正常的「最大化」（正常最大化应尊重
# 工作区 rcWork，给任务栏留位置），也不是「全屏」（不会隐藏应用顶栏）。
#
# 修复：子类化窗口过程，在 WM_GETMINMAXINFO 里把最大化矩形改写为当前显示器
# 的工作区。这样所有 maximize 路径（启动、reset_window_state 的 SW_MAXIMIZE、
# TitleBar 的 OS maximize 兜底）都会尊重任务栏。
# ============================================================================

_WM_GETMINMAXINFO = 0x0024
_WM_SIZE = 0x0005
_SIZE_MAXIMIZED = 2
_GWLP_WNDPROC = -4
_SWP_NOZORDER = 0x0004


class _MINMAXINFO(ctypes.Structure):
    """Windows MINMAXINFO 结构体（lpram of WM_GETMINMAXINFO）"""
    _fields_ = [
        ("ptReserved", wintypes.POINT),
        ("ptMaxSize", wintypes.POINT),       # 最大化时的尺寸
        ("ptMaxPosition", wintypes.POINT),   # 最大化时的位置
        ("ptMinTrackSize", wintypes.POINT),
        ("ptMaxTrackSize", wintypes.POINT),
    ]


# WNDPROC 签名（x64：LRESULT 为 64 位有符号）
_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)

# 关键修复：SetWindowLongPtrW 的第 3 个参数是「新窗口过程指针」。
# 上面把 argtype 设成了 LPARAM(整数)，传入 WINFUNCTYPE 回调实例会报
# "'WinFunctionType' object cannot be interpreted as an integer"，
# 使钩子静默安装失败 → 最大化仍盖住任务栏。改用 _WNDPROC 原型作为 argtype，
# ctypes 才能把回调实例正确转换为其地址；返回的原过程地址仍按 LPARAM(int)。
_user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, _WNDPROC]
_user32.SetWindowLongPtrW.restype = wintypes.LPARAM

# 模块级引用，避免回调被 GC 回收
_workarea_wndproc = None
# 已安装的窗口 -> 其原始窗口过程（LPARAM）。按 hwnd 各自保存，
# 避免「为第二个不同 hwnd 安装时覆盖全局 _orig_wndproc」导致第一个窗口
# 的消息被转发到错误窗口的过程（钩子链错乱 / 崩溃）。
_installed: dict = {}
# WM_SIZE 兜底钳制时的防重入标志
_clamping = False


def _workarea_wndproc_impl(hwnd, msg, wparam, lparam):
    """窗口过程钩子：改写最大化尺寸到工作区；其余消息转发给原过程"""
    global _clamping
    try: # 尽量小的影响面：仅拦截最大化尺寸计算与最大化后的兜底钳制
        if msg == _WM_GETMINMAXINFO and lparam:
            mmi = ctypes.cast(lparam, ctypes.POINTER(_MINMAXINFO)).contents
            info = get_monitor_info(hwnd)
            if info:
                wl, wt, wr, wb = info["work_rect"]
                mmi.ptMaxSize.x = wr - wl
                mmi.ptMaxSize.y = wb - wt
                mmi.ptMaxPosition.x = wl
                mmi.ptMaxPosition.y = wt
                return 0
        elif msg == _WM_SIZE and wparam == _SIZE_MAXIMIZED and not _clamping:
            # 兜底：某些最大化路径（如从已保存的"整屏最大化"位置恢复、点击任务栏
            # 还原、或直接 SetWindowPlacement）不经过 WM_GETMINMAXINFO，会把窗口放到
            # 整块显示器（rcMonitor）盖住任务栏。这里在最大化生效后再把窗口钳制回工作区。
            info = get_monitor_info(hwnd)
            if info:
                wl, wt, wr, wb = info["work_rect"]
                cur = get_window_rect(hwnd)
                if cur and (cur[0] != wl or cur[1] != wt or cur[2] != wr or cur[3] != wb):
                    _clamping = True
                    try:
                        _user32.SetWindowPos(hwnd, None, wl, wt, wr - wl, wb - wt, _SWP_NOZORDER)
                    finally:
                        _clamping = False
                    # 吞掉这条原始 WM_SIZE；上面的 SetWindowPos 已同步触发一条
                    # 工作区尺寸的 WM_SIZE 并被转发，前端据此正确缩放，避免循环。
                    return 0
    except Exception as exc:
        logger.debug(f"[WindowBounds] 窗口钩子异常（忽略）: {exc}")

    orig = _installed.get(hwnd)
    if orig is None:
        return 0
    return _user32.CallWindowProcW(orig, hwnd, msg, wparam, lparam)


def install_maximize_workarea_hook(hwnd: int) -> bool:
    """
    为窗口安装「最大化约束到工作区」的钩子（幂等，按 hwnd 去重）。

    必须在窗口创建后调用。子类化本身在任意线程调用都安全，
    但窗口消息仍在窗口线程上派发。

    Args:
        hwnd: 窗口句柄

    Returns:
        bool: 是否成功安装（已安装过同 hwnd 也返回 True）
    """
    global _workarea_wndproc
    try:
        if not hwnd or hwnd == 0:
            logger.debug("[WindowBounds] 钩子：无效 hwnd，跳过")
            return False

        # 同一 hwnd 已安装：直接返回（幂等）
        if hwnd in _installed:
            return True

        if _workarea_wndproc is None:
            _workarea_wndproc = _WNDPROC(_workarea_wndproc_impl)

        prev = _user32.SetWindowLongPtrW(hwnd, _GWLP_WNDPROC, _workarea_wndproc)
        if not prev:
            logger.warning("[WindowBounds] 钩子：SetWindowLongPtrW 返回 0（可能失败）")
            return False

        _installed[hwnd] = prev
        logger.info(f"[WindowBounds] 已安装最大化工作区钩子 (hwnd={hwnd})")
        return True
    except Exception as e:
        logger.warning(f"[WindowBounds] 安装最大化工作区钩子失败: {e}")
        return False
