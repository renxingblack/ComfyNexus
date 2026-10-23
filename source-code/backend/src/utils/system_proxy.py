"""
系统代理检测

判定当前是否开启了系统代理（Windows 注册表 / 环境变量）。
镜像加速的默认开关依据此状态：
- 未开系统代理 → 默认开启所有镜像加速（直连不稳定）
- 已开系统代理 → 默认关闭所有加速（代理本身即加速通道）
"""

import os
from typing import Optional

from backend.src.utils.logger import app_logger as logger

_cached: Optional[bool] = None
_cache_ts: float = 0.0
_CACHE_TTL = 30.0  # 秒级缓存，避免频繁读注册表


def _check_registry_proxy() -> bool:
    """读 Windows 注册表的 ProxyEnable / ProxyServer"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        try:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return False
            # ProxyEnable=1 但未配置服务器地址 → 视为未开
            try:
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
                return bool(str(server).strip())
            except FileNotFoundError:
                # 可能使用 PAC 自动配置脚本
                try:
                    winreg.QueryValueEx(key, "AutoConfigURL")
                    return True
                except FileNotFoundError:
                    return False
        finally:
            winreg.CloseKey(key)
    except Exception as e:
        logger.debug(f"[system-proxy] 注册表读取失败: {e}")
        return False


def _check_env_proxy() -> bool:
    """环境变量代理（HTTP_PROXY/HTTPS_PROXY/all_proxy）"""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                 "http_proxy", "https_proxy", "all_proxy"):
        v = os.environ.get(name, "").strip()
        if v:
            return True
    return False


def has_system_proxy() -> bool:
    """
    系统代理是否开启（结果缓存 30 秒）

    以 Windows 注册表（Internet 设置）为主判据——"系统代理"的标准含义。
    环境变量仅在注册表读取失败时作为回退（部分终端级代理只设 env）。
    """
    global _cached, _cache_ts
    import time
    now = time.time()
    if _cached is not None and now - _cache_ts < _CACHE_TTL:
        return _cached
    try:
        result = _check_registry_proxy()
    except Exception:
        result = _check_env_proxy()
    _cached = result
    _cache_ts = now
    return result


def get_system_proxy() -> Optional[str]:
    """系统代理地址（http://host:port），未开启返回 None"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        try:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return None
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
            server = str(server).strip()
            if not server:
                return None
            if "=" in server:  # 形如 http=...;https=... 取 https 段
                for part in server.split(";"):
                    if part.startswith("https=") or part.startswith("http="):
                        server = part.split("=", 1)[1]
                        break
            if not server.startswith("http"):
                server = "http://" + server
            return server
        finally:
            winreg.CloseKey(key)
    except Exception:
        return None
