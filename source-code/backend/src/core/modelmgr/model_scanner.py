"""
本地模型扫描器

扫描 ComfyUI 环境 models/ 目录下全部子目录（checkpoints / loras / vae / controlnet 等），
产出统一的 ModelInfo 列表供前端展示。

设计要点：
- 全量 stat 扫描（万级文件在 NTFS 上 <2s），结果缓存 JSON 防抖落盘
  （沿用 gallery/storage 的防抖 + flush 模式，避免 O(n²) 全量重写）。
- 已知目录给出中文标签与默认下载归类；未知目录也纳入扫描（不漏文件）。
"""

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from backend.src.utils.logger import app_logger as logger

# ComfyUI 官方模型目录分类（label 用于前端展示）
MODEL_DIR_LABELS: Dict[str, str] = {
    "checkpoints": "大模型 (Checkpoint)",
    "diffusion_models": "扩散模型 (Diffusion)",
    "unet": "UNet 模型",
    "loras": "LoRA",
    "vae": "VAE",
    "text_encoders": "文本编码器",
    "clip": "CLIP",
    "clip_vision": "CLIP Vision",
    "controlnet": "ControlNet",
    "upscale_models": "放大模型",
    "embeddings": "Embedding",
    "style_models": "风格模型",
    "photomaker": "PhotoMaker",
    "hypernetworks": "HyperNetwork",
    "ipadapter": "IPAdapter",
    "instantid": "InstantID",
    "sams": "SAM",
    "ultralytics": "Ultralytics",
    "vae_approx": "VAE Approx (预览)",
    "audio_encoders": "音频编码器",
    "diffusers": "Diffusers 模型",
    "gligen": "GLIGEN",
    "model_patches": "模型补丁",
    "latent_upscale_models": "潜在放大模型",
    "t2i_adapter": "T2I Adapter",
    "frame_interpolation": "帧插值",
    "classifiers": "分类器",
    "audiodit": "AudioDiT (音频)",
    "background_removal": "背景移除",
    "detection": "目标检测",
    "geometry_estimation": "几何估计",
    "optical_flow": "光流估计",
    "semantic_bridge": "语义桥接",
    "configs": "配置",
}

# 扫描时跳过的目录名
_SKIP_DIRS = {"put_*models_here", "__pycache__"}
# 模型文件扩展名（之外的文件忽略，如 .txt/.json 说明文件）
MODEL_EXTS = {
    ".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx",
    ".sft", ".engine", ".trt", ".xml", ".param",
}


class ModelInfo:
    """单个模型文件的元数据"""

    __slots__ = ("id", "filename", "model_type", "path", "size", "modified_at")

    def __init__(self, filename: str, model_type: str, path: str, size: int, modified_at: float):
        self.filename = filename
        self.model_type = model_type
        self.path = path
        self.size = size
        self.modified_at = modified_at
        self.id = hashlib.md5(path.lower().encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "modelType": self.model_type,
            "path": self.path,
            "size": self.size,
            "modifiedAt": self.modified_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ModelInfo":
        info = cls(
            filename=d.get("filename", ""),
            model_type=d.get("modelType", d.get("model_type", "other")),
            path=d.get("path", ""),
            size=d.get("size", 0),
            modified_at=d.get("modifiedAt", d.get("modified_at", 0.0)),
        )
        return info


class ModelScanner:
    """本地模型扫描器（带防抖缓存落盘）"""

    # 防抖落盘窗口（秒）
    SAVE_DEBOUNCE = 1.0

    def __init__(self, cache_dir: Optional[Path] = None):
        from backend.src.utils.paths import get_cache_dir
        self._cache_dir = Path(cache_dir) if cache_dir else get_cache_dir("model_library")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_file = self._cache_dir / "models.json"

        self._models: List[ModelInfo] = []
        self._models_by_key: Dict[str, ModelInfo] = {}
        self._lock = threading.Lock()
        self._dirty = False
        self._save_timer: Optional[threading.Timer] = None
        self._scanning = False
        self._scan_stop = False
        self.last_scan_time: Optional[float] = None

    # ---------- 缓存 ----------

    def _load_cache(self, models_root: str) -> None:
        if self._cache_file.exists():
            try:
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("modelsRoot") == models_root:
                    # 目录指纹校验：models 根目录 mtime 变化（新增/删除模型）→ 缓存失效重扫
                    # （否则新放入的模型永远不显示，直到用户手动强制重扫）
                    # 注意：多根时 models_root 是 "path1|path2" 连接形式，取第一个根做指纹
                    try:
                        root_path = models_root.split("|")[0]
                        root_mtime = Path(root_path).stat().st_mtime
                        cached_mtime = data.get("rootMtime", 0)
                        if root_mtime and cached_mtime and abs(root_mtime - cached_mtime) > 1:
                            logger.info(f"[ModelScanner] 目录已变化（mtime {cached_mtime} -> {root_mtime}），缓存失效")
                            return
                    except OSError:
                        pass
                    self._models = [ModelInfo.from_dict(d) for d in data.get("models", [])]
                    self._models_by_key = {m.path.lower(): m for m in self._models}
                    self.last_scan_time = data.get("lastScanTime")
                    logger.info(f"[ModelScanner] 缓存加载: {len(self._models)} 个模型")
            except Exception as e:
                logger.warning(f"[ModelScanner] 缓存读取失败，将重新扫描: {e}")

    def _schedule_save(self) -> None:
        self._dirty = True
        if self._save_timer is not None:
            return

        def _delayed():
            self._save_timer = None
            if self._dirty:
                self._write_cache()

        self._save_timer = threading.Timer(self.SAVE_DEBOUNCE, _delayed)
        self._save_timer.daemon = True
        self._save_timer.start()

    def _write_cache(self) -> None:
        try:
            tmp = self._cache_file.with_suffix(".json.tmp")
            # 记录 models 根目录 mtime（多根时取主根），供缓存失效校验
            root_mtime = 0.0
            try:
                _mr = getattr(self, "_models_root", "")
                if _mr:
                    root_mtime = Path(_mr.split("|")[0]).stat().st_mtime
            except OSError:
                pass
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "modelsRoot": getattr(self, "_models_root", ""),
                    "rootMtime": root_mtime,
                    "lastScanTime": self.last_scan_time,
                    "models": [m.to_dict() for m in self._models],
                }, f, ensure_ascii=False)
            tmp.replace(self._cache_file)
            self._dirty = False
        except Exception as e:
            logger.error(f"[ModelScanner] 缓存写入失败: {e}")

    def flush(self) -> None:
        if self._save_timer is not None:
            self._save_timer.cancel()
            self._save_timer = None
        if self._dirty:
            self._write_cache()

    # ---------- 扫描 ----------

    def get_models_root(self, comfyui_path: str) -> Optional[Path]:
        """定位环境的 models 目录"""
        if not comfyui_path:
            return None
        root = Path(comfyui_path)
        # 标准版：ComfyUI 根目录下 models/
        candidate = root / "models"
        if candidate.is_dir():
            return candidate
        # 桌面版/便携版：根目录下可能还有一层 ComfyUI
        candidate = root / "ComfyUI" / "models"
        if candidate.is_dir():
            return candidate
        return None

    def is_scanning(self) -> bool:
        return self._scanning

    def stop_scan(self) -> None:
        self._scan_stop = True

    def scan(self, comfyui_path: str, force: bool = False,
             extra_roots: Optional[List[str]] = None,
             extra_typed_roots: Optional[List[tuple]] = None) -> Dict:
        """
        扫描（或返回缓存的）模型列表

        Args:
            comfyui_path: 环境 ComfyUI 根路径
            force: True 强制重新扫描
            extra_roots: 额外的模型根目录列表（自动判断类型，按 models 根或类型目录处理）
            extra_typed_roots: 明确指定类型的模型目录列表，元素为 (绝对路径, 类型)。
                       用于「环境设置-模型路径」按 basePath+相对路径 解析出的真实类型目录，
                       避免把上一级目录误当 models 根目录扫描。

        Returns:
            {"models": [...], "dirs": {...}, "lastScanTime": float, "scanning": bool}
        """
        models_root = self.get_models_root(comfyui_path)
        # 收集所有要扫描的根目录（去重）
        roots: List[Path] = []
        typed: Dict[Path, str] = {}  # 明确指定类型的根目录 -> 类型
        if models_root is not None:
            roots.append(models_root)
        for r in (extra_roots or []):
            rp = Path(r)
            if rp.is_dir() and rp not in roots:
                roots.append(rp)
        for item in (extra_typed_roots or []):
            try:
                p, tp = item
            except (ValueError, TypeError):
                continue
            rp = Path(p)
            if not rp.is_dir():
                continue
            if rp not in roots:
                roots.append(rp)
            typed[rp] = tp

        if not roots:
            return {
                "models": [], "dirs": {}, "lastScanTime": None,
                "scanning": False,
                "error": f"未找到 models 目录（comfyuiPath={comfyui_path}）",
            }

        cache_key = "|".join(str(r) for r in roots)
        with self._lock:
            if not self._models and not force:
                self._load_cache(cache_key)
            cached_ok = bool(self._models)

        if force or not cached_ok:
            self._do_scan(roots, cache_key, typed)

        with self._lock:
            dirs: Dict[str, int] = {}
            for m in self._models:
                dirs[m.model_type] = dirs.get(m.model_type, 0) + 1
            return {
                "models": [m.to_dict() for m in self._models],
                "dirs": dirs,
                "lastScanTime": self.last_scan_time,
                "scanning": self._scanning,
            }

    def _do_scan(self, roots: List[Path], cache_key: str,
                 typed: Optional[Dict[Path, str]] = None) -> None:
        if self._scanning:
            return
        self._scanning = True
        self._scan_stop = False
        typed = typed or {}
        found: List[ModelInfo] = []
        try:
            for models_root in roots:
                # 明确指定类型的模型目录（外置模型路径配置解析出的真实类型目录）：
                # rglob 全部模型文件，类型用给定值——即使目录位于任意深度/名字
                # （如 unet 表示 diffusion_models）也能正确归类，且不会误扫上一级目录。
                explicit_type = typed.get(models_root)
                if explicit_type:
                    for f in models_root.rglob("*"):
                        if self._scan_stop:
                            break
                        if not f.is_file():
                            continue
                        if f.suffix.lower() not in MODEL_EXTS:
                            continue
                        try:
                            st = f.stat()
                        except OSError:
                            continue
                        found.append(ModelInfo(
                            filename=f.name, model_type=explicit_type,
                            path=str(f), size=st.st_size, modified_at=st.st_mtime,
                        ))
                    continue

                # 根目录可能直接是某个模型类型目录（如 base_path 指向 checkpoints），
                # 也可能包含多个模型类型子目录（如 models/）
                has_type_subdirs = any(
                    sub.is_dir() and sub.name not in _SKIP_DIRS
                    for sub in models_root.iterdir()
                ) if models_root.is_dir() else False
                # 判断：若根目录自身含模型文件，则当作单个类型目录处理
                direct_files = [f for f in models_root.iterdir()
                                if f.is_file() and f.suffix.lower() in MODEL_EXTS]

                if direct_files:
                    # 根目录本身就是模型类型目录（如外置 checkpoints 根）
                    model_type = models_root.name
                    for f in direct_files:
                        if self._scan_stop:
                            break
                        try:
                            st = f.stat()
                        except OSError:
                            continue
                        found.append(ModelInfo(
                            filename=f.name, model_type=model_type,
                            path=str(f), size=st.st_size, modified_at=st.st_mtime,
                        ))
                else:
                    # 根目录下是多个类型子目录（如 models/）
                    for subdir in sorted(models_root.iterdir()):
                        if self._scan_stop:
                            break
                        if not subdir.is_dir() or subdir.name in _SKIP_DIRS or subdir.name.startswith("put_"):
                            continue
                        model_type = subdir.name
                        for f in subdir.rglob("*"):
                            if self._scan_stop:
                                break
                            if not f.is_file():
                                continue
                            if f.suffix.lower() not in MODEL_EXTS:
                                continue
                            try:
                                st = f.stat()
                            except OSError:
                                continue
                            found.append(ModelInfo(
                                filename=f.name, model_type=model_type,
                                path=str(f), size=st.st_size, modified_at=st.st_mtime,
                            ))

            with self._lock:
                self._models = found
                self._models_by_key = {m.path.lower(): m for m in found}
                self._models_root = cache_key
                self.last_scan_time = time.time()
                self._schedule_save()
            logger.info(f"[ModelScanner] 扫描完成: {len(found)} 个模型 ({cache_key})")
        except Exception as e:
            logger.error(f"[ModelScanner] 扫描失败: {e}", exc_info=True)
        finally:
            self._scanning = False

    # ---------- 增量维护（下载完成后登记 / 删除后移除） ----------

    def register_file(self, path: str, model_type: str) -> None:
        """新文件登记进缓存（下载完成后调用，免全量重扫）"""
        try:
            st = Path(path).stat()
        except OSError:
            return
        info = ModelInfo(filename=Path(path).name, model_type=model_type,
                         path=path, size=st.st_size, modified_at=st.st_mtime)
        with self._lock:
            self._models_by_key[path.lower()] = info
            self._models = list(self._models_by_key.values())
            self._schedule_save()

    def remove_file(self, path: str) -> None:
        with self._lock:
            key = path.lower()
            if key in self._models_by_key:
                del self._models_by_key[key]
                self._models = list(self._models_by_key.values())
                self._schedule_save()
