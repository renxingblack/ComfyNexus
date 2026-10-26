"""
Windows 单例运行工具

使用 Windows Mutex 确保应用只有一个实例运行。
如果已有实例运行，则激活已存在的窗口并退出当前实例。
"""

import sys
import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Optional

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

HWND = wintypes.HWND
DWORD = wintypes.DWORD
LPWSTR = wintypes.LPWSTR
LPCWSTR = wintypes.LPCWSTR
HANDLE = wintypes.HANDLE
BOOL = wintypes.BOOL

CreateMutexW = kernel32.CreateMutexW
CreateMutexW.argtypes = [ctypes.c_void_p, BOOL, LPCWSTR]
CreateMutexW.restype = HANDLE

ReleaseMutex = kernel32.ReleaseMutex
ReleaseMutex.argtypes = [HANDLE]
ReleaseMutex.restype = BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [HANDLE]
CloseHandle.restype = BOOL

GetLastError = kernel32.GetLastError
GetLastError.argtypes = []
GetLastError.restype = DWORD

EnumWindows = user32.EnumWindows
# **必须用真正的回调类型**，不能用 c_void_p：
# 传 c_void_p 时 ctypes 无法把 WINFUNCTYPE 实例转成指针（或按默认 int 截断参数），
# 回调会被静默跳过，EnumWindows 返回后一个窗口都收不到。
# 这类失败完全不报错，只会让「枚举兜底」形同虚设 —— 以前只能靠 FindWindowW，
# 而 FindWindowW 在 Win11 上又会命中 TabProxyWindow，两个兜底同时失效。
_WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, HWND, wintypes.LPARAM)
EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
EnumWindows.restype = BOOL

GetWindowTextW = user32.GetWindowTextW
GetWindowTextW.argtypes = [HWND, LPWSTR, ctypes.c_int]
GetWindowTextW.restype = ctypes.c_int

# 取窗口类名。用于识别并排除 Win11 的 TabProxyWindow（同名干扰项）。
GetClassNameW = user32.GetClassNameW
GetClassNameW.argtypes = [HWND, LPWSTR, ctypes.c_int]
GetClassNameW.restype = ctypes.c_int

IsWindowVisible = user32.IsWindowVisible
IsWindowVisible.argtypes = [HWND]
IsWindowVisible.restype = BOOL

FindWindowW = user32.FindWindowW
FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
FindWindowW.restype = HWND

SetForegroundWindow = user32.SetForegroundWindow
SetForegroundWindow.argtypes = [HWND]
SetForegroundWindow.restype = BOOL

ShowWindow = user32.ShowWindow
ShowWindow.argtypes = [HWND, ctypes.c_int]
ShowWindow.restype = BOOL

IsIconic = user32.IsIconic
IsIconic.argtypes = [HWND]
IsIconic.restype = BOOL

ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9
SW_SHOW = 5


class SingleInstance:
    """
    Windows 单例运行管理器
    
    使用 Mutex 确保只有一个应用实例运行。
    当检测到已有实例时，会激活已存在的窗口并返回 False。
    """
    
    def __init__(self, app_name: str = "ComfyNexus"):
        self.app_name = app_name
        self.mutex_name = f"Global\\{app_name}_SingleInstance_Mutex"
        self.mutex_handle: Optional[HANDLE] = None
        self._is_first_instance: Optional[bool] = None
    
    def try_acquire(self) -> bool:
        """
        尝试获取单例锁
        
        Returns:
            bool: True 表示是第一个实例，False 表示已有实例运行
        """
        if self._is_first_instance is not None:
            return self._is_first_instance
        
        self.mutex_handle = CreateMutexW(None, False, self.mutex_name)
        
        if not self.mutex_handle:
            return True
        
        last_error = GetLastError()
        
        if last_error == ERROR_ALREADY_EXISTS:
            self._is_first_instance = False
            self._activate_existing_window()
            return False
        
        self._is_first_instance = True
        return True
    
    def _activate_existing_window(self) -> bool:
        """
        激活已存在的窗口（含托盘隐藏状态）

        **不能直接用 `FindWindowW(None, app_name)` 的结果**（本轮实测的坑）：
          Win11 文件资源管理器标签化后，会为每个顶层窗口在 explorer.exe 里
          创建一个**同名**伴生窗口 `Windows.Internal.Shell.TabProxyWindow`。
          `FindWindowW` 只按标题匹配，会先命中它 —— 于是「激活已有实例」变成了
          去 `ShowWindow`/`SetForegroundWindow` 一个**别人家进程**的窗口，
          真正的应用窗口毫无反应，用户二次启动时看起来「什么都没有发生」。

        改为：枚举所有顶层窗口，要求「标题含 app_name」**且**类名不是
        TabProxyWindow。找不到再退化为按标题精确匹配（旧行为）。
        Returns: 是否成功找到并激活
        """
        found = []
        EnumWindows_CB = ctypes.WINFUNCTYPE(ctypes.c_bool, HWND, wintypes.LPARAM)

        def _is_proxy(h) -> bool:
            """是否是 explorer 的标签页代理窗口（同名干扰项，必须排除）。"""
            try:
                cls_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(h, cls_buf, 256)
                return "TabProxyWindow" in (cls_buf.value or "")
            except Exception:
                return False

        def _cb(h, _l):
            try:
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(h, buf, 256)
                # 不检查 IsWindowVisible：托盘隐藏（SW_HIDE）的窗口也必须能找到，
                # 否则用户从托盘状态下二次启动会误判「无窗口」而弹错误框
                if self.app_name in (buf.value or "") and not _is_proxy(h):
                    found.append(h)
            except Exception:
                pass
            return True

        try:
            user32.EnumWindows(EnumWindows_CB(_cb), 0)
        except Exception:
            pass

        hwnd = found[0] if found else None

        if not hwnd or hwnd == 0:
            # 最后兜底：老的精确标题查找（仅在枚举完全失效时使用）
            hwnd = FindWindowW(None, self.app_name)
            if hwnd and _is_proxy(hwnd):
                # 命中的是代理窗口，宁可当作没找到，也不要去激活别人的窗口
                hwnd = None

        if hwnd and hwnd != 0:
            try:
                if IsIconic(hwnd):
                    ShowWindow(hwnd, SW_RESTORE)
                else:
                    ShowWindow(hwnd, SW_SHOW)
                SetForegroundWindow(hwnd)
                return True
            except Exception:
                return False
        return False
    
    def release(self):
        """
        释放单例锁
        
        在应用退出时调用，释放 Mutex。
        """
        if self.mutex_handle:
            ReleaseMutex(self.mutex_handle)
            CloseHandle(self.mutex_handle)
            self.mutex_handle = None
            self._is_first_instance = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


def check_single_instance(app_name: str = "ComfyNexus") -> Optional[SingleInstance]:
    """
    检查是否为单例运行
    
    Args:
        app_name: 应用名称，用于 Mutex 命名和窗口查找
    
    Returns:
        SingleInstance: 如果是第一个实例，返回管理器对象（需要在退出时调用 release）
        None: 如果已有实例运行，返回 None
    """
    instance = SingleInstance(app_name)
    
    if instance.try_acquire():
        return instance
    
    return None


def ensure_single_instance(app_name: str = "ComfyNexus") -> tuple[bool, Optional[SingleInstance]]:
    """
    确保单例运行
    
    便捷函数，返回是否为第一个实例以及管理器对象。
    
    Args:
        app_name: 应用名称
    
    Returns:
        tuple: (is_first_instance, instance_manager)
            - is_first_instance: True 表示是第一个实例
            - instance_manager: 单例管理器对象，需要在应用退出时释放
    """
    instance = SingleInstance(app_name)
    is_first = instance.try_acquire()
    # 非第一个实例也返回实例对象（含激活方法），调用方可主动 _activate_existing_window()
    return is_first, instance
