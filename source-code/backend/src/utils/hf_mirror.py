"""
HuggingFace 镜像源管理模块

提供 HuggingFace 国内镜像加速功能：
- 自动调度选择最优镜像（测速 + 防抖）
- 心跳检测
- URL 改写（huggingface.co → 当前镜像域名）

镜像清单：
- official    huggingface.co 官方（国内直连通常不可达）
- hf-mirror   hf-mirror.com（国内最稳定的 HF 镜像，支持 LFS/CDN）
"""

import time
import threading
from typing import Dict, Optional, Callable, List
from datetime import datetime

import requests

from backend.src.utils.logger import app_logger as logger


HF_MIRROR_SOURCES = {
    "hf-mirror": {
        "name": "HF-Mirror（国内镜像）",
        "description": "国内最稳定的 HuggingFace 镜像，CDN 全量加速，支持 LFS",
        "base_url": "https://hf-mirror.com",
    },
    "official": {
        "name": "HuggingFace 官方",
        "description": "官方源，国内通常需要代理才能访问",
        "base_url": "https://huggingface.co",
    },
}

HEARTBEAT_INTERVAL = 6 * 60 * 60


class AntiJitterPolicy:
    """防抖动策略：延迟未显著改善不切换，连续失败强制切换"""

    SWITCH_THRESHOLD = 0.8
    FAILURE_THRESHOLD = 2

    def __init__(self):
        self.failure_counts: Dict[str, int] = {}

    def should_switch(self, current: str, current_latency: int,
                      new: str, new_latency: int) -> bool:
        if new_latency < current_latency * self.SWITCH_THRESHOLD:
            return True
        return self.failure_counts.get(current, 0) >= self.FAILURE_THRESHOLD

    def record_failure(self, source: str):
        self.failure_counts[source] = self.failure_counts.get(source, 0) + 1

    def reset_all(self):
        self.failure_counts.clear()


class HFMirrorManager:
    """HuggingFace 镜像源管理器（单例）"""

    _instance: Optional["HFMirrorManager"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, settings_manager=None):
        if self._initialized:
            return
        self._settings_manager = settings_manager
        self._anti_jitter = AntiJitterPolicy()
        self._current_source: Optional[str] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()
        self._speed_test_running = False
        self._speed_test_progress: List[Dict] = []
        self._speed_test_results: Optional[Dict] = None
        self._initialized = True
        # 启动时恢复上次选择的镜像
        self._current_source = self._load_settings().get("currentSource") or None
        logger.info("[HFMirrorManager] 初始化完成")

    # ---------- 设置 ----------

    @property
    def settings_manager(self):
        if self._settings_manager is None:
            from backend.src.core.settings_manager import SettingsManager
            self._settings_manager = SettingsManager()
        return self._settings_manager

    def _load_settings(self) -> Dict:
        try:
            return self.settings_manager.load_config().get("hfMirror", {})
        except Exception:
            return {}

    def _save_settings(self, s: Dict):
        try:
            self.settings_manager.update_settings({"hfMirror": s})
        except Exception as e:
            logger.error(f"[HFMirrorManager] 保存设置失败: {e}")

    def is_enabled(self) -> bool:
        """
        未开启系统代理 -> 默认开启镜像加速；已开系统代理 -> 默认关闭。
        用户显式设置过（userSet=True）则尊重用户选择。
        """
        from backend.src.utils.system_proxy import has_system_proxy
        s = self._load_settings()
        if s.get("userSet", False):
            return s.get("enabled", True)
        return not has_system_proxy()

    def get_mode(self) -> str:
        return self._load_settings().get("mode", "auto")

    def get_force_source(self) -> Optional[str]:
        return self._load_settings().get("forceSource")

    def get_current_source_name(self) -> Optional[str]:
        if not self.is_enabled():
            return None
        if self.get_mode() == "manual" and self.get_force_source():
            if self.get_force_source() in HF_MIRROR_SOURCES:
                return self.get_force_source()
        return self._current_source or "hf-mirror"

    def get_settings(self) -> Dict:
        s = self._load_settings()
        s["statusText"] = self.get_status_text()
        s["currentSource"] = self.get_current_source_name()
        s["isTesting"] = self._speed_test_running
        s["testResults"] = self._speed_test_results
        return s

    def update_settings(self, updates: Dict):
        settings = self._load_settings()
        settings.update(updates)
        self._save_settings(settings)

        if updates.get("enabled") is True:
            self.enable_mirror()
        elif updates.get("enabled") is False:
            self.disable_mirror()
        elif updates.get("mode") == "manual" or updates.get("forceSource"):
            # 手动模式立即应用指定源
            self._current_source = self.get_current_source_name()

    # ---------- URL 改写 ----------

    def get_current_base_url(self) -> str:
        """当前生效的 HF 基础 URL（未启用时返回官方）"""
        name = self.get_current_source_name()
        source = HF_MIRROR_SOURCES.get(name) if name else None
        return (source or HF_MIRROR_SOURCES["official"])["base_url"]

    def transform_url(self, url: str) -> str:
        """
        把 huggingface.co 官方 URL 改写为当前镜像 URL。

        未启用镜像或 URL 与 HF 无关时原样返回。
        """
        if not url or "huggingface.co" not in url:
            return url
        if not self.is_enabled():
            return url
        base = self.get_current_base_url()
        if base == HF_MIRROR_SOURCES["official"]["base_url"]:
            return url
        return url.replace("https://huggingface.co", base, 1)

    # ---------- 启停 ----------

    def enable_mirror(self):
        settings = self._load_settings()
        settings["enabled"] = True
        settings["userSet"] = True
        if "mode" not in settings:
            settings["mode"] = "auto"
        self._save_settings(settings)

        if not self._speed_test_results:
            self._current_source = "hf-mirror"
            # 异步测速（后台线程，不阻塞设置保存；start_speed_test 内部已判重）
            self.start_speed_test()
        else:
            self._current_source = self._best_source(self._speed_test_results)
        self._start_heartbeat()

    def disable_mirror(self):
        settings = self._load_settings()
        settings["enabled"] = False
        settings["userSet"] = True
        self._save_settings(settings)
        self._stop_heartbeat()

    # ---------- 测速 ----------

    def start_speed_test(self) -> Dict:
        if self._speed_test_running:
            return {"success": False, "message": "测速正在进行中"}
        self._speed_test_running = True
        self._speed_test_progress = []
        self._speed_test_results = None
        threading.Thread(target=self._run_speed_test, daemon=True).start()
        return {"success": True, "message": "测速已开始"}

    def _run_speed_test(self):
        try:
            results = {}
            for name, info in HF_MIRROR_SOURCES.items():
                latency = self._test_speed(info["base_url"])
                results[name] = latency
                self._speed_test_progress.append(
                    {"source": name, "latency": latency, "timestamp": time.time()}
                )

            self._speed_test_results = results
            settings = self._load_settings()
            settings["lastTested"] = datetime.now().isoformat()
            settings["testResults"] = results
            self._save_settings(settings)

            # 自动模式：切换到最优镜像（防抖）
            if self.is_enabled() and self.get_mode() == "auto":
                best = self._best_source(results)
                current = self._current_source or "hf-mirror"
                if best != current:
                    cur_latency = results.get(current) or 9999
                    best_latency = results.get(best) or 9999
                    if self._anti_jitter.should_switch(
                        current, cur_latency, best, best_latency
                    ):
                        self._current_source = best
                        logger.info(f"[HFMirrorManager] 自动切换到最优镜像: {best}")
        except Exception as e:
            logger.error(f"[HFMirrorManager] 测速失败: {e}")
        finally:
            self._speed_test_running = False

    def _best_source(self, results: Dict) -> str:
        valid = {k: v for k, v in results.items() if v > 0}
        if not valid:
            return "hf-mirror"
        return min(valid, key=valid.get)

    def _test_speed(self, base_url: str) -> int:
        """测速：GET /api/models?limit=1（轻量 JSON 接口，测完整可达性）"""
        try:
            start = time.time()
            r = requests.get(
                f"{base_url}/api/models?limit=1",
                headers={"User-Agent": "ComfyNexus/1.0"},
                timeout=(10, 15),
                stream=True,
            )
            r.raise_for_status()
            # 读一小段确认真的有数据回来
            next(r.iter_content(4096), b"")
            return int((time.time() - start) * 1000)
        except Exception as e:
            logger.debug(f"[HFMirrorManager] 测速失败 ({base_url}): {e}")
            return -1

    def get_speed_test_status(self) -> Dict:
        return {
            "isRunning": self._speed_test_running,
            "progress": self._speed_test_progress,
            "results": self._speed_test_results,
        }

    # ---------- 状态 ----------

    def get_status_text(self) -> str:
        if not self.is_enabled():
            return ""
        if self._speed_test_running:
            return "正在测速中..."
        name = self.get_current_source_name()
        if name:
            label = HF_MIRROR_SOURCES[name]["name"]
            latency = (self._speed_test_results or {}).get(name)
            if latency and latency > 0:
                return f"当前源: {label} (延迟 {latency}ms)"
            return f"当前源: {label}"
        return "HuggingFace 镜像加速已启用"

    # ---------- 心跳 ----------

    def _start_heartbeat(self):
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self):
        self._heartbeat_stop.set()

    def _heartbeat_loop(self):
        while not self._heartbeat_stop.wait(timeout=HEARTBEAT_INTERVAL):
            if not self.is_enabled():
                break
            try:
                self._run_speed_test()
            except Exception as e:
                logger.error(f"[HFMirrorManager] 心跳检测失败: {e}")


hf_mirror_manager = HFMirrorManager()
