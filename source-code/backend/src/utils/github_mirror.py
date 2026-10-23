"""
GitHub 镜像源管理模块

提供 GitHub 资源访问的镜像加速功能，包括：
- URL 转换（Raw/Release/API）
- Git 环境变量注入
- 自动调度与故障转移
- 心跳检测
- 测速功能
- 防抖动策略
"""

import os
import subprocess
import time
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple, Callable, List
from datetime import datetime

import requests

from backend.src.utils.logger import app_logger as logger


MIRROR_PRESETS = {
    "hybrid": {
        "name": "混合加速",
        "description": "系统自动选择最优镜像（gh-proxy.com 方式优先）",
        "github": "gh-proxy.com",
        "raw": "gh-proxy.com",
        "api": None,
        "release": "gh-proxy.com",
        # fallback 融合 Github Enhancement 高速下载脚本（scriptcat #7474）的高可用加速源
        # （全部为完整前缀形式 https://{mirror}/https://github.com/...，顺序即回退优先级）
        "fallback": {
            "github": [
                "ghfast.top", "ghproxy.net", "wget.la", "hk.gh-proxy.org",
                "gh.h233.eu.org", "gh.ddlc.top", "github.moeyy.xyz", None,
            ],
            "raw": [
                "cdn.gh-proxy.org", "hk.gh-proxy.org", "ghfast.top",
                "gh.monlor.com", "gh.catmak.name", "gh.77yun.com.cn",
                "g.blfrp.cn", "wget.la",
            ],
            # 顺序按实测速度排列（cdn.gh-proxy.org 实测 ~1.6MB/s，gh-proxy.com ~0.2MB/s）
            "release": [
                "cdn.gh-proxy.org", "hk.gh-proxy.org", "ghfast.top",
                "gh.monlor.com", "gh.catmak.name", "gh.77yun.com.cn",
                "gh-proxy.net", "gh.h233.eu.org", "gh.ddlc.top",
                "wget.la", "github.moeyy.xyz", "ghproxy.net",
            ],
        },
    },
    "gitclone": {
        "name": "GitClone + GHProxy",
        "description": "Git Clone 用 GitClone，文件下载用 GHProxy",
        "github": "gitclone.com",
        "raw": "ghproxy.net",
        "api": None,
        "release": "ghproxy.net",
        "fallback": {
            "github": ["ghproxy.net", "gh-proxy.com", "ghfast.top", None],
            "release": ["gh-proxy.com", "ghfast.top"],
        },
    },
    "ghfast": {
        "name": "GHFast 加速",
        "description": "ghfast.top 高速节点，文件下载与克隆均支持",
        "github": "ghfast.top",
        "raw": "ghfast.top",
        "api": None,
        "release": "ghfast.top",
        "fallback": {
            "github": ["ghproxy.net", "gh-proxy.com", None],
            "raw": ["ghproxy.net", "gh-proxy.com"],
            "release": ["ghproxy.net", "gh-proxy.com"],
        },
    },
    "moeyy": {
        "name": "Moeyy 加速",
        "description": "github.moeyy.xyz 多协议加速",
        "github": "github.moeyy.xyz",
        "raw": "github.moeyy.xyz",
        "api": None,
        "release": "github.moeyy.xyz",
        "fallback": {
            "github": ["ghproxy.net", "ghfast.top", None],
            "raw": ["ghproxy.net", "ghfast.top"],
            "release": ["ghproxy.net", "ghfast.top"],
        },
    },
    "ur1fun": {
        "name": "UR1Fun + GHProxy",
        "description": "Git Clone 用 UR1Fun，文件下载用 GHProxy",
        "github": "github.ur1.fun",
        "raw": "ghproxy.net",
        "api": None,
        "release": "ghproxy.net",
        "fallback": {
            "github": ["gitclone.com", "ghproxy.net", None],
            "release": ["gh-proxy.com", "ghfast.top"],
        },
    },
    "ghproxy": {
        "name": "GHProxy 纯加速",
        "description": "仅加速文件下载",
        "github": None,
        "raw": "ghproxy.net",
        "api": None,
        "release": "ghproxy.net",
        "fallback": {
            "github": ["gh-proxy.com", "ghfast.top", None],
            "raw": ["gh-proxy.com", "ghfast.top"],
            "release": ["gh-proxy.com", "ghfast.top"],
        },
    },
}

MIRROR_USER_AGENTS = {
    "ghproxy.net": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "mirror.ghproxy.com": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "gh-proxy.com": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "ghfast.top": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "github.moeyy.xyz": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "gitclone.com": "git/2.0",
    "github.ur1.fun": "git/2.0",
}

# GitHub 文件下载测速：约 67MB 的稳定 Release 大文件（采样下载前 N MB 评估真实速度）
GITHUB_FILE_SPEED_TEST_URL = (
    "https://github.com/renxingblack/math-vertical-worksheet-generator/releases/download/4.0/Vertical-Division-Generator-4.0.exe"
)

SPEED_TEST_FILES = {
    "github": "https://github.com/git/git/archive/refs/heads/master.zip",
    "raw": "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/README.md",
    "release": "https://github.com/git-for-windows/git/releases/download/v2.50.0.windows.1/Git-2.50.0-64-bit.exe",
}

HEARTBEAT_INTERVAL = 6 * 60 * 60


class AntiJitterPolicy:
    """防抖动策略"""

    SWITCH_THRESHOLD = 0.8
    FAILURE_THRESHOLD = 2

    def __init__(self):
        self.failure_counts: Dict[str, int] = {}

    def should_switch(
        self,
        current_mirror: str,
        current_latency: int,
        new_mirror: str,
        new_latency: int,
    ) -> bool:
        if new_latency < current_latency * self.SWITCH_THRESHOLD:
            return True
        if self.failure_counts.get(current_mirror, 0) >= self.FAILURE_THRESHOLD:
            return True
        return False

    def record_failure(self, mirror: str):
        self.failure_counts[mirror] = self.failure_counts.get(mirror, 0) + 1

    def reset_failure(self, mirror: str):
        self.failure_counts[mirror] = 0

    def reset_all(self):
        self.failure_counts.clear()


class GitHubMirrorManager:
    """GitHub 镜像源管理器"""

    _instance: Optional["GitHubMirrorManager"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, settings_manager=None):
        if self._initialized:
            return

        self._settings_manager = settings_manager
        self._scheduler = MirrorScheduler(self)
        self._speed_tester = MirrorSpeedTester(self)
        self._anti_jitter = AntiJitterPolicy()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()
        self._speed_test_running = False
        self._speed_test_progress: List[Dict] = []
        self._speed_test_results: Optional[Dict] = None
        self._benchmark = None                    # 安装前全面测速结果（含镜像排名/直连优选）
        self._file_test_ranking = None          # 大文件测速排名（优者在前）
        self._file_test_ts = 0.0
        self._file_testing = False
        self._file_test_lock = __import__("threading").Lock()
        self._initialized = True

        logger.info("[GitHubMirrorManager] 初始化完成")

    @property
    def settings_manager(self):
        if self._settings_manager is None:
            from backend.src.core.settings_manager import SettingsManager
            self._settings_manager = SettingsManager()
        return self._settings_manager

    def _load_settings(self) -> Dict:
        try:
            config = self.settings_manager.load_config()
            return config.get("githubMirror", {})
        except Exception:
            return {}

    def _save_settings(self, mirror_settings: Dict):
        try:
            self.settings_manager.update_settings({"githubMirror": mirror_settings})
        except Exception as e:
            logger.error(f"[GitHubMirrorManager] 保存镜像设置失败: {e}")

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

    def get_force_preset(self) -> Optional[str]:
        return self._load_settings().get("forcePreset", None)

    def get_current_preset_name(self) -> str:
        if not self.is_enabled():
            return ""
        mode = self.get_mode()
        if mode == "manual" and self.get_force_preset():
            preset = self.get_force_preset()
            if preset in MIRROR_PRESETS:
                return preset
        return self._scheduler.current_preset or "hybrid"

    def get_current_preset(self) -> Optional[Dict]:
        name = self.get_current_preset_name()
        if name:
            return MIRROR_PRESETS.get(name)
        return None

    def get_mirror_for_type(self, url_type: str) -> Optional[str]:
        if not self.is_enabled():
            return None
        preset = self.get_current_preset()
        if preset:
            return preset.get(url_type)
        return None

    def transform_url(self, url: str, url_type: str) -> Tuple[str, Dict]:
        """
        转换 URL 为镜像 URL

        Args:
            url: 原始 URL
            url_type: URL 类型 (github, raw, release, api)

        Returns:
            (transformed_url, headers)
        """
        if not self.is_enabled():
            return url, {}

        mirror = self.get_mirror_for_type(url_type)
        if not mirror:
            return url, {}

        headers = self._get_recommended_headers(mirror, url_type)
        transformed = self._do_transform(url, mirror, url_type)
        return transformed, headers

    def _do_transform(self, url: str, mirror: str, url_type: str) -> str:
        if url_type in ("github", "release"):
            if "github.com" in url:
                # 完整前缀形式（缺 https://github.com/ 段会让镜像站 404）
                return url.replace("https://github.com", f"https://{mirror}/https://github.com", 1)
            return url

        if url_type == "raw":
            if "raw.githubusercontent.com" in url:
                return f"https://{mirror}/{url}"
            return url

        if url_type == "api":
            return url

        return url

    def _get_recommended_headers(self, mirror: str, url_type: str) -> Dict:
        headers = {}
        if mirror in MIRROR_USER_AGENTS:
            headers["User-Agent"] = MIRROR_USER_AGENTS[mirror]
        if url_type == "raw":
            headers["Referer"] = "https://github.com/"
        return headers

    def get_git_env_with_mirror(
        self, mirror: Optional[str] = None, mingit_path: Optional[Path] = None
    ) -> Dict:
        """
        获取带有镜像配置的 Git 环境变量

        Args:
            mirror: 镜像源域名
            mingit_path: MinGit 安装路径（Windows 特有）
        """
        env = os.environ.copy()

        settings = self._load_settings()

        if mirror:
            env["GIT_CONFIG_COUNT"] = "1"
            env["GIT_CONFIG_KEY_0"] = f"url.https://{mirror}/https://github.com/.insteadOf"  # 完整前缀
            env["GIT_CONFIG_VALUE_0"] = "https://github.com/"

        if not settings.get("verifySSL", True):
            env["GIT_SSL_NO_VERIFY"] = "true"

        if mingit_path and os.name == "nt":
            mingit_bin = str(mingit_path / "cmd")
            current_path = env.get("PATH", "")
            if mingit_bin not in current_path:
                env["PATH"] = f"{mingit_bin}{os.pathsep}{current_path}"

        return env

    def get_status_text(self) -> str:
        if not self.is_enabled():
            return ""
        if self._speed_test_running:
            return "正在测速中..."
        preset_name = self.get_current_preset_name()
        if preset_name:
            latency = self._get_best_latency(preset_name)
            if latency and latency > 0:
                return f"当前节点: {MIRROR_PRESETS[preset_name]['name']} (延迟 {latency}ms)"
            return f"当前节点: {MIRROR_PRESETS[preset_name]['name']}"
        return "镜像加速已启用"

    def _get_best_latency(self, preset_name: str) -> Optional[int]:
        if self._speed_test_results and preset_name in self._speed_test_results:
            results = self._speed_test_results[preset_name]
            valid = [v for v in results.values() if v > 0]
            if valid:
                return min(valid)
        return None

    def enable_mirror(self):
        settings = self._load_settings()
        settings["enabled"] = True
        settings["userSet"] = True
        if "mode" not in settings:
            settings["mode"] = "auto"
        settings["verifySSL"] = False
        self._save_settings(settings)

        if not self._speed_test_results:
            self._scheduler.current_preset = "hybrid"
            self._start_background_speed_test()
        else:
            best = self._scheduler.get_best_mirror(self._speed_test_results)
            self._scheduler.current_preset = best

        self._start_heartbeat()

    def disable_mirror(self):
        settings = self._load_settings()
        settings["enabled"] = False
        settings["userSet"] = True
        settings["verifySSL"] = True
        self._save_settings(settings)
        self._scheduler.current_preset = None
        self._stop_heartbeat()

    def update_settings(self, updates: Dict):
        settings = self._load_settings()
        settings.update(updates)
        self._save_settings(settings)

        if updates.get("enabled") is True:
            self.enable_mirror()
        elif updates.get("enabled") is False:
            self.disable_mirror()

    def get_settings(self) -> Dict:
        settings = self._load_settings()
        settings["statusText"] = self.get_status_text()
        settings["currentPreset"] = self.get_current_preset_name()
        settings["isTesting"] = self._speed_test_running
        settings["testResults"] = self._speed_test_results
        return settings

    def start_speed_test(self) -> Dict:
        if self._speed_test_running:
            return {"success": False, "message": "测速正在进行中"}
        self._speed_test_running = True
        self._speed_test_progress = []
        self._speed_test_results = None
        thread = threading.Thread(target=self._run_speed_test, daemon=True)
        thread.start()
        return {"success": True, "message": "测速已开始"}

    def _run_speed_test(self):
        try:
            results = self._speed_tester.test_all_mirrors(
                progress_callback=self._on_speed_test_progress
            )
            self._speed_test_results = results
            settings = self._load_settings()
            settings["lastTested"] = datetime.now().isoformat()
            settings["testResults"] = results
            # 前三最优镜像（综合分排序），供下载时优先选择
            top3 = [m["mirror"] for m in getattr(self._speed_tester, "_all_mirrors", [])
                    if m.get("bestLatency", -1) > 0][:3]
            if top3:
                settings["topMirrors"] = top3
                logger.info(f"[GitHubMirrorManager] 前三最优镜像: {', '.join(top3)}")
            self._save_settings(settings)

            if self.is_enabled() and self.get_mode() == "auto":
                best = self._scheduler.get_best_mirror(results)
                current = self._scheduler.current_preset
                if best != current:
                    current_latency = self._get_best_latency(current or "hybrid") or 9999
                    best_latency = self._get_best_latency(best) or 9999
                    if self._anti_jitter.should_switch(
                        current or "hybrid", current_latency, best, best_latency
                    ):
                        self._scheduler.current_preset = best
                        logger.info(f"[GitHubMirrorManager] 自动切换到最优镜像: {best}")
        except Exception as e:
            logger.error(f"[GitHubMirrorManager] 测速失败: {e}")
        finally:
            self._speed_test_running = False

    def _on_speed_test_progress(self, preset_name: str, url_type: str, latency: int):
        self._speed_test_progress.append(
            {
                "preset": preset_name,
                "type": url_type,
                "latency": latency,
                "timestamp": time.time(),
            }
        )

    def get_speed_test_status(self) -> Dict:
        return {
            "isRunning": self._speed_test_running,
            "progress": self._speed_test_progress,
            "results": self._speed_test_results,
            "mirrorSpeeds": getattr(self._speed_tester, "_mirror_speeds", {}),
            "allMirrors": getattr(self._speed_tester, "_all_mirrors", []),
        }

    def _start_background_speed_test(self):
        if not self._speed_test_running:
            thread = threading.Thread(target=self._run_speed_test, daemon=True)
            thread.start()

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
        # 首轮：立即做一次大文件下载测速（50MB 级文件采样），供下载排序用
        try:
            self._run_file_speed_test()
        except Exception as e:
            logger.debug(f"[GitHubMirrorManager] 首轮文件测速失败: {e}")
        while not self._heartbeat_stop.wait(timeout=HEARTBEAT_INTERVAL):
            if not self.is_enabled():
                break
            try:
                self._start_background_speed_test()
            except Exception as e:
                logger.error(f"[GitHubMirrorManager] 心跳检测失败: {e}")

    # ==================== GitHub 文件下载测速（约 50-70MB 级真实大文件采样） ====================

    def _file_test_candidates(self) -> list:
        """
        文件测速候选：直连 + 当前 preset 的 release 镜像（完整前缀形式）

        Returns:
            list: [{"name": str, "url": str}]，name 为 "直连(github.com)" 或镜像域名
        """
        base = "https://github.com"
        cands = [{"name": "直连(github.com)", "url": GITHUB_FILE_SPEED_TEST_URL}]
        preset = self.get_current_preset() or {}
        mirrors = []
        primary = self.get_mirror_for_type("release")
        if primary:
            mirrors.append(primary)
        mirrors.extend((preset.get("fallback") or {}).get("release") or [])
        seen = set()
        for m in mirrors:
            if not m or m in seen:
                continue
            seen.add(m)
            cands.append({
                "name": m,
                "url": GITHUB_FILE_SPEED_TEST_URL.replace("https://github.com", f"https://{m}/https://github.com", 1),
            })
        return cands

    def _run_file_speed_test(self, sample_mb: int = 3, candidates: Optional[list] = None):
        """
        对候选加速方式做真实大文件下载测速：
        每个候选通过 Range 请求采样前 sample_mb MB，记录首字节延迟（TTFB）
        与平均下载速度，按「速度快、延迟低」综合排序并缓存。

        Returns:
            list: [{"name","mirror","latency_ms","speed_mbps","ok"}]，优者在前
        """
        import time as _t
        import threading as _th

        with self._file_test_lock:
            if self._file_testing:
                return self._file_test_ranking or []
            self._file_testing = True

        def _run():
            try:
                import requests as _rq
                session = _rq.Session()
                session.trust_env = False
                session.headers.update({"User-Agent": "ComfyNexus/1.0"})
                sample_bytes = sample_mb * 1024 * 1024

                def _probe(cand):
                    rec = {"name": cand["name"], "mirror": cand["name"],
                           "latency_ms": None, "speed_mbps": 0.0, "ok": False}
                    try:
                        s = _rq.Session()
                        s.trust_env = False
                        s.headers.update({"User-Agent": "ComfyNexus/1.0"})
                        t0 = _t.perf_counter()
                        r = s.get(
                            cand["url"], stream=True, timeout=(10, sample_mb + 10),
                            headers={"Range": f"bytes=0-{sample_bytes - 1}"},
                        )
                        ttfb = int((_t.perf_counter() - t0) * 1000)
                        rec["latency_ms"] = ttfb
                        if r.status_code not in (200, 206):
                            r.close()
                            return rec
                        got = 0
                        t_data0 = _t.perf_counter()
                        probe_deadline = t_data0 + max(20, sample_mb * 5)  # 采样窗口上限
                        for chunk in r.iter_content(256 * 1024):
                            got += len(chunk)
                            if got >= sample_bytes or _t.perf_counter() > probe_deadline:
                                break
                        r.close()
                        elapsed = max(_t.perf_counter() - t_data0, 0.001)
                        rec["speed_mbps"] = round(got * 8 / elapsed / 1_000_000, 2)
                        rec["ok"] = got >= sample_bytes * 0.9
                    except Exception:
                        pass
                    return rec

                # 并发探测（8 线程）：单个慢/超时镜像不拖累整体，总耗时 ≈ 最慢一个
                # 注意：as_completed 不加外层超时（_probe 内部已有连接/读取时限），
                # 否则超时异常会把已收集的全部结果一并丢弃
                from concurrent.futures import ThreadPoolExecutor, as_completed
                results = []
                cand_list = candidates if candidates is not None else self._file_test_candidates()
                with ThreadPoolExecutor(max_workers=8, thread_name_prefix="ghspeed") as pool:
                    futures = {pool.submit(_probe, c): c for c in cand_list}
                    for fut in as_completed(futures):
                        try:
                            results.append(fut.result())
                        except Exception:
                            pass
                # 综合排序：速度为主（权重 1），延迟低加分（每 100ms 折算 2 Mbps 罚分）
                def score(x):
                    if not x["ok"]:
                        return -1
                    penalty = (x["latency_ms"] or 3000) / 100.0 * 2.0
                    return x["speed_mbps"] - penalty
                results.sort(key=score, reverse=True)
                with self._file_test_lock:
                    self._file_test_ranking = results
                    self._file_test_ts = _t.time()
                best = next((r for r in results if r["ok"]), None)
                if best:
                    logger.info(
                        f"[GitHubMirrorManager] 大文件测速完成，最优: {best['name']} "
                        f"({best['speed_mbps']} Mbps, TTFB {best['latency_ms']}ms)"
                    )
            except Exception as e:
                logger.warning(f"[GitHubMirrorManager] 文件测速异常: {e}")
            finally:
                with self._file_test_lock:
                    self._file_testing = False

        _th.Thread(target=_run, daemon=True, name="github-file-speed-test").start()
        return self._file_test_ranking or []

    def get_file_speed_ranking(self, max_age: int = 1800, wait: bool = False, timeout: int = 60):
        """
        获取大文件测速排名（缓存 30 分钟；过期则后台重测）

        Args:
            wait: True 时若无有效排名则等待后台测速完成（用于下载前确保排序可用）

        Returns:
            list|None: 排名列表（优者在前）；无可用排名时 None
        """
        import time as _t
        with self._file_test_lock:
            fresh = (self._file_test_ranking and _t.time() - self._file_test_ts < max_age)
        if fresh:
            return self._file_test_ranking
        if wait:
            self._run_file_speed_test()
            deadline = _t.time() + timeout
            while _t.time() < deadline:
                _t.sleep(0.5)
                with self._file_test_lock:
                    if self._file_test_ranking and not self._file_testing:
                        return self._file_test_ranking
            return self._file_test_ranking
        # 非等待：仅触发后台
        if not self._file_testing:
            self._run_file_speed_test()
        with self._file_test_lock:
            return self._file_test_ranking or None

    def set_benchmark_result(self, result: Dict):
        """保存安装前全面测速结果（镜像速度排名 + 直连优选）"""
        self._benchmark = result

    def get_benchmark_ranking_by_type(self, kind: str = "release") -> list:
        """分类型测速排名（release / raw / zip）；无对应数据时回退 release 排名"""
        b = getattr(self, "_benchmark", None) or {}
        by_type = b.get("rankingByType") or {}
        return list(by_type.get(kind) or by_type.get("release") or [])

    def get_benchmark_mirror_ranking(self) -> list:
        """安装前全面测速的镜像速度排名（优先于心跳小文件测速）"""
        b = getattr(self, "_benchmark", None)
        return list((b or {}).get("mirrorRanking") or [])

    def get_benchmark_direct_first(self, kind: str = "github") -> bool:
        """全面测速结论：直连是否快于镜像（github/huggingface）"""
        b = getattr(self, "_benchmark", None) or {}
        return bool(b.get("bestGithubDirect" if kind == "github" else "bestHfDirect"))

    def get_release_mirror_ranking(self):
        """从文件测速排名提取镜像域名序列（直连除外），供下载排序"""
        ranking = self.get_file_speed_ranking() or []
        return [r["name"] for r in ranking
                if r.get("ok") and r["name"] != "直连(github.com)"]

    def fetch_with_fallback(
        self,
        url: str,
        url_type: str,
        timeout: int = 30,
        operation_name: str = "下载",
    ) -> Tuple[bytes, Optional[str]]:
        """
        带静默故障转移的请求

        Returns:
            (content, used_mirror)
        """
        if not self.is_enabled():
            return self._fetch_direct(url, timeout), None

        mirrors_to_try = self._get_mirror_priority_list(url_type)

        last_error = None
        for attempt, mirror in enumerate(mirrors_to_try):
            if not mirror:
                continue
            try:
                transformed_url, headers = self.transform_url(url, url_type)
                content = self._fetch_url(transformed_url, headers, mirror, timeout)

                if attempt > 0:
                    self._anti_jitter.reset_failure(mirror)

                return content, mirror

            except Exception as e:
                last_error = e
                self._anti_jitter.record_failure(mirror)
                logger.warning(
                    f"[GitHubMirrorManager] {operation_name}失败 (镜像: {mirror}): {e}"
                )
                continue

        settings = self._load_settings()
        if settings.get("fallbackToDirect", True):
            try:
                return self._fetch_direct(url, timeout), None
            except Exception as e:
                last_error = e

        raise MirrorError(f"所有镜像源均失败: {last_error}")

    def _get_mirror_priority_list(self, url_type: str) -> List[str]:
        preset = self.get_current_preset()
        if not preset:
            return []

        # 前三最优镜像（最近一次全池测速结果）优先，再补 preset 主镜像 + fallback
        top3 = (self._load_settings() or {}).get("topMirrors") or []
        primary = preset.get(url_type)
        fallbacks = preset.get("fallback", {}).get(url_type, [])

        result = list(top3)
        if primary:
            result.append(primary)
        result.extend(fallbacks)
        return list(dict.fromkeys(result))

    def _fetch_url(
        self, url: str, headers: Dict, mirror: str, timeout: int
    ) -> bytes:
        all_headers = {"User-Agent": "ComfyNexus/1.0"}
        all_headers.update(headers)
        response = requests.get(url, headers=all_headers, timeout=timeout)
        response.raise_for_status()
        return response.content

    def _fetch_direct(self, url: str, timeout: int) -> bytes:
        response = requests.get(
            url,
            headers={"User-Agent": "ComfyNexus/1.0"},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.content


class MirrorScheduler:
    """镜像调度器"""

    def __init__(self, manager: GitHubMirrorManager):
        self.manager = manager
        self.current_preset: Optional[str] = None

    def get_best_mirror(self, speed_results: Dict) -> str:
        if not speed_results:
            return "hybrid"

        scores: Dict[str, float] = {}
        for preset_name, results in speed_results.items():
            valid_latencies = [v for v in results.values() if v > 0]
            if valid_latencies:
                scores[preset_name] = sum(valid_latencies) / len(valid_latencies)

        if scores:
            return min(scores, key=scores.get)

        return "hybrid"


class MirrorSpeedTester:
    """镜像测速器"""

    def __init__(self, manager: GitHubMirrorManager):
        self.manager = manager
        self._mirror_speeds: Dict[str, float] = {}   # mirror -> MB/s
        self._detail: Dict = {}
        self._all_mirrors: list = []

    def test_all_mirrors(
        self, progress_callback: Optional[Callable] = None
    ) -> Dict:
        """
        全镜像并行测速（更科学）：
        1. 候选池 = 各 preset 主镜像 + fallback 全部 + 动态脚本镜像（更多站）
        2. 每个镜像用真实小文件下载测「延迟 + 速度」（不只 ls-remote 延迟）
        3. 并行探测（更快，20 个站几秒完成）
        返回结构保持 {preset: {github/raw/release: 延迟ms}} 兼容前端；
        额外挂 _detail 保存各镜像实测速度供排序。
        """
        import concurrent.futures as _cf

        # 1. 收集全镜像候选（去重，每个镜像测 github+raw+release 三类）
        candidates = set()
        for preset in MIRROR_PRESETS.values():
            for t in ("github", "raw", "release"):
                m = preset.get(t)
                if m:
                    candidates.add(m)
                for fb in (preset.get("fallback") or {}).get(t) or []:
                    if fb:
                        candidates.add(fb)
        # 动态脚本镜像（Github Enhancement 高可用源）
        try:
            from backend.src.utils.mirror_script import fetch_script_mirrors
            for m in (fetch_script_mirrors() or [])[:12]:
                candidates.add(m)
        except Exception:
            pass

        # 2. 并行探测每个镜像（三类 url 各自测）
        mirror_result = {}   # mirror -> {type: latency}
        with _cf.ThreadPoolExecutor(max_workers=12) as pool:
            futs = {}
            for m in candidates:
                for t in ("github", "raw", "release"):
                    futs[pool.submit(self._probe_one, m, t)] = (m, t)
            for f in _cf.as_completed(futs):
                m, t = futs[f]
                try:
                    mirror_result.setdefault(m, {})[t] = f.result()
                except Exception:
                    mirror_result.setdefault(m, {})[t] = -1

        # 3. 每个 preset 取该类型下最快镜像的延迟
        results = {}
        self._detail = mirror_result
        # 整理「全部镜像站」综合列表（延迟+速度，供前端滚动列表 + 前三最优）
        all_mirrors = []
        for m, types in mirror_result.items():
            lats = [v for v in types.values() if v is not None and v > 0]
            best_lat = min(lats) if lats else -1
            speed = self._mirror_speeds.get(m, 0.0)
            # 综合分：延迟低 + 速度快 → 分数高（用于排序前三最优）
            score = (speed * 1000 / max(best_lat, 1)) if best_lat > 0 else 0.0
            all_mirrors.append({
                "mirror": m,
                "bestLatency": best_lat,
                "speed": speed,
                "score": round(score, 2),
                "types": types,
            })
        # 排序：可用优先，再按综合分降序
        all_mirrors.sort(key=lambda x: (x["bestLatency"] < 0, -x["score"], x["bestLatency"]))
        self._all_mirrors = all_mirrors

        for preset_name, preset in MIRROR_PRESETS.items():
            results[preset_name] = {}
            for t in ("github", "raw", "release"):
                # 该 preset 相关镜像 = 主镜像 + fallback
                pool_mirrors = [preset.get(t)] if preset.get(t) else []
                pool_mirrors += (preset.get("fallback") or {}).get(t) or []
                pool_mirrors = [m for m in pool_mirrors if m]
                lat = -1
                for m in pool_mirrors:
                    v = mirror_result.get(m, {}).get(t, -1)
                    if v is not None and v > 0 and (lat < 0 or v < lat):
                        lat = v
                results[preset_name][t] = lat
                if progress_callback:
                    progress_callback(preset_name, t, lat)

        return results

    def _probe_one(self, mirror: str, url_type: str) -> int:
        """探测单个镜像的某类 url：返回延迟 ms（-1 不可用）；顺带记录下载速度"""
        # github 类型也用 HTTP 探测（git clone 可用性由 git ls-remote 单独测，
        # 这里统一 HTTP 更快速、且能测出下载速度）
        return self._test_mirror_speed(mirror, url_type)

    def _test_git_mirror_speed(self, mirror: str) -> int:
        test_repo = "https://github.com/git/git"
        mirror_url = test_repo.replace("https://github.com", f"https://{mirror}/https://github.com", 1)

        try:
            start_time = time.time()
            result = subprocess.run(
                ["git", "ls-remote", "--exit-code", mirror_url, "HEAD"],
                capture_output=True,
                timeout=12,
                text=True,
            )
            elapsed = int((time.time() - start_time) * 1000)

            if result.returncode == 0:
                return elapsed
            else:
                logger.debug(f"[MirrorSpeedTester] git ls-remote 失败 ({mirror}): {result.stderr}")
                return -1

        except subprocess.TimeoutExpired:
            logger.debug(f"[MirrorSpeedTester] git ls-remote 超时 ({mirror})")
            return -1
        except FileNotFoundError:
            logger.debug("[MirrorSpeedTester] git 命令未找到")
            return -1
        except Exception as e:
            logger.debug(f"[MirrorSpeedTester] git ls-remote 异常 ({mirror}): {e}")
            return -1

    def _test_mirror_speed(self, mirror: str, url_type: str) -> int:
        test_url = SPEED_TEST_FILES.get(url_type)
        if not test_url:
            return -1

        try:
            transformed_url, headers = self._transform_test_url(
                test_url, mirror, url_type
            )
            all_headers = {"User-Agent": "ComfyNexus/1.0"}
            all_headers.update(headers)

            start_time = time.time()
            response = requests.get(
                transformed_url,
                headers=all_headers,
                timeout=(6, 10),
                stream=True,
            )
            response.raise_for_status()

            chunk_size = 8192
            downloaded = 0
            max_download = 256 * 1024   # 采样 256KB（比 64KB 更能反映真实速度）
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    downloaded += len(chunk)
                    if downloaded >= max_download:
                        break

            elapsed = int((time.time() - start_time) * 1000)
            # 记录下载速度（MB/s）供「更科学」的排序
            speed_mbps = (downloaded / (elapsed / 1000)) / 1048576 if elapsed > 0 else 0.0
            self._mirror_speeds[mirror] = round(speed_mbps, 2)
            return elapsed

        except Exception as e:
            logger.debug(f"[MirrorSpeedTester] 测速失败 ({mirror}, {url_type}): {e}")
            return -1

    def _transform_test_url(
        self, url: str, mirror: str, url_type: str
    ) -> Tuple[str, Dict]:
        headers = {}
        if mirror in MIRROR_USER_AGENTS:
            headers["User-Agent"] = MIRROR_USER_AGENTS[mirror]
        if url_type == "raw":
            headers["Referer"] = "https://github.com/"

        transformed = self.manager._do_transform(url, mirror, url_type)
        return transformed, headers


class MirrorError(Exception):
    """镜像源错误"""

    pass


github_mirror_manager = GitHubMirrorManager()
