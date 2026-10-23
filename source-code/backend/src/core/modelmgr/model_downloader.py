"""
多源模型下载器

支持的下载源（按 URL 自动识别）：
- huggingface.co      官方源，失败自动切换 hf-mirror.com 国内镜像重试
- hf-mirror.com       HuggingFace 国内镜像
- modelscope.cn       魔搭社区（阿里）
- civitai.com         Civitai（支持 URL 里带 ?token=）
- 其它任意直链

特性：
- 串行队列下载（同时最多 1 个任务占盘/占带宽，其余排队）
- 断点续传（.part 文件 + Range 请求，服务器不支持时自动退回全量）
- 下载完成后自动登记进扫描缓存（免重扫）
- 进度/速度/取消由任务字典承载，前端轮询 model_get_download_status
"""

import os
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional

import requests

from backend.src.utils.aria2_helper import aria2_download
from backend.src.utils.logger import app_logger as logger

CHUNK_SIZE = 1 << 20  # 1MB


def detect_source(url: str) -> str:
    """根据 URL 识别下载源"""
    host = urllib.parse.urlparse(url).netloc.lower()
    if "huggingface.co" in host:
        return "huggingface"
    if "hf-mirror.com" in host:
        return "hf-mirror"
    if "modelscope.cn" in host:
        return "modelscope"
    if "civitai.com" in host:
        return "civitai"
    return "direct"


def suggest_filename(url: str, default: str = "") -> str:
    """从 URL 推断文件名（解码百分号编码）"""
    path = urllib.parse.urlparse(url).path
    name = urllib.parse.unquote(os.path.basename(path)) if path else ""
    if not name or "." not in name:
        return default
    return name


class DownloadTask:
    """单个下载任务的运行状态"""

    def __init__(self, task_id: str, url: str, dest_path: str, model_type: str, filename: str, source: str):
        self.task_id = task_id
        self.url = url
        self.dest_path = dest_path
        self.model_type = model_type
        self.filename = filename
        self.source = source
        self.status = "queued"       # queued/downloading/completed/failed/cancelled
        self.error = ""
        self.downloaded = 0
        self.total = 0
        self.speed = 0.0             # bytes/s
        self.started_at = 0.0
        self.finished_at = 0.0

    def to_dict(self) -> dict:
        percent = 0
        if self.total > 0:
            percent = min(100, int(self.downloaded * 100 / self.total))
        return {
            "taskId": self.task_id,
            "url": self.url,
            "destPath": self.dest_path,
            "modelType": self.model_type,
            "filename": self.filename,
            "source": self.source,
            "status": self.status,
            "error": self.error,
            "downloaded": self.downloaded,
            "total": self.total,
            "percent": percent,
            "speed": self.speed,
            "elapsed": (self.finished_at or time.time()) - self.started_at if self.started_at else 0,
        }


class ModelDownloader:
    """多源模型下载器（串行队列 + 断点续传）"""

    def __init__(self, scanner=None):
        self._scanner = scanner
        self._tasks: Dict[str, DownloadTask] = {}
        self._order: List[str] = []
        self._queue: List[str] = []
        self._cancel_events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._worker_running = False

    # ---------- 公共 API ----------

    def start_download(self, url: str, dest_dir: Path, model_type: str,
                       filename: str = "") -> Dict:
        """
        加入下载队列

        Args:
            url: 下载地址
            dest_dir: 目标目录（models/<type>）
            model_type: 模型分类（目录名）
            filename: 目标文件名（空则从 URL 推断）

        Returns:
            {"success": bool, "taskId": str, "error_message": str(可选)}
        """
        url = (url or "").strip()
        if not url:
            return {"success": False, "error_message": "下载地址不能为空"}
        if not url.lower().startswith(("http://", "https://")):
            return {"success": False, "error_message": "仅支持 http/https 下载地址"}

        source = detect_source(url)
        if not filename:
            filename = suggest_filename(url)
        if not filename:
            return {"success": False, "error_message": "无法从 URL 推断文件名，请手动指定"}

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename

        if dest_path.exists() and dest_path.stat().st_size > 0:
            return {"success": False, "error_message": f"目标文件已存在: {filename}"}

        task_id = f"dl_{int(time.time() * 1000)}_{len(self._tasks) % 10000}"
        task = DownloadTask(task_id, url, str(dest_path), model_type, filename, source)

        with self._lock:
            self._tasks[task_id] = task
            self._order.append(task_id)
            self._queue.append(task_id)
            self._cancel_events[task_id] = threading.Event()

        self._ensure_worker()
        logger.info(f"[ModelDownloader] 任务入队: {filename} ({source})")
        return {"success": True, "taskId": task_id, "source": source}

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            ev = self._cancel_events.get(task_id)
            task = self._tasks.get(task_id)
        if ev is None or task is None:
            return False
        if task.status in ("completed", "failed", "cancelled"):
            return True
        ev.set()
        if task.status == "queued":
            task.status = "cancelled"
            task.finished_at = time.time()
        return True

    def get_status(self) -> Dict:
        """全部任务状态（含历史，前端按需展示）"""
        with self._lock:
            tasks = [self._tasks[tid].to_dict() for tid in self._order if tid in self._tasks]
        # 最多保留 50 条历史，防 UI 内存膨胀
        return {"success": True, "tasks": tasks[-50:]}

    def clear_finished(self) -> None:
        with self._lock:
            keep = [tid for tid in self._order
                    if self._tasks[tid].status in ("queued", "downloading")]
            self._order = keep
            self._tasks = {tid: self._tasks[tid] for tid in keep}

    # ---------- 内部实现 ----------

    def _ensure_worker(self) -> None:
        if self._worker_running:
            return
        self._worker_running = True
        threading.Thread(target=self._worker_loop, daemon=True, name="model-downloader").start()

    def _worker_loop(self) -> None:
        while True:
            with self._lock:
                task_id = self._queue.pop(0) if self._queue else None
            if task_id is None:
                self._worker_running = False
                return

            task = self._tasks.get(task_id)
            if task is None or task.status == "cancelled":
                continue

            cancel_ev = self._cancel_events.get(task_id)
            self._run_task(task, cancel_ev)

    def _hf_mirror_url(self, url: str) -> str:
        """huggingface.co → hf-mirror.com 镜像替换"""
        if url.startswith("https://huggingface.co/"):
            return "https://hf-mirror.com/" + url[len("https://huggingface.co/"):]
        return url

    def _run_task(self, task: DownloadTask, cancel_ev: Optional[threading.Event]) -> None:
        task.status = "downloading"
        task.started_at = time.time()
        dest = Path(task.dest_path)
        part_file = dest.with_suffix(dest.suffix + ".part")
        urls_to_try = [task.url]

        # HuggingFace 镜像加速：用户在设置里启用了 HF 镜像时，
        # 把官方 URL 改写为当前最优镜像（默认 hf-mirror.com）；
        # 改写后的 URL 放在最前，官方 URL 保留作 fallback。
        if task.source == "huggingface":
            try:
                from backend.src.utils.hf_mirror import hf_mirror_manager
                mirrored = hf_mirror_manager.transform_url(task.url)
                if mirrored != task.url:
                    urls_to_try.insert(0, mirrored)
            except Exception:
                pass
            # 官方直连失败自动切镜像兜底（未启用镜像设置时仍可用）
            urls_to_try.append(self._hf_mirror_url(task.url))

        last_error = ""
        # 统一下载缓存：先落全局缓存（重装/多板块复用、断点续传），再复制到目标目录
        from backend.src.utils import download_cache as dc
        try:
            def _cb(done, total):
                task.downloaded = done
                task.total = total or task.total
            cached = dc.fetch(task.url, task.filename, size_hint=int(task.total or 0),
                              progress_cb=_cb,
                              extra_urls=urls_to_try[1:] or None,
                              cancel_ev=cancel_ev,
                              log_fn=lambda m: logger.info(f"[ModelDownloader] {m}"))
            if cached.resolve() != dest.resolve():
                import shutil as _sh
                dest.parent.mkdir(parents=True, exist_ok=True)
                _sh.copy2(str(cached), str(dest))
            task.status = "completed"
            task.finished_at = time.time()
            if self._scanner is not None:
                try:
                    self._scanner.register_file(str(dest), task.model_type)
                except Exception:
                    pass
            logger.info(f"[ModelDownloader] 完成(缓存): {task.filename}")
            return
        except Exception as e:
            logger.warning(f"[ModelDownloader] 缓存下载失败，回退单线程: {e}")

        for url in urls_to_try:
            try:
                if self._download_one(task, url, part_file, cancel_ev):
                    # 成功：改名落位 + 登记
                    if part_file.exists():
                        part_file.replace(dest)
                    task.status = "completed"
                    task.finished_at = time.time()
                    if self._scanner is not None:
                        try:
                            self._scanner.register_file(str(dest), task.model_type)
                        except Exception:
                            pass
                    logger.info(f"[ModelDownloader] 完成: {task.filename} ({task.total / 1024 / 1024:.1f} MB)")
                    return
                else:
                    task.status = "cancelled"
                    task.finished_at = time.time()
                    return
            except Exception as e:
                last_error = str(e)
                logger.warning(f"[ModelDownloader] 下载失败 ({url}): {e}")

        task.status = "failed"
        task.error = last_error or "下载失败"
        task.finished_at = time.time()

    def _download_one(self, task: DownloadTask, url: str, part_file: Path,
                      cancel_ev: Optional[threading.Event]) -> bool:
        """单 URL 下载（支持 .part 断点续传），返回 False 表示被取消"""
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ComfyNexus/1.3.0"}
        existing = part_file.stat().st_size if part_file.exists() else 0
        if existing > 0:
            headers["Range"] = f"bytes={existing}-"

        with requests.get(url, stream=True, timeout=(30, 120), headers=headers, allow_redirects=True) as resp:
            if resp.status_code == 416:
                # 断点越界：服务端文件可能已变化，从头来
                existing = 0
                part_file.unlink(missing_ok=True)
                headers.pop("Range", None)
                resp.close()
                resp = requests.get(url, stream=True, timeout=(30, 120), headers=headers, allow_redirects=True)
            resp.raise_for_status()

            # Civitai 等 302 后的最终文件名
            cd = resp.headers.get("Content-Disposition", "")
            if cd and "filename=" in cd and not task.filename.startswith("(from-civitai)"):
                try:
                    fn = cd.split("filename=")[-1].strip().strip('"').strip("'")
                    if fn and "." in fn and fn != task.filename:
                        # 沿用已确定的文件名（避免中文乱码文件名），只记录日志
                        logger.debug(f"[ModelDownloader] 服务端文件名: {fn}")
                except Exception:
                    pass

            if resp.status_code == 200 and existing > 0:
                # 服务器不支持 Range（返回全量 200）：从头写
                existing = 0

            total_header = resp.headers.get("Content-Length")
            task.total = (int(total_header) + existing) if total_header else (existing or 0)
            task.downloaded = existing

            mode = "ab" if existing > 0 else "wb"
            last_speed_calc = time.time()
            last_downloaded = existing

            with open(part_file, mode) as f:
                for chunk in resp.iter_content(CHUNK_SIZE):
                    if cancel_ev is not None and cancel_ev.is_set():
                        logger.info(f"[ModelDownloader] 已取消: {task.filename}")
                        return False
                    if chunk:
                        f.write(chunk)
                        task.downloaded += len(chunk)

                    now = time.time()
                    if now - last_speed_calc >= 1.0:
                        task.speed = (task.downloaded - last_downloaded) / (now - last_speed_calc)
                        last_speed_calc = now
                        last_downloaded = task.downloaded
            return True
