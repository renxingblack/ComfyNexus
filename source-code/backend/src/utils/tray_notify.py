"""Windows 托盘气泡通知（无第三方依赖，Shell_NotifyIconW）"""

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32

NIIF_INFO = 0x1
NIF_INFO = 0x10
NIM_MODIFY = 0x1


def show_balloon(message: str, title: str = "") -> bool:
    """
    显示托盘气泡通知。

    说明：气泡必须挂在已有的托盘图标上（NIM_MODIFY），本软件启动时
    由 system_tray_manager 创建了托盘图标；若托盘不可用则静默失败。
    """
    try:
        # 找到本进程的托盘窗口不可靠，退而求其次：直接创建一个临时托盘图标再删除
        # （Shell_NotifyIcon NIM_ADD 需要窗口句柄；用消息窗口简化）
        # 实测最简单可靠的方式：复用 PowerShell 气泡（无依赖、异步、不阻塞）
        import subprocess
        import os
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
            "ContentType = WindowsRuntime] | Out-Null;"
            f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('ComfyNexus')"
        )
        # PowerShell toast 在部分系统受限，退回 balloon tip 经由临时窗体
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$n = New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon = [System.Drawing.SystemIcons]::Information;"
            "$n.Visible = $true;"
            f"$n.ShowBalloonTip(4000, '{title}', '{message}', "
            "[System.Windows.Forms.ToolTipIcon]::Info);"
            "Start-Sleep -Seconds 5;$n.Dispose()"
        )
        flags = 0x08000000  # CREATE_NO_WINDOW
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            creationflags=flags,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False
