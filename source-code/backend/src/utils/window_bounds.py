"""
窗口边界检查和自动调整工具
用于多显示器环境下防止窗口移出可视区域

注意：所有函数必须在主 UI 线程中调用，不能在后台线程中调用。
"""

import ctypes
import ctypes.wintypes as wintypes
import threading
import time
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
# GetAsyncKeyState：判断左键是否仍按下（缩放轮询的松手判据）
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short

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

# IsZoomed / IsIconic（判断窗口是否最大化 / 最小化，供缩放命中判定使用）
_user32.IsZoomed.argtypes = [wintypes.HWND]
_user32.IsZoomed.restype = wintypes.BOOL
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL

# GetDpiForWindow（Win10 1607+）。老系统上没有该导出，调用前用 getattr 兜底，
# 所以这里只设置「如果存在」的原型。
if hasattr(_user32, "GetDpiForWindow"):
    _user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    _user32.GetDpiForWindow.restype = wintypes.UINT

# IsWindow（校验句柄是否仍然有效）
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.restype = wintypes.BOOL
# GetWindowThreadProcessId（判断窗口属于哪个进程）
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
# GetClassNameW
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int
# IsWindowVisible
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL

# WNDENUMPROC 回调原型。
# **必须显式声明**：64 位下若不设 argtypes，ctypes 会把回调参数按默认 int 截断，
# EnumWindows 的回调会静默异常并立刻返回 FALSE —— 表现为「一个窗口都没枚举到」。
# 上一版诊断脚本就是这样误判成「WebView2 用了 Composition 模式，没有子窗口」。
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL
_user32.EnumChildWindows.argtypes = [wintypes.HWND, _WNDENUMPROC, wintypes.LPARAM]
_user32.EnumChildWindows.restype = wintypes.BOOL

_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GetCurrentProcessId.argtypes = []
_kernel32.GetCurrentProcessId.restype = wintypes.DWORD


# ============================================================================
# 权威窗口句柄解析（本轮关键修复）
#
# ## 踩到的根因
#
# 全项目原先有 17 处靠 `FindWindowW(None, "ComfyNexus")` 取窗口句柄，
# 这个用法在 Windows 11 上是**错的**，而且错得非常隐蔽：
#
#   Win11 的「文件资源管理器标签化」会在 explorer.exe 里为每个顶层窗口创建一个
#   伴生窗口 `Windows.Internal.Shell.TabProxyWindow`，它的**标题与目标窗口相同**。
#   `FindWindowW(None, "ComfyNexus")` 只按标题匹配顶层窗口，枚举顺序上
#   TabProxyWindow 先命中，于是返回的是 explorer.exe 的窗口：
#
#     实测（2026-10-25）：
#       FindWindowW(None,'ComfyNexus') = 3738060
#         class = Windows.Internal.Shell.TabProxyWindow
#         pid   = 4288 (explorer.exe)        ← 不是本进程！
#         rect  = (0,0,1920,935)  client=(1906,921)   ← 带 7px 边框
#       真实窗口 = 4853078
#         class = WindowsForms10.Window.8.app.0.15a303f_r3_ad1
#         pid   = 15432 (ComfyNexus.exe)
#         STYLE = 0x17010000  ← **没有 WS_THICKFRAME**
#         rect  = (0,0,1920,1080)  client=(1920,1080)  ← 无边框
#
#   后果链条：
#     1. `ensure_frameless_style()` 与钩子都作用在 explorer 的窗口上；
#        跨进程 `SetWindowLongPtrW` 被 UIPI 拒绝 → 日志 `SetWindowLongPtrW 返回 0`；
#     2. 真实窗口从未被施加 `WS_THICKFRAME`，而原生四角缩放**完全依赖**这个样式位；
#     3. 于是「拖动四角改变大小」彻底失效 —— 正是用户反馈的现象。
#
#   为什么以前「看起来是好的」：旧机器/旧系统没有 TabProxyWindow，
#   FindWindowW 恰好命中真实窗口。Win11 有了标签页代理后才暴露。
#
# ## 修复策略
#
# 不再信任「按标题猜窗口」，改为**按进程 ID + 窗口类名**精确锁定本进程的
# WinForms 窗体。解析顺序：
#   1. pywebview 的 `window.native.Handle`（最权威，直接就是 BrowserForm 句柄）
#   2. 枚举本进程（GetCurrentProcessId）的顶层窗口，取 class 以 WindowsForms10 开头者
#   3. `EnumChildWindows` 兜底（窗体被重新 parent 的情况）
#   4. 最后才退回 FindWindowW，但**必须校验 pid 属于本进程**，否则弃用
# ============================================================================

# 解析结果的缓存：hwnd 在应用生命周期内不变，缓存可避免每次 API 调用都枚举。
_cached_hwnd = 0


def _pid_of(hwnd: int) -> int:
    """取窗口所属进程 ID。"""
    try:
        pid = wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def _class_of(hwnd: int) -> str:
    """取窗口类名。"""
    try:
        buf = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return ""


def _is_own_window(hwnd: int) -> bool:
    """句柄是否有效且属于本进程。"""
    if not hwnd:
        return False
    try:
        if not _user32.IsWindow(hwnd):
            return False
        return _pid_of(hwnd) == int(_kernel32.GetCurrentProcessId())
    except Exception:
        return False


def _to_int_handle(handle) -> int:
    """把 pythonnet 的 `System.IntPtr` / 原生 int 统一转成 Python int。

    为什么需要它：`window.native` 是 WinForms Form，`.Handle` 返回的是
    pythonnet 的 `System.IntPtr`，不是一个干净的 int：
      - `int(handle)` 在部分 pythonnet 版本上抛 TypeError；
      - `handle.ToInt64()` 更可靠，但它不是标准 Python 对象的方法。
    这里按「先试 ToInt64 → 再试 int → 最后试 .value」逐级兜底，
    任何一步成功即返回，全部失败返回 0（调用方会继续用枚举兜底）。
    """
    if handle is None:
        return 0
    # 1) pythonnet IntPtr.ToInt64()
    try:
        to_int64 = getattr(handle, "ToInt64", None)
        if callable(to_int64):
            return int(to_int64())
    except Exception:
        pass
    # 2) 直接 int()
    try:
        return int(handle)
    except Exception:
        pass
    # 3) .value（某些包装类型）
    try:
        return int(handle.value)
    except Exception:
        pass
    return 0


def _find_own_top_level_window() -> int:
    """枚举本进程的顶层窗口，返回最可能是主窗体的那个句柄。

    判据：class 以 `WindowsForms10` 开头 + 可见 + 面积最大。
    面积最大是为了在多窗口场景（比如浮窗）里挑出主窗体。
    """
    pid = int(_kernel32.GetCurrentProcessId())
    candidates = []

    @_WNDENUMPROC
    def _cb(hwnd, _lparam):
        try:
            if _pid_of(hwnd) != pid:
                return True
            cls = _class_of(hwnd)
            if not cls.startswith("WindowsForms10"):
                return True
            if not _user32.IsWindowVisible(hwnd):
                return True
            rect = get_window_rect(hwnd)
            area = 0
            if rect:
                area = max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])
            candidates.append((area, hwnd, cls))
        except Exception:
            pass
        return True

    try:
        _user32.EnumWindows(_cb, 0)
    except Exception as exc:
        logger.debug(f"[WindowBounds] 枚举本进程窗口失败: {exc}")
        return 0

    if not candidates:
        return 0
    candidates.sort(key=lambda item: item[0], reverse=True)
    return int(candidates[0][1])


def resolve_app_hwnd(window=None, refresh: bool = False) -> int:
    """取**本应用真实主窗口**的句柄（权威实现）。

    绝对不要再用裸的 `FindWindowW(None, "ComfyNexus")` —— 理由见本段上方注释。

    Args:
        window: pywebview 的 Window 对象（可选）。传入时优先用它的 native.Handle，
                这是最权威的来源，且不依赖任何窗口枚举。
        refresh: 忽略缓存，强制重新解析。

    Returns:
        窗口句柄；解析失败返回 0。
    """
    global _cached_hwnd

    # 1) pywebview 原生句柄（最可靠）
    if window is not None:
        try:
            native = getattr(window, "native", None)
            if native is not None:
                handle = getattr(native, "Handle", None)
                hwnd = _to_int_handle(handle)
                if hwnd and _is_own_window(hwnd):
                    _cached_hwnd = hwnd
                    return hwnd
        except Exception as exc:
            logger.debug(f"[WindowBounds] 读取 window.native.Handle 失败: {exc}")

    # 2) 缓存（仍有效则直接用）
    if not refresh and _cached_hwnd and _is_own_window(_cached_hwnd):
        return _cached_hwnd

    # 3) 按进程 + 类名枚举
    hwnd = _find_own_top_level_window()
    if hwnd:
        _cached_hwnd = hwnd
        logger.debug(f"[WindowBounds] 解析到主窗口 hwnd={hwnd}（按进程枚举）")
        return hwnd

    # 4) 兜底：FindWindowW，但必须校验属于本进程
    try:
        fallback = _user32.FindWindowW(None, "ComfyNexus")
        if _is_own_window(fallback):
            _cached_hwnd = int(fallback)
            logger.debug(f"[WindowBounds] 解析到主窗口 hwnd={fallback}（FindWindowW 兜底）")
            return int(fallback)
        if fallback:
            logger.warning(
                f"[WindowBounds] FindWindowW 命中的窗口 {fallback} 不属于本进程"
                f"（pid={_pid_of(fallback)}, class={_class_of(fallback)!r}），已丢弃。"
                f"这是 Win11 TabProxyWindow 干扰，属于预期情况。"
            )
    except Exception as exc:
        logger.debug(f"[WindowBounds] FindWindowW 兜底失败: {exc}")

    return 0


def invalidate_hwnd_cache():
    """清空句柄缓存（窗口重建 / 退出时调用）。"""
    global _cached_hwnd
    _cached_hwnd = 0


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
_SWP_NOREDRAW = 0x0008

# ----------------------------------------------------------------------------
# 四角原生缩放（WM_NCHITTEST）
#
# 背景：窗口是 frameless(WS_POPUP)。原先由前端 JS 监听 mousemove，逐帧跨桥调用
# resize+move。桥接调用是异步线程，且 SetWindowPos 跨线程投递到 UI 线程，
# 大量调用会互相覆盖：常见表现是「窗口跟着鼠标平移、尺寸不变」，或者是
# 拖动过程卡顿/假死。
#
# 修复：子类化窗口过程，在 WM_NCHITTEST 里只对「四个角」返回对应的缩放命中码，
# 其余位置返回 HTCLIENT。这样拖动由 Windows 自己的模态缩放缓动环完成
# （UI 线程内同步处理，帧率由系统决定），前端不再逐帧干预。
# ----------------------------------------------------------------------------
_WM_NCHITTEST = 0x0084
_WM_NCCALCSIZE = 0x0083
_HTCLIENT = 1
_HTTOPLEFT = 13
_HTTOPRIGHT = 14
_HTBOTTOMLEFT = 16
_HTBOTTOMRIGHT = 17

# 命中缩放命中码 -> (x 方向符号, y 方向符号)，用于「从左上角拖」时反转增量
HIT_TEST_TO_CORNER = {
    _HTTOPLEFT: "top-left",
    _HTTOPRIGHT: "top-right",
    _HTBOTTOMLEFT: "bottom-left",
    _HTBOTTOMRIGHT: "bottom-right",
}

# 角部命中区域边长（逻辑像素）。只有这个正方形内的点才触发缩放，
# 目的正是「只在四个角拖动，四边不响应」。
CORNER_HIT_SIZE = 12

# 由 main.py 在创建窗口后写入（物理像素），供 WM_GETMINMAXINFO 使用。
# 为 None 时不改写最小跟踪尺寸，交给 WinForms 的 MinimumSize 处理。
_min_track_size = None

# 全屏豁免标志（按 hwnd 记录）。
#
# 背景：本模块的钩子把 ptMaxSize 改写为「工作区」，并在 WM_SIZE(MAXIMIZED)
# 里把窗口钳制回工作区 —— 这是为了「最大化时保留任务栏」。
# 但 pywebview 的 toggle_fullscreen() 实现是：
#     FormBorderStyle = None; Bounds = Screen.Bounds; WindowState = Maximized;
#     SetWindowPos(整屏矩形)
# 也就是说它内部**也是先 Maximized**。于是钩子把这次最大化按「普通最大化」
# 改写/钳制到工作区，全屏因此退化成最大化 —— 任务栏依然可见，
# 表现为「点全屏只是放大了一点，任务栏还在」。
#
# 修复：进全屏前给该 hwnd 置豁免位，钩子见到豁免位就完全不管最大化尺寸；
# 退出全屏后清豁免位，恢复「最大化尊重工作区」的正常行为。
_fullscreen_hwnds: set = set()


def set_fullscreen_override(hwnd: int, enabled: bool) -> None:
    """设置「全屏豁免」：为 True 时钩子不再把最大化矩形改写到工作区。

    这是全屏与最大化的根本区别所在：
      - 最大化：占满工作区（rcWork），保留任务栏
      - 全屏：  占满整块显示器（rcMonitor），覆盖任务栏
    """
    try:
        if not hwnd:
            return
        if enabled:
            _fullscreen_hwnds.add(int(hwnd))
        else:
            _fullscreen_hwnds.discard(int(hwnd))
        logger.debug(f"[WindowBounds] 全屏豁免 -> {enabled} (hwnd={hwnd})")
    except Exception as exc:
        logger.debug(f"[WindowBounds] 设置全屏豁免失败（忽略）: {exc}")


def is_fullscreen_override(hwnd: int) -> bool:
    try:
        return int(hwnd) in _fullscreen_hwnds
    except Exception:
        return False


def clamp_rect_to_workarea(hwnd: int, x: int, y: int, width: int, height: int):
    """把「位置 + 尺寸」钳制到显示器工作区内，返回 (x, y, w, h)。

    为什么需要它：窗口高 1080 而工作区只有 1032 时，
    居中计算会得到 y = (1080-1080)//2 = 0，看起来正常；
    但一旦尺寸等于屏幕高度，窗口顶边就会跑到 y=-48（工作区上边界之上），
    而窗口的**左上/右上两个角恰好落在屏幕外**——鼠标根本移不到那里，
    用户感知就是「拖角完全没反应」。
    实测证据：还原后窗口矩形 (0,-48)-(1680,1032)，四角命中测试只能在
    屏幕内取点，上两个角永远测不到，等同失效。

    规则：尺寸先按工作区封顶，再把位置夹到 [work_left, work_right - w]。
    """
    info = get_monitor_info(hwnd)
    if not info:
        return x, y, width, height
    wl, wt, wr, wb = info["work_rect"]
    work_w = max(1, wr - wl)
    work_h = max(1, wb - wt)

    width = max(1, min(int(width), work_w))
    height = max(1, min(int(height), work_h))
    x = max(wl, min(int(x), wr - width))
    y = max(wt, min(int(y), wb - height))
    return x, y, width, height


def apply_window_rect(hwnd: int, x: int, y: int, width: int, height: int,
                      clamp: bool = True) -> bool:
    """把窗口摆到指定位置和尺寸（物理像素），默认按工作区钳制。"""
    try:
        if clamp:
            x, y, width, height = clamp_rect_to_workarea(hwnd, x, y, width, height)
        ok = _user32.SetWindowPos(
            hwnd, None, int(x), int(y), int(width), int(height),
            _SWP_NOZORDER | _SWP_FRAMECHANGED,
        )
        logger.debug(
            f"[WindowBounds] 应用窗口矩形 ({x},{y}) {width}x{height} -> {bool(ok)}"
        )
        return bool(ok)
    except Exception as exc:
        logger.warning(f"[WindowBounds] 应用窗口矩形失败: {exc}")
        return False


def set_min_track_size(width: int, height: int) -> None:
    """设置窗口的最小跟踪尺寸（物理像素），供原生缩放缓动环使用。"""
    global _min_track_size
    _min_track_size = (max(1, int(width)), max(1, int(height)))


# =============== 四角拖动缩放（轮询实现） ===============
#
# 为什么不用 WM_NCLBUTTONDOWN + 系统模态环（这是被实测推翻的方案）：
#
#   原方案：前端 mousedown → 后端 SendMessage(WM_NCLBUTTONDOWN, HTTOPLEFT)。
#   实测结果：模态环**确实进入了**（SendMessage 阻塞到鼠标松开，3s 超时证明），
#   但窗口尺寸**完全不动**。原因是鼠标捕获被 WebView2 抢走了 ——
#   WebView2 是子窗口，用户按下鼠标时捕获归它，而 ReleaseCapture() 只能在
#   **调用线程**释放捕获，后端工作线程调用它等于什么都没释放。
#   于是模态环收不到 WM_MOUSEMOVE，尺寸永远不变 —— 用户感知就是"拖不动"。
#
#   对照实验证明：往主窗口**直接投递** WM_MOUSEMOVE，模态环会响应并改尺寸。
#   也就是说模态环本身没坏，是鼠标消息到不了它手上。
#
#   结论：任何依赖"鼠标消息路由到主窗口"的方案在 WebView2 下都不可靠。
#   改用**轮询光标全局坐标**（GetCursorPos）+ SetWindowPos。
#   优势：
#     - GetCursorPos 是全局的，不受捕获归属影响，任何线程都能读到；
#     - 每帧只做一次 SetWindowPos，是真正的窗口操作而非消息排队；
#     - 松手判定用 GetAsyncKeyState(VK_LBUTTON)，同样不受捕获影响；
#     - 全程可不依赖前端 IPC，前端只在 mousedown 时调一次。

_resize_lock = threading.Lock()
_resize_active = False
# 停止信号：前端 mouseup 时置位，轮询循环据此退出。
#
# **为什么不能只靠 GetAsyncKeyState(VK_LBUTTON) 判断松手**（本轮实测的坑）：
#   - 它读的是「物理按键」状态。自动化/远程输入（CDP 合成事件、触摸板轻点、
#     某些远程桌面）下物理键从未真的按下，读数恒为"已松开"，
#     轮询循环会**第 0 帧就退出**，表现为"完全拖不动"。
#   - 实测日志：`开始 bottom-right ... 左键已松开，结束（0 帧）`。
#   - 而且用户点得快时（<10ms 松开）也会漏判。
# 因此改为：**前端 mouseup 主动置停止标志**为权威依据，
# GetAsyncKeyState 只作为辅助（连续多帧为松开才认定，避免瞬时抖动）。
_resize_stop = threading.Event()

_CORNER_CURSORS = {
    "top-left": "nwse", "top-right": "nesw",
    "bottom-left": "nesw", "bottom-right": "nwse",
}


def _cursor_pos():
    """读全局光标位置。

    **必须用本模块顶部的 `POINT` 结构**，因为本文件后面已经声明了
        _user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    ctypes 会按该签名做严格类型校验：
      - 传 wintypes.POINT  → TypeError: expected LP_POINT instance
                             instead of pointer to POINT
      - 传自定义 _POINT    → TypeError: expected LP_POINT instance
                             instead of pointer to _POINT
    两种错法本轮都实际踩过。只有模块内这个 POINT 才对得上。
    """
    pt = POINT()
    if _user32.GetCursorPos(ctypes.byref(pt)):
        return int(pt.x), int(pt.y)
    return None


def _left_button_down() -> bool:
    """左键当前是否按下。GetAsyncKeyState 最高位 = 当前按下。"""
    try:
        return bool(_user32.GetAsyncKeyState(0x01) & 0x8000)
    except Exception:
        return False


def is_resize_running() -> bool:
    """是否正在轮询缩放中（供外部判断，避免重复启动）。"""
    return _resize_active


def stop_polling_resize() -> bool:
    """通知轮询缩放结束（由前端 mouseup / mouseleave 调用）。

    这是**权威的结束信号**。相比读 GetAsyncKeyState，它不依赖物理按键状态，
    因此在触摸板轻点、远程输入、自动化派发等场景下同样可靠。
    """
    try:
        if not _resize_active:
            return False
        _resize_stop.set()
        logger.info("[PollResize] 已请求停止")
        return True
    except Exception as exc:
        logger.debug(f"[PollResize] 请求停止失败（忽略）: {exc}")
        return False


def start_polling_resize(hwnd: int, corner: str,
                         min_width: int = 1024, min_height: int = 640,
                         on_finish=None) -> bool:
    """开始四角拖动缩放（轮询版）。

    在独立线程里循环：
      1. 读光标全局坐标；
      2. 按 corner 反算新的窗口矩形（对边固定）；
      3. 钳制到最小尺寸与工作区；
      4. SetWindowPos。
    直到左键松开或线程被取消。

    为什么对边固定：拖左上角时，右下角必须原地不动，否则窗口会"跟着鼠标平移"。
    这正是原前端逐帧方案出问题的表现，这里用"反算矩形"从根本上避免。

    Args:
        hwnd: 目标窗口句柄
        corner: top-left / top-right / bottom-left / bottom-right
        min_width / min_height: 最小尺寸（物理像素）
        on_finish: 结束回调（在缩放线程里调用），用于写回设置

    Returns:
        True 表示已启动；False 表示已有缩放在进行或参数非法。
    """
    global _resize_active

    if corner not in _CORNER_CURSORS:
        logger.warning(f"[PollResize] 非法角: {corner}")
        return False

    with _resize_lock:
        if _resize_active:
            logger.info("[PollResize] 已有缩放在进行，忽略本次")
            return False
        _resize_active = True
    # 每次开始都要清掉上一次残留的停止信号
    _resize_stop.clear()

    def _worker():
        global _resize_active
        try:
            rect = get_window_rect(hwnd)
            if not rect:
                logger.warning("[PollResize] 取窗口矩形失败")
                return
            left, top, right, bottom = rect

            start_x, start_y = left, top
            start_w, start_h = right - left, bottom - top

            info = get_monitor_info(hwnd)
            if info:
                wl, wt, wr, wb = info["work_rect"]
                ml, mt, mr, mb = info.get("monitor_rect") or (wl, wt, wr, wb)
            else:
                wl, wt, wr, wb = 0, 0, start_w + start_x, start_h + start_y
                ml, mt, mr, mb = wl, wt, wr, wb

            work_left, work_top = wl, wt
            # **钳到工作区（排除任务栏），不是整块显示器**。
            #
            # 曾经这里用显示器全矩形 mr/mb，注释理由是"否则右下角拖到任务栏会被卡住"。
            # 但那会引入更严重的问题（本轮实测踩到）：
            #   拖成 1680x1080（屏幕高 1080）后，能挡住任务栏，
            #   底部两个热区落在 y=1071 —— **正好在任务栏下面，鼠标点不到**。
            #   于是"拖过一次到底之后，下两个角就再也拖不动了"，
            #   用户感受就是"缩放时好时坏"。
            # 而且保存下来的 1080 在还原时又会被工作区钳成 1032，
            # 出现"拖出来 1080、还原变 1032"的尺寸跳变。
            #
            # 钳到工作区的三条好处：
            #   1. 窗口永远不被任务栏遮挡，四角热区始终可点；
            #   2. 拖动结果 == 保存值 == 还原值，口径完全一致；
            #   3. 拖到底就停住，和绝大多数 Windows 程序的手感一致
            #      （这不是"卡住"，是正常的边界行为）。
            work_right, work_bottom = wr, wb

            min_w = max(1, int(min_width))
            min_h = max(1, int(min_height))

            cursor0 = _cursor_pos()
            if cursor0 is None:
                logger.warning("[PollResize] 读光标失败")
                return

            # 记录按下时的光标位置，用于计算位移量。
            # 不能直接用"光标 == 窗口角"，因为用户可能点在热区中间而非精确角点，
            # 那样窗口会瞬间跳一段。用位移量最稳。
            base_x, base_y = cursor0
            logger.info(
                f"[PollResize] 开始 {corner} 窗口=({left},{top}) "
                f"{start_w}x{start_h} 基准光标=({base_x},{base_y})"
            )

            last = (left, top, start_w, start_h)
            frames = 0
            started_at = time.time()

            # ---- 松手判据（本轮踩坑后的定稿） ----
            #
            # 权威依据是**前端 stopNativeResize 置的 _resize_stop 事件**。
            # GetAsyncKeyState 只能当兜底，而且必须满足一个前提：
            #   **本次拖动过程中确实观察到过「按下」**。
            #
            # 为什么加这个前提（实测日志实证）：
            #   在触摸板轻点、远程输入、CDP 合成事件等场景下，物理按键从未真的按下，
            #   GetAsyncKeyState 从第 0 帧起就报「已松开」。若不加前提，
            #   计数 20 帧（≈160ms）后就把线程杀了，而用户此刻还没开始移动鼠标，
            #   表现为「完全拖不动」。日志：`按键状态显示已松开（0 帧）`。
            #   真鼠标拖动的场景下一定观测得到按下，所以加前提不影响正常手感。
            seen_down = False
            released_frames = 0
            # 硬性生存期上限：防止前端 stop 信号因为页面崩溃/刷新而永久丢失，
            # 导致轮询线程常驻空转。
            _MAX_LIFETIME = 60.0

            while True:
                if _resize_stop.is_set():
                    logger.info(f"[PollResize] 收到前端结束信号（{frames} 帧）")
                    break

                if time.time() - started_at > _MAX_LIFETIME:
                    logger.info(f"[PollResize] 超过最长生存期，强制结束（{frames} 帧）")
                    break

                if _left_button_down():
                    seen_down = True
                    released_frames = 0
                elif seen_down:
                    # 只有「确实按下过」才拿松开状态当退出依据。
                    # 20 帧 ≈ 160ms：真鼠标松手后不会出现这么长的连续松开。
                    released_frames += 1
                    if released_frames >= 20:
                        logger.info(
                            f"[PollResize] 按键状态显示已松开（{frames} 帧）"
                        )
                        break

                cur = _cursor_pos()
                if cur is None:
                    break
                cx, cy = cur
                dx, dy = cx - base_x, cy - base_y

                new_left, new_top = start_x, start_y
                new_w, new_h = start_w, start_h

                if corner == "top-left":
                    new_left = start_x + dx
                    new_top = start_y + dy
                    new_w = start_w - dx
                    new_h = start_h - dy
                elif corner == "top-right":
                    new_top = start_y + dy
                    new_w = start_w + dx
                    new_h = start_h - dy
                elif corner == "bottom-left":
                    new_left = start_x + dx
                    new_w = start_w - dx
                    new_h = start_h + dy
                else:  # bottom-right
                    new_w = start_w + dx
                    new_h = start_h + dy

                # 最小尺寸：从被拖的那条边"顶住"，对边保持不动
                if new_w < min_w:
                    if corner in ("top-left", "bottom-left"):
                        new_left = start_x + start_w - min_w
                    new_w = min_w
                if new_h < min_h:
                    if corner in ("top-left", "top-right"):
                        new_top = start_y + start_h - min_h
                    new_h = min_h

                # 工作区钳制：同样保证对边不动
                if new_left < work_left:
                    if corner in ("top-left", "bottom-left"):
                        new_w -= (work_left - new_left)
                    new_left = work_left
                if new_top < work_top:
                    if corner in ("top-left", "top-right"):
                        new_h -= (work_top - new_top)
                    new_top = work_top
                if new_left + new_w > work_right:
                    new_w = work_right - new_left
                if new_top + new_h > work_bottom:
                    new_h = work_bottom - new_top

                new_w = max(min_w, int(new_w))
                new_h = max(min_h, int(new_h))

                cur_rect = (int(new_left), int(new_top), new_w, new_h)
                if cur_rect != last:
                    _user32.SetWindowPos(
                        hwnd, None, cur_rect[0], cur_rect[1],
                        cur_rect[2], cur_rect[3],
                        _SWP_NOZORDER | _SWP_NOREDRAW,
                    )
                    last = cur_rect
                    frames += 1

                time.sleep(0.008)  # ~120Hz，足够跟手又不烧 CPU

            logger.info(f"[PollResize] 完成，最终 {last[2]}x{last[3]}")
            if on_finish:
                try:
                    on_finish(last)
                except Exception as exc:
                    logger.debug(f"[PollResize] 结束回调异常（忽略）: {exc}")
        except Exception as exc:
            logger.error(f"[PollResize] 缩放异常: {exc}", exc_info=True)
        finally:
            with _resize_lock:
                _resize_active = False

    threading.Thread(target=_worker, daemon=True, name="PollResize").start()
    return True



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


def _corner_from_lparam(hwnd: int, lparam: int):
    """
    判断屏幕坐标点是否落在窗口四个角的热区内。

    lParam 的低 16 位是 X、高 16 位是 Y（均为**屏幕**物理坐标，有符号 short）。
    热区按物理像素 = CORNER_HIT_SIZE * 当前窗口 DPI 缩放计算，
    保证在不同缩放下「手感」一致（150% 缩放下热区不至于只有 8 个物理像素）。

    Returns:
        命中的 HT* 常量；不在任何角部时返回 None。
    """
    try:
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value

        rect = get_window_rect(hwnd)
        if not rect:
            return None
        left, top, right, bottom = rect

        # 用窗口自身 DPI 换算热区大小；取不到 DPI 时按 1.0 处理
        try:
            dpi = _user32.GetDpiForWindow(hwnd) or 96
        except Exception:
            dpi = 96
        size = max(6, round(CORNER_HIT_SIZE * (dpi / 96.0)))

        near_left = left <= x < left + size
        near_right = right - size < x <= right
        near_top = top <= y < top + size
        near_bottom = bottom - size < y <= bottom

        if near_left and near_top:
            return _HTTOPLEFT
        if near_right and near_top:
            return _HTTOPRIGHT
        if near_left and near_bottom:
            return _HTBOTTOMLEFT
        if near_right and near_bottom:
            return _HTBOTTOMRIGHT
        return None
    except Exception as exc:
        logger.debug(f"[WindowBounds] 角部命中判定异常（忽略）: {exc}")
        return None


def _workarea_wndproc_impl(hwnd, msg, wparam, lparam):
    """窗口过程钩子：改写最大化尺寸到工作区；四角返回缩放命中码；其余转发原过程"""
    global _clamping
    try: # 尽量小的影响面：仅拦截最大化尺寸计算与最大化后的兜底钳制
        # 全屏豁免：全屏要求占满整块显示器（覆盖任务栏），
        # 而下面的逻辑是「最大化只占工作区（保留任务栏）」。
        # 两者语义互斥，全屏期间必须整段跳过，否则全屏会被钳成最大化。
        if is_fullscreen_override(hwnd):
            orig = _installed.get(hwnd)
            if orig is None:
                return 0
            return _user32.CallWindowProcW(orig, hwnd, msg, wparam, lparam)

        if msg == _WM_GETMINMAXINFO and lparam:
            mmi = ctypes.cast(lparam, ctypes.POINTER(_MINMAXINFO)).contents
            info = get_monitor_info(hwnd)
            if info:
                wl, wt, wr, wb = info["work_rect"]
                ml, mt, mr, mb = info.get("monitor_rect") or (wl, wt, wr, wb)
                mmi.ptMaxSize.x = wr - wl
                mmi.ptMaxSize.y = wb - wt
                mmi.ptMaxPosition.x = wl
                mmi.ptMaxPosition.y = wt
                # ptMaxTrackSize 是「用户拖动能拉伸到的最大尺寸」。
                # 这里 `return 0` 会跳过 DefWindowProc，系统不会再帮忙填这一项；
                # 若缓冲区是零初始化的，ptMaxTrackSize 就变成 (0, 0)，
                # 与下面的 ptMinTrackSize(1024x640) 直接矛盾。
                # 系统在「最大 < 最小」这种非法区间里的表现就是：
                # 拖角时窗口被瞬间撑到最大（看起来像「点一下就最大化」）。
                # 因此必须显式给出：上限取当前显示器的完整矩形（允许铺满屏幕），
                # 下限不小于最小跟踪尺寸。
                max_track_w = max(mr - ml, 1)
                max_track_h = max(mb - mt, 1)
                if _min_track_size:
                    mmi.ptMinTrackSize.x = _min_track_size[0]
                    mmi.ptMinTrackSize.y = _min_track_size[1]
                    max_track_w = max(max_track_w, _min_track_size[0])
                    max_track_h = max(max_track_h, _min_track_size[1])
                mmi.ptMaxTrackSize.x = max_track_w
                mmi.ptMaxTrackSize.y = max_track_h
                return 0
        elif msg == _WM_NCCALCSIZE and wparam:
            # 为了拿到原生缩放缓动环，窗口保留了 WS_THICKFRAME；
            # 但标准的 THICKFRAME 会算出 4~8px 的边框区域，
            # 使客户区比窗口矩形小一圈（表现为四周露出黑边、
            # 前端按 100vw/100vh 排版时被裁掉一角）。
            # wParam=TRUE 时返回 0 表示「客户区与窗口矩形完全一致」，
            # 即没有非客户区边框。wParam=FALSE 的分支交回原过程处理。
            return 0
        elif msg == _WM_NCHITTEST and lparam:
            # 只在四个角的正方形区域内返回缩放命中码。
            # 若窗口已最大化/最小化，不返回缩放码，避免出现「最大化窗口被拖动缩放」
            # 这种 Windows 本身也不支持的状态。
            if not _user32.IsZoomed(hwnd) and not _user32.IsIconic(hwnd):
                corner = _corner_from_lparam(hwnd, lparam)
                if corner is not None:
                    return corner
                # 非角部的命中一律交回客户端区域，避免继承 WS_THICKFRAME
                # 残留的四边缩放行为（用户要求四边不再拖动）。
                return _HTCLIENT
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


def is_corner_resize_active(hwnd) -> bool:
    """
    判断「四角原生缩放」是否已经接管。

    条件：该 hwnd 已安装本模块的窗口过程钩子。
    装了钩子，WM_NCHITTEST 就会只对四角返回缩放命中码，
    Windows 自己负责光标形状与缩放缓动环，前端无需再叠加热区。
    """
    try:
        if hwnd and hwnd in _installed:
            return True
    except Exception:
        pass
    return False


def install_maximize_workarea_hook(hwnd: int, min_width: int = 0, min_height: int = 0) -> bool:
    """
    为窗口安装「最大化约束到工作区 + 四角原生缩放 + 最小尺寸」的窗口过程钩子
    （幂等，按 hwnd 去重）。

    必须在窗口创建后调用。子类化本身在任意线程调用都安全，
    但窗口消息仍在窗口线程上派发。

    Args:
        hwnd: 窗口句柄
        min_width: 最小宽度（**物理**像素）。>0 时生效，供原生缩放缓动环使用。
        min_height: 最小高度（**物理**像素）。

    Returns:
        bool: 是否成功安装（已安装过同 hwnd 也返回 True）
    """
    global _workarea_wndproc
    try:
        if min_width > 0 and min_height > 0:
            set_min_track_size(min_width, min_height)

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
        logger.info(
            f"[WindowBounds] 已安装窗口钩子 (hwnd={hwnd}, 最小尺寸={min_width}x{min_height})"
        )
        return True
    except Exception as e:
        logger.warning(f"[WindowBounds] 安装窗口钩子失败: {e}")
        return False


# ============================================================================
# frameless 样式复位（全屏进出 / 最大化还原后的兜底）
#
# 背景：pywebview 的 winforms 后端在退出全屏时执行
#     self.FormBorderStyle = self.old_style
# WinForms 会因此重算窗口样式（内部走 SetWindowLong(GWL_STYLE)），把我们为
# 「原生四角缩放」刻意保留的 WS_THICKFRAME 位清掉。结果：进出一次全屏后，
# 四角拖动又变回「没反应 / 只有窗口在动、尺寸不变」。
#
# 修复：在每次状态切换（全屏进/出、最大化还原）后调用本函数重新应用一次
# 目标样式，并同步刷新窗口框架。幂等，可重复调用。
# ============================================================================

_GWL_STYLE = -16
_WS_POPUP = 0x80000000
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_WS_SYSMENU = 0x00080000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_SWP_FRAMECHANGED = 0x0020
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001

# 32 位样式读写。必须显式声明 long 原型：
# - 不声明 restype 时 ctypes 默认按 c_int 返回，WS_POPUP(0x80000000) 会变成负数，
#   位运算前需 & 0xFFFFFFFF 转无符号；
# - 不声明 argtypes 时传入 >2^31 的值可能触发 OverflowError。
_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowLongW.restype = ctypes.c_long
_user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
_user32.SetWindowLongW.restype = ctypes.c_long


def ensure_frameless_style(hwnd: int, refresh_frame: bool = True) -> bool:
    """
    重新应用 frameless + 可缩放 的窗口样式。

    目标样式 = 保留原样式里除标题栏相关的位 +
               WS_POPUP（无标题栏） + WS_THICKFRAME（原生缩放必需） + WS_MINIMIZEBOX

    Args:
        hwnd: 窗口句柄
        refresh_frame: 是否调用 SetWindowPos(SWP_FRAMECHANGED) 让系统重算非客户区。
                       WM_NCCALCSIZE 会把非客户区消成 0，因此不会出现可视边框。

    Returns:
        bool: 是否成功
    """
    try:
        if not hwnd:
            return False
        # GetWindowLongW 对超出 32 位的样式位（WS_POPUP = 0x80000000）会返回负数，
        # 用 & 0xFFFFFFFF 转成无符号再参与位运算。
        current = _user32.GetWindowLongW(hwnd, _GWL_STYLE) & 0xFFFFFFFF
        remove_mask = _WS_CAPTION | _WS_SYSMENU | _WS_MAXIMIZEBOX
        target = (current & ~remove_mask) | _WS_POPUP | _WS_THICKFRAME | _WS_MINIMIZEBOX
        _user32.SetWindowLongW(hwnd, _GWL_STYLE, target & 0xFFFFFFFF)
        if refresh_frame:
            flags = _SWP_FRAMECHANGED | _SWP_NOZORDER | _SWP_NOMOVE | _SWP_NOSIZE
            _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, flags)
        logger.debug(
            f"[WindowBounds] 样式复位 0x{current:08X} -> 0x{target & 0xFFFFFFFF:08X} (hwnd={hwnd})"
        )
        return True
    except Exception as e:
        logger.warning(f"[WindowBounds] 样式复位失败: {e}")
        return False


def refresh_corner_resize(hwnd: int, min_width: int = 0, min_height: int = 0) -> bool:
    """
    状态切换（全屏进出 / 最大化还原）后的统一收尾：
    复位 frameless 样式 + 确保窗口钩子仍然在位。

    为什么要「确保钩子在位」：WinForms 重设 FormBorderStyle 时可能同时重建
    窗口句柄（Handle），旧 hwnd 的子类化会随之失效 → WM_NCHITTEST 不再被拦截，
    四角缩放彻底失效。这里按「当前有效 hwnd」重新安装（幂等）。
    """
    try:
        if not hwnd:
            return False
        ok_style = ensure_frameless_style(hwnd, refresh_frame=True)
        ok_hook = install_maximize_workarea_hook(hwnd, min_width=min_width, min_height=min_height)
        return bool(ok_style and ok_hook)
    except Exception as e:
        logger.warning(f"[WindowBounds] 刷新四角缩放失败: {e}")
        return False
