"""
模型库控制器

为前端『模型管理』页面提供本地扫描与多源下载的桥接层。
环境定位复用 EnvironmentController 的环境管理器（与依赖管理页一致）。
"""

import threading
from pathlib import Path
from typing import Dict, List, Optional

from backend.src.utils.logger import app_logger as logger
from backend.src.utils.path_serializer import serialize_response
from backend.src.core.modelmgr.model_scanner import ModelScanner, MODEL_DIR_LABELS
from backend.src.core.modelmgr.model_downloader import ModelDownloader, detect_source, suggest_filename
from backend.src.core.modelmgr.model_linker import ModelLinker


# 前端模型路径配置的类型键（驼峰）-> 规范化类型名（与 MODEL_DIR_LABELS / ComfyUI folder_paths 一致）
_MODEL_TYPE_FIELD_MAP = {
    "checkpoints": "checkpoints",
    "clip": "clip",
    "clipVision": "clip_vision",
    "configs": "configs",
    "controlnet": "controlnet",
    "diffusionModels": "diffusion_models",
    "embeddings": "embeddings",
    "loras": "loras",
    "upscaleModels": "upscale_models",
    "vae": "vae",
    "gligen": "gligen",
    "hypernetworks": "hypernetworks",
    "styleModels": "style_models",
    "diffusers": "diffusers",
    "vaeApprox": "vae_approx",
    "t2iAdapter": "t2i_adapter",
    "latentUpscaleModels": "latent_upscale_models",
    "photomaker": "photomaker",
    "classifiers": "classifiers",
    "modelPatches": "model_patches",
    "audioEncoders": "audio_encoders",
    "frameInterpolation": "frame_interpolation",
}


def _normalize_model_type(key: str) -> str:
    """把前端类型键规范化为 ComfyUI 类型名；未知键原样返回。"""
    return _MODEL_TYPE_FIELD_MAP.get(key, key)


class ModelController:
    """模型库控制器"""

    def __init__(self, environment_manager=None, model_config_manager=None):
        self.environment_manager = environment_manager
        self._model_config_manager = model_config_manager
        self._scanner = ModelScanner()
        self._downloader = ModelDownloader(scanner=self._scanner)
        self._linker = ModelLinker()
        self._current_models_root: str = ""

    def set_environment_manager(self, manager) -> None:
        self.environment_manager = manager

    def set_model_config_manager(self, manager) -> None:
        """注入模型管理配置管理器（本地模型文件夹 scan_paths + 默认源）"""
        self._model_config_manager = manager

    def _get_current_env(self) -> Optional[Dict]:
        if not self.environment_manager:
            logger.error("[ModelController] 环境管理器未初始化")
            return None
        try:
            env_id = self.environment_manager.get_current_environment_id()
            if not env_id:
                logger.warning("[ModelController] 无当前环境 ID（environments.json 未选中环境）")
                return None
            resp = self.environment_manager.get_environment(env_id)
            if not resp or resp.get("success") is False:
                logger.warning(f"[ModelController] 环境 {env_id} 获取失败: {resp}")
                return None
            # get_environment 返回 {"success": True, "environment": {...}}，需解包
            env = resp.get("environment") if isinstance(resp, dict) else None
            if not env:
                logger.warning(f"[ModelController] 环境 {env_id} 响应无 environment 字段: {resp}")
                return None
            logger.info(
                f"[ModelController] 当前环境: id={env_id} | "
                f"path={env.get('path')} | modelPathConfigs={len(env.get('modelPathConfigs') or [])}"
            )
            return env
        except Exception as e:
            logger.error(f"[ModelController] 获取当前环境失败: {e}")
            return None

    def _get_models_root(self) -> Optional[Path]:
        env = self._get_current_env()
        if not env:
            return None
        comfyui_path = env.get("comfyuiPath") or env.get("path")
        if not comfyui_path:
            return None
        return self._scanner.get_models_root(str(comfyui_path))

    # ---------- 本地扫描 ----------

    @serialize_response
    def model_get_models(self, force: bool = False) -> Dict:
        """获取本地模型列表（优先缓存）"""
        env = self._get_current_env()
        if not env:
            logger.warning("[ModelController] 未选中环境或环境配置无效，无法扫描模型")
            return {"success": False, "error_message": "未选中环境或环境配置无效"}

        comfyui_path = env.get("comfyuiPath") or env.get("path") or ""
        # 「环境设置-模型路径」配置的外置模型目录（解析为真实的模型类型目录）。
        # 注意：前端为兼容 ComfyUI 的 extra_model_paths.yaml，会把 basePath 末尾的
        # /models 去掉，并给每个模型类型填相对路径（如 checkpoints -> models/checkpoints，
        # customNodes -> custom_nodes）。因此这里必须用 basePath + 各相对路径 解析出
        # 「真实的模型类型目录」再按类型扫描，而不是把 basePath（此时是上一级目录）
        # 当成 models 根目录去扫描——否则会误扫上一级目录（如 ComfyUI-Shared）。
        env_typed_roots: List[tuple] = []  # (绝对路径, 规范化类型)
        default_roots: List[str] = []      # 默认填充候选（当前环境 models 根 + 共享目录）
        models_root = self._scanner.get_models_root(str(comfyui_path)) if comfyui_path else None
        if models_root is not None:
            default_roots.append(str(models_root))
            self._current_models_root = str(models_root)
        for cfg in (env.get("modelPathConfigs") or env.get("model_path_configs") or []):
            base = (cfg.get("basePath") or cfg.get("base_path") or "").strip()
            if not base:
                continue
            paths = cfg.get("paths") or {}
            has_model_type = False
            for key, rel in paths.items():
                # custom_nodes 是插件目录，不是模型，跳过
                if key == "customNodes":
                    continue
                rel = rel.strip() if isinstance(rel, str) else ""
                if not rel:
                    continue
                typed_dir = str(Path(base) / rel)
                env_typed_roots.append((typed_dir, _normalize_model_type(key)))
                default_roots.append(typed_dir)
                has_model_type = True
            if not has_model_type:
                # 没有按类型配置相对路径时，退化为直接扫描 base 本身及其子目录
                default_roots.append(base)

        # 桌面版共享模型目录：<安装父目录>/ComfyUI-Shared/models
        try:
            from backend.src.utils.paths import get_project_root
            shared = str(Path(get_project_root()).parent / "ComfyUI-Shared" / "models")
            if shared not in default_roots:
                default_roots.append(shared)
        except Exception:
            pass

        # 「模型管理」页面设置的本地模型文件夹（scan_paths）——唯一的扫描根来源：
        # - 首次使用：自动填充上面的默认候选（环境 models 根 + 共享目录 + 外置类型目录）；
        # - 用户清空后保存：scan_paths 为空 → 不扫描任何目录 → 列表为空（不会被自动恢复）；
        # - 用户输入了哪些文件夹，就只显示哪些文件夹。
        extra_roots: List[str] = []
        if self._model_config_manager is not None:
            try:
                self._model_config_manager.ensure_default_model_paths(default_roots)
                sp_result = self._model_config_manager.get_scan_paths()
                for sp in (sp_result.get("paths") or []):
                    p = (sp.get("path") or "").strip()
                    if not p:
                        continue
                    if sp.get("enabled", True) is False:
                        continue
                    if p not in extra_roots:
                        extra_roots.append(p)
            except Exception as e:
                logger.warning(f"[ModelController] 读取模型扫描路径失败（忽略）: {e}")
        else:
            # 没有配置管理器时退化为旧行为（环境 models 根 + 外置类型目录）
            extra_roots = list(default_roots)

        # 去重：scan_paths 里恰好是环境「模型路径」配置的类型目录时，
        # 交给 typed 逻辑按明确类型扫描更准确（其余 scan_paths 走自动类型判断）
        root_set = set(extra_roots)
        extra_typed_roots = [(p, t) for p, t in env_typed_roots if p in root_set]

        result = self._scanner.scan(
            str(comfyui_path), force=force,
            extra_roots=extra_roots, extra_typed_roots=extra_typed_roots,
        )

        # 附加网络链接关联信息（有链接的模型带 linkUrl/linkSource）
        links = self._linker.store.get_all()
        models_out = result["models"]
        for m in models_out:
            lnk = links.get(m.get("id"))
            if lnk:
                m["linkUrl"] = lnk.get("url", "")
                m["linkSource"] = lnk.get("source", "")
                m["linkManual"] = bool(lnk.get("manual"))

        logger.info(
            f"[ModelController] 模型扫描完成: {len(models_out)} 个 | "
            f"comfyuiPath={comfyui_path} | extraRoots={extra_roots} | force={force}"
        )

        return {
            "success": True,
            "models": models_out,
            "dirs": result["dirs"],
            "dirLabels": MODEL_DIR_LABELS,
            "lastScanTime": result["lastScanTime"],
            "scanning": result["scanning"],
            "error": result.get("error", ""),
        }

    @serialize_response
    def model_rescan(self) -> Dict:
        """强制重新扫描"""
        result = self.model_get_models(force=True)
        # 扫描在后台线程跑的话立刻返回缓存；这里 scan 是同步的，直接返回结果
        return result

    @serialize_response
    def model_get_scan_status(self) -> Dict:
        return {"success": True, "scanning": self._scanner.is_scanning()}

    @serialize_response
    def model_delete(self, path: str) -> Dict:
        """删除本地模型文件"""
        if not path:
            return {"success": False, "error_message": "路径为空"}
        p = Path(path)
        if not p.exists():
            self._scanner.remove_file(path)
            self._linker.store.remove(self._model_id_of(path))
            return {"success": True, "message": "文件不存在，已清理缓存记录"}

        # 防误删：允许删除的范围 = 当前环境 models 根 + 设置里启用的扫描文件夹
        allowed_roots: List[Path] = []
        models_root = self._get_models_root()
        if models_root is not None:
            allowed_roots.append(models_root)
        if self._model_config_manager is not None:
            try:
                sp_result = self._model_config_manager.get_scan_paths()
                for sp in (sp_result.get("paths") or []):
                    rp = (sp.get("path") or "").strip()
                    if rp and sp.get("enabled", True) is not False:
                        allowed_roots.append(Path(rp))
            except Exception:
                pass
        if not allowed_roots:
            return {"success": False, "error_message": "未找到允许删除的模型目录"}

        rp_resolved = p.resolve()
        inside = False
        for root in allowed_roots:
            try:
                rp_resolved.relative_to(root.resolve())
                inside = True
                break
            except (ValueError, OSError):
                continue
        if not inside:
            return {"success": False, "error_message": "仅允许删除已配置模型文件夹内的文件"}

        try:
            p.unlink()
            self._scanner.remove_file(path)
            self._linker.store.remove(self._model_id_of(path))
            logger.info(f"[ModelController] 模型已删除: {p.name}")
            return {"success": True}
        except Exception as e:
            logger.error(f"[ModelController] 删除失败: {e}")
            return {"success": False, "error_message": f"删除失败: {e}"}

    @staticmethod
    def _model_id_of(path: str) -> str:
        """与 ModelScanner 一致的模型 id（路径 md5 前 16 位）"""
        import hashlib
        return hashlib.md5(path.lower().encode("utf-8")).hexdigest()[:16]

    # ---------- 网络链接关联 ----------

    def _default_source(self) -> str:
        if self._model_config_manager is not None:
            try:
                r = self._model_config_manager.get_default_source()
                return r.get("source", "modelscope")
            except Exception:
                pass
        return "modelscope"

    @serialize_response
    def model_get_link(self, model_id: str) -> Dict:
        """获取单个模型已关联的网络链接"""
        entry = self._linker.store.get(model_id)
        return {"success": True, "link": entry}

    @serialize_response
    def model_set_link(self, model_id: str, url: str, source: str = "",
                       repo_name: str = "", manual: bool = True) -> Dict:
        """手动设置/覆盖单个模型的关联链接"""
        url = (url or "").strip()
        if not url:
            return {"success": False, "error_message": "链接不能为空"}
        if not url.lower().startswith(("http://", "https://")):
            return {"success": False, "error_message": "仅支持 http/https 链接"}
        if not source:
            from backend.src.core.modelmgr.model_downloader import detect_source as _ds
            source = _ds(url)
        entry = self._linker.store.set(model_id, url, source, repo_name=repo_name, manual=manual)
        logger.info(f"[ModelController] 模型 {model_id} 手动关联链接: {url}")
        return {"success": True, "link": entry}

    @serialize_response
    def model_remove_link(self, model_id: str) -> Dict:
        """移除单个模型的关联链接"""
        ok = self._linker.store.remove(model_id)
        return {"success": ok}

    @serialize_response
    def model_get_link_candidates(self, filename: str, source: str = "") -> Dict:
        """获取单个模型的候选关联链接（魔搭/HuggingFace 搜索结果，供用户直接选）"""
        source = source or self._default_source()
        return self._linker.get_candidates(filename, source=source)

    @serialize_response
    def model_start_link_sync(self) -> Dict:
        """启动后台批量同步：为所有无关联的模型自动关联网络链接"""
        scan = self.model_get_models(force=False)
        models = [
            {"id": m["id"], "filename": m["filename"]}
            for m in (scan.get("models") or [])
        ]
        if not models:
            return {"success": False, "error_message": "当前没有可同步的模型"}
        return self._linker.start_sync(models, source=self._default_source())

    @serialize_response
    def model_stop_link_sync(self) -> Dict:
        self._linker.stop_sync()
        return {"success": True}

    @serialize_response
    def model_get_link_sync_status(self) -> Dict:
        return self._linker.get_sync_status()

    # ---------- 下载 ----------

    @serialize_response
    def model_start_download(self, url: str, model_type: str, filename: str = "") -> Dict:
        """
        开始下载模型

        Args:
            url: 下载地址（自动识别 HF/HF-Mirror/ModelScope/Civitai/直链）
            model_type: 模型分类目录名（checkpoints/loras/vae/...）
            filename: 目标文件名（空则从 URL 推断）
        """
        models_root = self._get_models_root()
        if models_root is None:
            return {"success": False, "error_message": "未找到当前环境的 models 目录"}

        dest_dir = models_root / (model_type or "checkpoints")
        result = self._downloader.start_download(url, dest_dir, model_type, filename)
        if result.get("success"):
            result["suggestFilename"] = suggest_filename(url)
            result["detectedSource"] = detect_source(url)
        return result

    @serialize_response
    def model_get_download_status(self) -> Dict:
        return self._downloader.get_status()

    @serialize_response
    def model_cancel_download(self, task_id: str) -> Dict:
        ok = self._downloader.cancel(task_id)
        return {"success": ok, "error_message": "" if ok else "任务不存在或已结束"}

    @serialize_response
    def model_clear_finished_downloads(self) -> Dict:
        self._downloader.clear_finished()
        return {"success": True}

    @serialize_response
    def model_detect_source(self, url: str) -> Dict:
        """前端输入 URL 时实时识别来源"""
        url = (url or "").strip()
        return {
            "success": True,
            "source": detect_source(url) if url else "",
            "suggestFilename": suggest_filename(url) if url else "",
        }
