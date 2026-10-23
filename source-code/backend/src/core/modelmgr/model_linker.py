"""
模型网络链接关联模块

功能：
- ModelLinkStore：本地模型文件 <-> 网络链接 的关联持久化（model_links.json，防抖落盘）
- ModelLinker：网络搜索（魔搭社区 ModelScope / HuggingFace）+ 关联管理 + 批量同步

搜索源（本机已实测验证）：
- 魔搭社区（ModelScope）:
    * 搜索: PUT https://modelscope.cn/api/v1/models  匿名可用
    * 仓库文件列表: GET /api/v1/models/{owner}/{name}/repo/files?Revision=master&Root=
    * 文件直链: https://modelscope.cn/models/{owner}/{name}/resolve/master/{file_path}
- HuggingFace:
    * 官方 huggingface.co 国内通常不可达，API 与下载一律走 hf-mirror.com 镜像
    * 搜索: GET https://hf-mirror.com/api/models?search=...&limit=...
    * 仓库文件列表: GET https://hf-mirror.com/api/models/{repo_id}/tree/main
    * 文件直链: https://hf-mirror.com/{repo_id}/resolve/main/{file_path}

匹配策略（auto / 魔搭优先）：
1. 用模型文件名（去扩展名、去量化后缀）搜索魔搭 → 取下载量最高的仓库；
2. 在该仓库文件树里找与本地文件名最接近的模型文件（同名 > 包含 > 后缀相同）；
3. 找不到时（或 default_source=huggingface）按同策略搜 HuggingFace。
"""

import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

from backend.src.utils.logger import app_logger as logger

# 模型文件扩展名（与 model_scanner 保持一致）
MODEL_EXTS = {
    ".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx",
    ".sft", ".engine", ".trt", ".xml", ".param",
}

_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}

_MS_API = "https://modelscope.cn/api/v1/models"
_HF_API = "https://hf-mirror.com"

# 搜索/列举接口超时（秒）——批量同步对每个模型都要请求，不能太长
_HTTP_TIMEOUT = (10, 20)


def _base_name(filename: str) -> str:
    """文件名去扩展名，统一小写比较"""
    p = Path(filename)
    return p.stem.strip().lower()


def _tokens(name: str) -> set:
    """把名字拆成 token 集合（按 - _ . 空格 切分），用于模糊匹配"""
    raw = _base_name(name)
    for ch in "-_.":
        raw = raw.replace(ch, " ")
    return {t for t in raw.split() if t}


class ModelLinkStore:
    """模型网络链接关联存储（model_links.json，防抖落盘）"""

    SAVE_DEBOUNCE = 1.0

    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            from backend.src.utils.paths import get_cache_dir
            cache_dir = get_cache_dir("model_library")
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "model_links.json"
        self._lock = threading.Lock()
        self._links: Dict[str, dict] = {}   # 模型 id -> {url, source, repoName, linkedAt, manual}
        self._dirty = False
        self._timer: Optional[threading.Timer] = None
        self._load()

    def _load(self) -> None:
        if not self._file.exists():
            return
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._links = {k: v for k, v in (data.get("links") or {}).items() if isinstance(v, dict)}
        except Exception as e:
            logger.warning(f"[ModelLinkStore] 关联缓存读取失败（忽略）: {e}")

    def _schedule_save(self) -> None:
        self._dirty = True
        if self._timer is not None:
            return

        def _delayed():
            self._timer = None
            if self._dirty:
                self._flush_locked()

        self._timer = threading.Timer(self.SAVE_DEBOUNCE, _delayed)
        self._timer.daemon = True
        self._timer.start()

    def _flush_locked(self) -> None:
        try:
            tmp = self._file.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"links": self._links}, f, ensure_ascii=False)
            tmp.replace(self._file)
            self._dirty = False
        except Exception as e:
            logger.error(f"[ModelLinkStore] 关联缓存写入失败: {e}")

    def flush(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._dirty:
                self._flush_locked()

    def get(self, model_id: str) -> Optional[dict]:
        with self._lock:
            return self._links.get(model_id)

    def get_all(self) -> Dict[str, dict]:
        with self._lock:
            return dict(self._links)

    def set(self, model_id: str, url: str, source: str,
            repo_name: str = "", manual: bool = False) -> dict:
        """设置/覆盖一条关联"""
        entry = {
            "url": url,
            "source": source,          # modelscope / huggingface / direct ...
            "repoName": repo_name or "",
            "linkedAt": time.time(),
            "manual": bool(manual),
        }
        with self._lock:
            self._links[model_id] = entry
            self._schedule_save()
        return entry

    def remove(self, model_id: str) -> bool:
        with self._lock:
            if model_id in self._links:
                del self._links[model_id]
                self._schedule_save()
                return True
            return False


class ModelLinker:
    """模型网络链接搜索与关联"""

    def __init__(self, store: Optional[ModelLinkStore] = None):
        self._store = store or ModelLinkStore()
        self._lock = threading.Lock()
        # 后台批量同步状态
        self._sync_running = False
        self._sync_stop = False
        self._sync_progress = {"total": 0, "done": 0, "matched": 0,
                               "current": "", "finished": False, "error": ""}

    @property
    def store(self) -> ModelLinkStore:
        return self._store

    # ---------- 魔搭社区（ModelScope） ----------

    def search_modelscope(self, keyword: str, limit: int = 8) -> List[dict]:
        """搜索魔搭模型仓库，返回候选列表"""
        keyword = (keyword or "").strip()
        if not keyword:
            return []
        body = {"Name": keyword, "PageSize": max(1, min(limit, 20)),
                "PageNumber": 1, "SortBy": "Default", "Target": ""}
        try:
            r = requests.put(_MS_API, headers={**_UA, "Content-Type": "application/json",
                                               "Origin": "https://modelscope.cn",
                                               "Referer": "https://modelscope.cn/models"},
                             json=body, timeout=_HTTP_TIMEOUT)
            if r.status_code != 200:
                logger.warning(f"[ModelLinker] 魔搭搜索 HTTP {r.status_code}: {keyword}")
                return []
            models = (r.json() or {}).get("Data", {}).get("Models", []) or []
            out = []
            for m in models:
                path = m.get("Path") or ""      # 仓库 owner
                name = m.get("Name") or ""      # 仓库名
                if not path or not name:
                    continue
                repo_id = f"{path}/{name}"
                out.append({
                    "repoId": repo_id,
                    "name": m.get("ChineseName") or name,
                    "repoName": name,
                    "source": "modelscope",
                    "downloads": m.get("Downloads") or 0,
                    "aigcType": m.get("AigcType") or "",
                    "pageUrl": f"https://modelscope.cn/models/{repo_id}",
                })
            out.sort(key=lambda x: -(x.get("downloads") or 0))
            return out
        except Exception as e:
            logger.warning(f"[ModelLinker] 魔搭搜索失败: {keyword} -> {e}")
            return []

    def list_modelscope_files(self, repo_id: str) -> List[dict]:
        """列举魔搭仓库内的模型文件（递归，含子目录）"""
        results: List[dict] = []

        def _walk(root: str):
            url = (f"https://modelscope.cn/api/v1/models/{repo_id}"
                   f"/repo/files?Revision=master&Root={root}")
            try:
                r = requests.get(url, headers=_UA, timeout=_HTTP_TIMEOUT)
                if r.status_code != 200:
                    return
                files = (r.json() or {}).get("Data", {}).get("Files", []) or []
            except Exception:
                return
            for f in files:
                p = f.get("Path") or ""
                if f.get("Type") == "tree":
                    _walk(p)
                elif Path(p).suffix.lower() in MODEL_EXTS:
                    results.append({
                        "path": p,
                        "size": f.get("Size") or 0,
                        "url": f"https://modelscope.cn/models/{repo_id}/resolve/master/{p}",
                    })

        try:
            _walk("")
        except Exception as e:
            logger.warning(f"[ModelLinker] 魔搭仓库文件列举失败: {repo_id} -> {e}")
        return results

    # ---------- HuggingFace（经 hf-mirror） ----------

    def search_huggingface(self, keyword: str, limit: int = 8) -> List[dict]:
        """搜索 HuggingFace（走 hf-mirror 镜像 API），返回候选列表"""
        keyword = (keyword or "").strip()
        if not keyword:
            return []
        try:
            r = requests.get(f"{_HF_API}/api/models",
                             params={"search": keyword, "limit": max(1, min(limit, 20))},
                             headers=_UA, timeout=_HTTP_TIMEOUT)
            if r.status_code != 200:
                logger.warning(f"[ModelLinker] HF 搜索 HTTP {r.status_code}: {keyword}")
                return []
            models = r.json() or []
            out = []
            for m in models:
                repo_id = m.get("id") or m.get("modelId") or ""
                if not repo_id:
                    continue
                out.append({
                    "repoId": repo_id,
                    "name": repo_id.split("/")[-1],
                    "repoName": repo_id.split("/")[-1],
                    "source": "huggingface",
                    "downloads": m.get("downloads") or 0,
                    "aigcType": "",
                    "pageUrl": f"https://huggingface.co/{repo_id}",
                })
            out.sort(key=lambda x: -(x.get("downloads") or 0))
            return out
        except Exception as e:
            logger.warning(f"[ModelLinker] HF 搜索失败: {keyword} -> {e}")
            return []

    def list_huggingface_files(self, repo_id: str) -> List[dict]:
        """列举 HF 仓库内的模型文件（走 hf-mirror，递归子目录）"""
        results: List[dict] = []

        def _walk(path: str):
            url = f"{_HF_API}/api/models/{repo_id}/tree/main"
            if path:
                url += f"/{path}"
            try:
                r = requests.get(url, headers=_UA, timeout=_HTTP_TIMEOUT)
                if r.status_code != 200:
                    return
                items = r.json() or []
            except Exception:
                return
            for it in items:
                p = it.get("path") or ""
                if it.get("type") == "directory":
                    _walk(p)
                elif Path(p).suffix.lower() in MODEL_EXTS:
                    results.append({
                        "path": p,
                        "size": (it.get("size") or 0),
                        "url": f"{_HF_API}/{repo_id}/resolve/main/{p}",
                    })

        try:
            _walk("")
        except Exception as e:
            logger.warning(f"[ModelLinker] HF 仓库文件列举失败: {repo_id} -> {e}")
        return results

    # ---------- 候选链接（手动关联页直接可选的链接列表） ----------

    def get_candidates(self, filename: str, source: str = "auto",
                       limit: int = 6) -> Dict:
        """
        为单个模型文件生成候选下载链接列表（供手动关联页直接选择）。

        Args:
            filename: 本地模型文件名
            source: modelscope / huggingface / auto（默认魔搭，没有再 HF）
            limit: 每个源最多返回的仓库数

        Returns:
            {"success": bool, "filename": str, "candidates": [
                {"repoId","source","downloads","url","filePath","size","pageUrl"}
            ]}
        """
        filename = (filename or "").strip()
        stem = _base_name(filename)
        if not stem:
            return {"success": False, "error_message": "文件名为空", "candidates": []}

        candidates: List[dict] = []

        def _collect(searcher, lister, source_tag):
            repos = searcher(stem, limit=limit)
            for repo in repos:
                files = lister(repo["repoId"])
                # 优先精确同名；否则按 token 重合度排序取最接近的
                best = self._best_file(files, stem)
                if best:
                    candidates.append({
                        "repoId": repo["repoId"],
                        "repoName": repo.get("name") or repo["repoId"],
                        "source": source_tag,
                        "downloads": repo.get("downloads") or 0,
                        "url": best["url"],
                        "filePath": best["path"],
                        "size": best.get("size") or 0,
                        "pageUrl": repo.get("pageUrl", ""),
                    })

        try:
            if source == "modelscope":
                _collect(self.search_modelscope, self.list_modelscope_files, "modelscope")
            elif source == "huggingface":
                _collect(self.search_huggingface, self.list_huggingface_files, "huggingface")
            else:  # auto：魔搭优先，空则 HF
                _collect(self.search_modelscope, self.list_modelscope_files, "modelscope")
                if not candidates:
                    _collect(self.search_huggingface, self.list_huggingface_files, "huggingface")
        except Exception as e:
            logger.warning(f"[ModelLinker] 候选链接生成失败: {filename} -> {e}")
            return {"success": False, "error_message": str(e), "candidates": []}

        return {"success": True, "filename": filename, "candidates": candidates}

    @staticmethod
    def _best_file(files: List[dict], stem: str) -> Optional[dict]:
        """从仓库文件中挑与目标名最匹配的一个：同名 > token 重合最多 > 最大文件"""
        if not files:
            return None
        target_tokens = _tokens(stem)

        def _score(f: dict) -> tuple:
            fstem = _base_name(Path(f["path"]).name)
            if fstem == stem:
                return (3, 1.0, f.get("size") or 0)
            overlap = len(target_tokens & _tokens(fstem))
            # stem 完全包含于文件名（或反之）
            contains = 1 if (stem in fstem or fstem in stem) else 0
            return (1 + contains, overlap, f.get("size") or 0)

        return max(files, key=_score)

    # ---------- 单模型自动关联（用于批量同步） ----------

    def auto_link_one(self, model_id: str, filename: str,
                      source: str = "auto") -> Optional[dict]:
        """为一个模型自动找链接并保存关联，返回关联条目（未找到返回 None）"""
        result = self.get_candidates(filename, source=source, limit=4)
        if not result.get("success") or not result.get("candidates"):
            return None
        best = result["candidates"][0]
        return self._store.set(
            model_id, best["url"], best["source"],
            repo_name=best.get("repoId", ""), manual=False,
        )

    # ---------- 批量同步（后台线程） ----------

    def start_sync(self, models: List[dict], source: str = "auto") -> Dict:
        """
        启动后台批量同步：为每个模型（无手动关联的）自动关联网络链接。

        Args:
            models: [{"id":..., "filename":...}, ...]
            source: modelscope / huggingface / auto
        """
        with self._lock:
            if self._sync_running:
                return {"success": False, "error_message": "同步已在进行中"}
            self._sync_running = True
            self._sync_stop = False
            self._sync_progress = {"total": len(models), "done": 0, "matched": 0,
                                   "current": "", "finished": False, "error": ""}

        threading.Thread(target=self._sync_worker, args=(list(models), source),
                         daemon=True, name="model-link-sync").start()
        return {"success": True, "total": len(models)}

    def stop_sync(self) -> None:
        self._sync_stop = True

    def get_sync_status(self) -> Dict:
        with self._lock:
            return {
                "success": True,
                "running": self._sync_running,
                **dict(self._sync_progress),
            }

    def _sync_worker(self, models: List[dict], source: str) -> None:
        try:
            existing = self._store.get_all()
            for m in models:
                if self._sync_stop:
                    break
                mid = m.get("id") or ""
                fname = m.get("filename") or ""
                with self._lock:
                    self._sync_progress["current"] = fname
                if not mid or not fname:
                    with self._lock:
                        self._sync_progress["done"] += 1
                    continue
                # 手动设置的关联不覆盖；已有自动关联的也跳过（幂等）
                prev = existing.get(mid)
                if prev and prev.get("manual"):
                    with self._lock:
                        self._sync_progress["done"] += 1
                        self._sync_progress["matched"] += 1
                    continue
                if prev:
                    with self._lock:
                        self._sync_progress["done"] += 1
                        self._sync_progress["matched"] += 1
                    continue
                try:
                    linked = self.auto_link_one(mid, fname, source=source)
                except Exception as e:
                    logger.warning(f"[ModelLinker] 同步单模型失败: {fname} -> {e}")
                    linked = None
                with self._lock:
                    self._sync_progress["done"] += 1
                    if linked:
                        self._sync_progress["matched"] += 1
            with self._lock:
                self._sync_progress["finished"] = True
                self._sync_progress["current"] = ""
        except Exception as e:
            logger.error(f"[ModelLinker] 批量同步失败: {e}", exc_info=True)
            with self._lock:
                self._sync_progress["error"] = str(e)
                self._sync_progress["finished"] = True
        finally:
            with self._lock:
                self._sync_running = False
