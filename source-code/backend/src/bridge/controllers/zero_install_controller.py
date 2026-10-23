"""
『0基础安装』控制器

从零下载并装配一个完整可运行的 ComfyUI 便携环境，编排步骤：
  1. 下载 ComfyUI 官方 portable 7z（GitHub Release 资产，自动镜像 fallback）
  2. 解压并规范化目录（防嵌套：确保 <install_dir>/ComfyUI/main.py 与 run_*.bat 在顶层）
  3. 安装选中的注意力后端（官方已含的提示跳过；Flash/Sage 按 torch/cuda/python 匹配）
  4. 插件 git clone 到 custom_nodes（复用 GitManager 的镜像 fallback）
  5. 工作流仓库 clone 并把 *.json 拷入 ComfyUI/user/default/workflows
  6. pip install -r ComfyUI/requirements.txt（走 PyPI 镜像设置）
  7. 完成（前端引导用户去工作台启动）

模型文件不自动下载（体积过大），向导中列出链接供用户后续手动下载。
下载全程若直连与镜像均失败，错误信息附带 Watt Toolkit / DevSidecar 引导。
"""

import json
import sys
import re
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

import requests

from backend.src.utils.logger import app_logger as logger
from backend.src.utils.path_serializer import serialize_response

OFFICIAL_REPO = "Comfy-Org/ComfyUI"
GPU_HINT_ASSETS = {
    "nvidia": ["nvidia"],
    "nvidia_arm64": ["arm64"],
    "intel": ["intel"],
    "amd": ["amd"],
}

PROXY_GUIDE = (
    "直连与镜像均无法连接。请开启网络代理工具后重试；"
    "若没有代理工具，推荐安装 Watt Toolkit（https://steampp.net）"
    "或 DevSidecar（https://github.com/docmirror/dev-sidecar）后重试。"
)


class _WorkflowSourceSlow(RuntimeError):
    """工作流下载：当前源速度过慢（触发换源）"""


# 默认插件清单（用户可在向导中增删）
DEFAULT_PLUGINS = [
    {"name": "ComfyUI-Manager", "url": "https://github.com/Comfy-Org/ComfyUI-Manager"},
    {"name": "rgthree-comfy", "url": "https://github.com/rgthree/rgthree-comfy"},
    {"name": "RES4LYF", "url": "https://github.com/ClownsharkBatwing/RES4LYF"},
    {"name": "XB_ToolBox", "url": "https://github.com/wjluoxiao/XB_ToolBox"},
    {"name": "ComfyUI-JZL-MiniMax-H3", "url": "https://github.com/wjluoxiao/ComfyUI-JZL-MiniMax-H3"},
    {"name": "ComfyUI-xiaozhuguang", "url": "https://github.com/xiaozhuguang/ComfyUI-xiaozhuguang"},
    {"name": "comfyui-SelfLift", "url": "https://github.com/facok/comfyui-SelfLift"},
    {"name": "ComfyUI-AlignLayout", "url": "https://github.com/pixixai/ComfyUI-AlignLayout.git"},
]

# 默认工作流清单（10 条官方推荐工作流，blob 地址 → 安装时转 raw + gh-proxy 镜像下载）
DEFAULT_WORKFLOW_FILES = [
    {"name": "H3_Balanced", "url": "https://github.com/FlowForgeLabAi/MiniMax-H3-8GB-Workflows/blob/main/H3_Balanced.json"},
    {"name": "H3_Fast", "url": "https://github.com/FlowForgeLabAi/MiniMax-H3-8GB-Workflows/blob/main/H3_Fast.json"},
    {"name": "H3_Quality", "url": "https://github.com/FlowForgeLabAi/MiniMax-H3-8GB-Workflows/blob/main/H3_Quality.json"},
    {"name": "H3全模式本地工作流_Beta_1", "url": "https://github.com/YixuAn-13/minimax-h3-comfyui-all-in-one/blob/main/beta1/workflows/H3%E5%85%A8%E6%A8%A1%E5%BC%8F%E6%9C%AC%E5%9C%B0%E5%B7%A5%E4%BD%9C%E6%B5%81_Beta_1.json"},
    {"name": "H3全模式本地工作流_Beta_1_Lite", "url": "https://github.com/YixuAn-13/minimax-h3-comfyui-all-in-one/blob/main/beta1/workflows/H3%E5%85%A8%E6%A8%A1%E5%BC%8F%E6%9C%AC%E5%9C%B0%E5%B7%A5%E4%BD%9C%E6%B5%81_Beta_1_Lite.json"},
    {"name": "H3全模式本地工作流_Beta_2.1", "url": "https://github.com/YixuAn-13/minimax-h3-comfyui-all-in-one/blob/main/beta2/workflows/H3%E5%85%A8%E6%A8%A1%E5%BC%8F%E6%9C%AC%E5%9C%B0%E5%B7%A5%E4%BD%9C%E6%B5%81_Beta_2.1.json"},
    {"name": "H3全模式本地工作流_Beta_2_Lite", "url": "https://github.com/YixuAn-13/minimax-h3-comfyui-all-in-one/blob/main/beta2/workflows/H3%E5%85%A8%E6%A8%A1%E5%BC%8F%E6%9C%AC%E5%9C%B0%E5%B7%A5%E4%BD%9C%E6%B5%81_Beta_2_Lite.json"},
    {"name": "H3全模式本地工作流_Beta_3", "url": "https://github.com/YixuAn-13/minimax-h3-comfyui-all-in-one/blob/main/beta3/workflows/H3%E5%85%A8%E6%A8%A1%E5%BC%8F%E6%9C%AC%E5%9C%B0%E5%B7%A5%E4%BD%9C%E6%B5%81_Beta_3.json"},
    {"name": "H3全模式本地工作流_Beta_3_FaceRefine", "url": "https://github.com/YixuAn-13/minimax-h3-comfyui-all-in-one/blob/main/beta3/workflows/H3%E5%85%A8%E6%A8%A1%E5%BC%8F%E6%9C%AC%E5%9C%B0%E5%B7%A5%E4%BD%9C%E6%B5%81_Beta_3_FaceRefine.json"},
    {"name": "H3全模式本地工作流_Beta_3_Lite", "url": "https://github.com/YixuAn-13/minimax-h3-comfyui-all-in-one/blob/main/beta3/workflows/H3%E5%85%A8%E6%A8%A1%E5%BC%8F%E6%9C%AC%E5%9C%B0%E5%B7%A5%E4%BD%9C%E6%B5%81_Beta_3_Lite.json"},
]

# 默认模型清单（7 个 HF 仓库；文件清单由 zero_list_hf_files 动态拉取）
# 名称规范：仅字母、小数点、下划线（作为下载子目录名）
# default_dir：该仓库文件的强制分类目录（覆盖智能分类，如文本编码器仓库）
DEFAULT_MODEL_REPOS = [
    {"name": "FLUX.2", "repo": "rockerBOO/flux2-klein-4b-nvfp4-convrot", "defaultDir": ""},
    {"name": "Z_Image", "repo": "martin-rizzo/Z-Image-Turbo-INT8-ConvRot-ComfyUI", "defaultDir": ""},
    {"name": "Qwen_Image_2.1", "repo": "Comfy-Org/Qwen-Image-2.1", "defaultDir": ""},
    {"name": "MiniMax_H3", "repo": "Gluttony10/MiniMax-H3-INT8-CONVROT", "defaultDir": ""},
    {"name": "MiniMax_H3", "repo": "binglingzhimeng/minimax_h3_hybrid_fl2va_ref2va_b25-49_w6a8", "defaultDir": ""},
    {"name": "Qwen3_VL_32B", "repo": "Momoking/Qwen3-VL-32B-Heretic-MiniMax-H3-NVFP4",
     "defaultDir": "text_encoders"},
    {"name": "gemma4", "repo": "mcmonkey/swarm-models", "defaultDir": "text_encoders"},
]

# extra_model_paths.yaml 支持的模型目录 key（ComfyUI 官方 folder_paths 注册表，snake_case）
MODEL_PATH_KEYS = [
    {"label": "Checkpoints", "key": "checkpoints", "default": "models/checkpoints"},
    {"label": "CLIP", "key": "clip", "default": "models/clip"},
    {"label": "Text Encoders", "key": "text_encoders", "default": "models/text_encoders"},
    {"label": "CLIP Vision", "key": "clip_vision", "default": "models/clip_vision"},
    {"label": "Configs", "key": "configs", "default": "models/configs"},
    {"label": "ControlNet", "key": "controlnet", "default": "models/controlnet"},
    {"label": "Diffusion Models", "key": "diffusion_models", "default": "models/diffusion_models"},
    {"label": "Embeddings", "key": "embeddings", "default": "models/embeddings"},
    {"label": "LoRAs", "key": "loras", "default": "models/loras"},
    {"label": "Upscale Models", "key": "upscale_models", "default": "models/upscale_models"},
    {"label": "VAE", "key": "vae", "default": "models/vae"},
    {"label": "GLIGEN", "key": "gligen", "default": "models/gligen"},
    {"label": "Hypernetworks", "key": "hypernetworks", "default": "models/hypernetworks"},
    {"label": "Custom Nodes", "key": "custom_nodes", "default": "models/custom_nodes"},
    {"label": "Style Models", "key": "style_models", "default": "models/style_models"},
    {"label": "Diffusers", "key": "diffusers", "default": "models/diffusers"},
    {"label": "VAE Approx", "key": "vae_approx", "default": "models/vae_approx"},
    {"label": "T2I Adapter", "key": "t2i_adapter", "default": "models/t2i_adapter"},
    {"label": "Latent Upscale Models", "key": "latent_upscale_models", "default": "models/latent_upscale_models"},
    {"label": "Photomaker", "key": "photomaker", "default": "models/photomaker"},
    {"label": "Classifiers", "key": "classifiers", "default": "models/classifiers"},
    {"label": "Model Patches", "key": "model_patches", "default": "models/model_patches"},
    {"label": "Audio Encoders", "key": "audio_encoders", "default": "models/audio_encoders"},
    {"label": "Frame Interpolation", "key": "frame_interpolation", "default": "models/frame_interpolation"},
]

WORKSPACE_KEYS = [
    {"label": "Input 目录", "key": "input"},
    {"label": "Output 目录", "key": "output"},
    {"label": "Temp 目录", "key": "temp"},
    {"label": "User 目录", "key": "user"},
    {"label": "工作流目录", "key": "workflows"},
]

# HF 文件名 → 模型目录类型（智能分类；顺序敏感，先匹配专项再匹配主模型）
HF_FILE_TYPE_RULES = [
    (re.compile(r"vae", re.I), "vae"),
    (re.compile(r"text_encoder|t5xxl|t5-|clip[-_]?l|clip[-_]?g|clip[-_]?vision|qwen2\.?5-?vl|umt5|gemma", re.I), "text_encoders"),
    (re.compile(r"loras?[/\\]|[-_.]lora", re.I), "loras"),
    (re.compile(r"controlnet|control_", re.I), "controlnet"),
    (re.compile(r"upscale|esrgan|realesrgan|swinir", re.I), "upscale_models"),
    (re.compile(r"embedding|invscal", re.I), "embeddings"),
]

# 注意力后端清单；built_in=True 的无需安装
ATTENTION_OPTIONS = [
    {"id": "flash", "name": "Flash Attention", "built_in": False},
    {"id": "sage", "name": "Sage Attention", "built_in": False},
    {"id": "ck", "name": "Comfy Kitchen Attention", "built_in": True,
     "note": "ComfyUI v0.32.0+ 官方已包含"},
    {"id": "split", "name": "Split Attention", "built_in": True,
     "note": "官方已包含"},
    {"id": "pytorch", "name": "PyTorch Attention", "built_in": True,
     "note": "官方已包含"},
    {"id": "quad", "name": "Quad Attention", "built_in": True,
     "note": "官方已包含"},
]


class ZeroInstallController:
    """『0基础安装』控制器"""

    def __init__(self, environment_manager=None, settings_manager=None):
        self.environment_manager = environment_manager
        self.settings_manager = settings_manager
        self._lock = threading.Lock()
        self._progress: Dict = {"running": False, "step": "", "percent": 0, "logs": [], "done": False, "error": ""}
        self._cancel_event = threading.Event()
        # 下载组状态（按字节总量算进度，见 _begin_download_group）
        self._dl_group_total = 0
        self._dl_files: Dict[str, Dict[str, int]] = {}
        self._dl_done = 0

    # ==================== 向导数据 API ====================

    @serialize_response
    def zero_get_release_assets(self) -> Dict:
        """
        获取 ComfyUI 最新 Release 的便携包资产（.7z），并按 GPU 推荐默认项
        """
        try:
            import subprocess

            r = requests.get(
                f"https://api.github.com/repos/{OFFICIAL_REPO}/releases/latest",
                headers={"User-Agent": "ComfyNexus/1.0", "Accept": "application/vnd.github.v3+json"},
                timeout=(15, 30),
            )
            r.raise_for_status()
            release = r.json()
            assets = [
                {
                    "name": a["name"],
                    "url": a["browser_download_url"],
                    "size": a["size"],
                }
                for a in release.get("assets", [])
                if a["name"].lower().endswith(".7z")
            ]
            if not assets:
                return {"success": False, "error_message": "最新 Release 中未找到便携包（.7z）资产"}

            # GPU 推荐匹配
            gpu_name = ""
            try:
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True, text=True, timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode == 0:
                    gpu_name = result.stdout.strip().splitlines()[0] if result.stdout else ""
            except Exception:
                pass

            recommended = None
            if gpu_name:
                if "arm" in gpu_name.lower():
                    recommended = next((a["url"] for a in assets if "arm64" in a["name"].lower()), None)
                if not recommended:
                    recommended = next((a["url"] for a in assets if "nvidia" in a["name"].lower()), None)

            return {
                "success": True,
                "tag": release.get("tag_name", ""),
                "assets": assets,
                "gpuName": gpu_name,
                "recommendedUrl": recommended,
                "attentions": ATTENTION_OPTIONS,
                "defaultPlugins": DEFAULT_PLUGINS,
                "defaultModelRepos": DEFAULT_MODEL_REPOS,
                "modelPathKeys": MODEL_PATH_KEYS,
                "workspaceKeys": WORKSPACE_KEYS,
                "workflowFiles": DEFAULT_WORKFLOW_FILES,
            }
        except Exception as e:
            logger.error(f"[ZeroInstall] 获取 Release 资产失败: {e}")
            return {"success": False, "error_message": str(e)}

    # HF API 专用会话：trust_env=False 绕过系统代理（用户环境常见死代理导致识别失败）
    _hf_session: Optional[requests.Session] = None

    def _hf_api_session(self) -> requests.Session:
        if ZeroInstallController._hf_session is None:
            s = requests.Session()
            s.trust_env = False
            s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"})
            ZeroInstallController._hf_session = s
        return ZeroInstallController._hf_session

    @staticmethod
    def _normalize_hf_repo(raw: str) -> Optional[str]:
        """
        多方位清洗 HF 仓库标识，以下输入全部归一为 owner/repo：
        - owner/repo
        - owner/repo/tree/main、/tree/master、/blob/...、/resolve/main/...
        - https://hf-mirror.com/owner/repo[/...]
        - https://huggingface.co/owner/repo[/...]
        - Hugface/owner/repo、Huggingface/owner/repo（误写前缀）
        - api/models/owner/repo
        """
        s = (raw or "").strip().strip("/")
        if not s:
            return None
        # 剥协议与已知域名
        s = re.sub(r"^https?://", "", s, flags=re.I)
        s = re.sub(r"^(hf-mirror\.com|huggingface\.co)/", "", s, flags=re.I)
        s = re.sub(r"^(www\.)?", "", s, flags=re.I)
        # 剥常见前缀误写
        s = re.sub(r"^(hugface|huggingface|hf|model(models)?)[:/]+", "", s, flags=re.I)
        s = re.sub(r"^api/models/", "", s, flags=re.I)
        s = s.strip("/")
        # 剥子路径（tree/blob/resolve 及之后全部丢弃）
        s = re.split(r"/(tree|blob|resolve)/", s)[0]
        # 剥查询与锚点
        s = s.split("?")[0].split("#")[0].strip("/")
        # 校验 owner/repo 形态
        parts = [p for p in s.split("/") if p]
        if len(parts) >= 2 and all(re.match(r"^[\w.\-]+$", p) for p in parts[:2]):
            return f"{parts[0]}/{parts[1]}"
        return None

    @serialize_response
    def zero_list_hf_files(self, repo_raw: str, default_dir: str = "") -> Dict:
        """
        列出 HuggingFace 仓库中的模型文件（hf-mirror API，绕过系统代理）

        自动清洗多种输入形态；过滤出权重类文件并按文件名智能分类目标目录。

        Returns:
            dict: {"success", "repo", "files": [{"path","name","size","dir","url"}]}
        """
        repo = self._normalize_hf_repo(repo_raw)
        if not repo:
            return {"success": False, "error_message": f"无法识别仓库地址: {repo_raw}"}

        try:
            r = self._hf_api_session().get(
                f"https://hf-mirror.com/api/models/{repo}/tree/main",
                params={"recursive": "true"},
                timeout=(15, 40),
            )
            r.raise_for_status()
            tree = r.json()
        except Exception as e:
            logger.warning(f"[ZeroInstall] HF 文件列表拉取失败 ({repo}): {e}")
            return {"success": False, "error_message": f"获取文件列表失败: {e}（请点击刷新重试）"}

        files = []
        for item in tree:
            if item.get("type") != "file":
                continue
            path = item.get("path", "")
            # 排除文档/配置类；权重文件保留（含子目录中的大文件）
            if not re.search(r"\.(safetensors|sft|gguf|ckpt|pt|pth|onnx)$", path, re.I):
                continue
            name = path.split("/")[-1]
            dir_type = (default_dir or "").strip() or self._classify_hf_file(name)
            files.append({
                "path": path,
                "name": name,
                "size": item.get("size", 0),
                "dir": dir_type,
                "url": f"https://hf-mirror.com/{repo}/resolve/main/{path}",
            })

        # 排序：大文件（主模型）在前
        files.sort(key=lambda f: -f["size"])
        if not files:
            return {
                "success": True,
                "repo": repo,
                "files": [],
                "error_message": "仓库中未找到权重文件（.safetensors/.gguf 等）",
            }
        return {"success": True, "repo": repo, "files": files}

    def _write_mappings(self, install_dir: Path, model_paths: Dict, workspace: Dict):
        """安装完成后落地共享映射（pipeline 内部调用）"""
        if model_paths:
            import yaml
            doc = {"comfynexus_shared": {}}
            for key, abs_path in model_paths.items():
                if abs_path:
                    doc["comfynexus_shared"][key] = Path(abs_path).as_posix()
            with open(install_dir / "extra_model_paths.yaml", "w", encoding="utf-8") as f:
                yaml.safe_dump(doc, f, allow_unicode=True, default_flow_style=False)
            self._log(f"已写入 extra_model_paths.yaml（{len(doc['comfynexus_shared'])} 项模型映射）")

        if workspace:
            (install_dir / "comfynexus_paths.json").write_text(
                json.dumps({"workspace": workspace}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._log(f"已写入工作区目录配置（{len(workspace)} 项）")

        wf_dir = workspace.get("workflows")
        if wf_dir:
            from backend.src.core.env.workflow_junction import ensure_workflow_junction
            ok = ensure_workflow_junction(str(install_dir), wf_dir)
            self._log("工作流目录联接" + ("成功" if ok else "失败（可稍后在环境设置中重试）"))

    @staticmethod
    def _classify_hf_file(filename: str) -> str:
        """按文件名智能分类模型目录（主模型统一放 unet，SD/SDXL 除外）"""
        # 先查专项类型
        for pattern, dir_type in HF_FILE_TYPE_RULES:
            if pattern.search(filename):
                return dir_type
        # SD/SDXL 主模型放 checkpoints，其余主模型放 unet
        if re.search(r"sd15|sd_?1\.5|sd_?xl|stable[-_]?diffusion", filename, re.I):
            return "checkpoints"
        return "unet"

    @serialize_response
    def zero_write_extra_paths(self, config: Dict) -> Dict:
        """
        把共享模型文件夹 / 工作区映射写入安装目录：
        - 模型映射 → <install_dir>/extra_model_paths.yaml（ComfyUI 官方机制）
        - input/output/temp/user → <install_dir>/comfynexus_paths.json（添加环境时自动带入）
        - workflows → NTFS 目录联接

        config: {"installDir", "modelPaths": {key: absPath}, "workspace": {key: absPath}}
        """
        try:
            install_dir = Path((config or {}).get("installDir", ""))
            if not install_dir.is_dir():
                return {"success": False, "error_message": "安装目录不存在"}
            model_paths: Dict = config.get("modelPaths") or {}
            workspace: Dict = config.get("workspace") or {}

            # ---- extra_model_paths.yaml ----
            if model_paths:
                import yaml  # pyyaml 已在依赖中
                # ComfyUI 官方格式：命名字段 + base_path + 各类型相对路径
                # 这里把用户填的绝对路径换算成相对 base（base 取第一个映射的公共前缀简化处理：
                # 直接为每个类型写绝对路径，ComfyUI 支持绝对路径）
                doc = {"comfynexus_shared": {}}
                for key, abs_path in model_paths.items():
                    if abs_path:
                        # yaml 内统一使用正斜杠（Windows 亦兼容）
                        doc["comfynexus_shared"][key] = Path(abs_path).as_posix()
                yaml_file = install_dir / "extra_model_paths.yaml"
                with open(yaml_file, "w", encoding="utf-8") as f:
                    yaml.safe_dump(doc, f, allow_unicode=True, default_flow_style=False)
                self._log(f"已写入 extra_model_paths.yaml（{len(model_paths)} 项模型映射）")

            # ---- 工作区目录 ----
            if workspace:
                paths_file = install_dir / "comfynexus_paths.json"
                paths_file.write_text(
                    json.dumps({"workspace": workspace}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                self._log(f"已写入工作区目录配置（{len(workspace)} 项）")

            # ---- workflows 目录联接 ----
            wf_dir = workspace.get("workflows")
            if wf_dir:
                from backend.src.core.env.workflow_junction import ensure_workflow_junction
                # 联接目标：ComfyUI/user/default/workflows
                ok = ensure_workflow_junction(str(install_dir), wf_dir)
                self._log("工作流目录联接" + ("成功" if ok else "失败（可稍后在环境设置中重试）"))

            return {"success": True}
        except Exception as e:
            logger.error(f"[ZeroInstall] 写入共享映射失败: {e}")
            return {"success": False, "error_message": str(e)}

    @serialize_response
    def zero_list_attention_wheels(self, attention_id: str) -> Dict:
        """
        列出注意力后端的可选版本（供用户选择）

        - sageattention: PyPI 已有则提示直接 pip 安装（无需选版本）
        - flash-attn: 从 kingbri1/flash-attention release 资产中按
          cu{X}torch{Y} 与 python 版本过滤
        """
        try:
            env_info = self._detect_python_env()
            if not env_info:
                return {"success": False, "error_message": "请先完成第 1/2 步（解压便携包）后再安装注意力"}

            if attention_id == "sage":
                # sageattention 在 PyPI 有纯 py 源码包，无需选 whl 版本
                return {"success": True, "mode": "pip", "wheels": [],
                        "message": "Sage Attention 将通过 pip 安装（需 triton 支持）"}

            if attention_id != "flash":
                return {"success": True, "mode": "built-in", "wheels": []}

            # flash-attn whl 匹配：cp{py} + cu{cuda} + torch{major.minor}
            py_tag = f"cp{env_info['python']}{env_info['python_minor']}"
            cu_tag = f"cu{env_info['cuda']}"
            torch_tag = f"torch{env_info['torch_major']}.{env_info['torch_minor']}"

            r = requests.get(
                "https://api.github.com/repos/kingbri1/flash-attention/releases?per_page=10",
                headers={"User-Agent": "ComfyNexus/1.0"},
                timeout=(15, 30),
            )
            r.raise_for_status()
            wheels = []
            for rel in r.json():
                for a in rel.get("assets", []):
                    n = a["name"].lower()
                    if (n.endswith(".whl") and py_tag in n
                            and cu_tag in n and torch_tag in n
                            and "win_amd64" in n):
                        wheels.append({"name": a["name"], "url": a["browser_download_url"], "size": a["size"]})
            if not wheels:
                return {
                    "success": True, "mode": "manual", "wheels": [],
                    "message": (
                        f"未找到与当前环境自动匹配的 whl（{py_tag}/{cu_tag}/{torch_tag}）。"
                        "请到 https://github.com/kingbri1/flash-attention/releases 手动确认，"
                        "或跳过 Flash Attention。"
                    ),
                }
            return {"success": True, "mode": "wheel", "wheels": wheels}
        except Exception as e:
            logger.error(f"[ZeroInstall] 列出注意力 whl 失败: {e}")
            return {"success": False, "error_message": str(e)}

    def _detect_python_env(self) -> Optional[Dict]:
        """从便携包目录检测 python/cuda/torch 版本（解压完成后调用）"""
        state = self._progress.get("env") or {}
        python_exe = state.get("python_exe")
        if not python_exe or not Path(python_exe).exists():
            return None
        try:
            import subprocess
            creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            probe = subprocess.run(
                [python_exe, "-c",
                 "import sys, torch; print(sys.version_info[0]);"
                 "print(sys.version_info[1]);"
                 "print(torch.version.cuda or '0');"
                 "print(torch.__version__)"],
                capture_output=True, text=True, timeout=60, creationflags=creation,
            )
            if probe.returncode != 0:
                return None
            lines = probe.stdout.strip().splitlines()
            if len(lines) < 4:
                return None
            cuda_full = lines[2]
            torch_full = lines[3]
            m = re.search(r"(\d+)\.(\d+)", torch_full)
            return {
                "python": lines[0], "python_minor": lines[1],
                "cuda": cuda_full.split(".")[0] if cuda_full != "0" else "0",
                "torch_major": m.group(1) if m else "0",
                "torch_minor": m.group(2) if m else "0",
                "python_exe": python_exe,
                "torch_full": torch_full,
            }
        except Exception as e:
            logger.warning(f"[ZeroInstall] 探测 python 环境失败: {e}")
            return None

    # ==================== 主流程 ====================

    @serialize_response
    def zero_preview_workflows(self, repos: List[str], install_dir: str = "") -> Dict:
        """
        预拉取工作流仓库（clone 到安装目录 _wf_tmp，安装时直接拷贝选中项）

        install_dir 由前端显式传入（此时安装尚未开始，progress 里还没有）。

        Returns:
            dict: {"success", "groups": [{"repo", "dir", "files": [{"name","relPath"}]}]}
        """
        try:
            groups = []
            install_dir = (install_dir or "").strip() or (self._progress.get("installDir") or "").strip()
            if not install_dir:
                return {"success": False, "error_message": "请先返回第 1 步填写安装位置"}
            base = Path(install_dir) / "_wf_tmp"
            if base.exists():
                shutil.rmtree(base, ignore_errors=True)
            base.mkdir(parents=True, exist_ok=True)

            for repo in repos or []:
                repo = (repo or "").strip()
                if not repo:
                    continue
                repo_name = repo.rstrip("/").split("/")[-1]
                dest = base / repo_name
                try:
                    self._log(f"拉取工作流仓库 {repo_name} ...")
                    if not self._fetch_repo_zip(repo, dest):
                        self._log(f"  zip 下载不可用，回退 git clone...")
                        self._mirror_clone(repo, dest)
                    files = []
                    for wf in sorted(dest.rglob("*.json")):
                        rel = wf.relative_to(dest)
                        # 排除配置类文件
                        s = str(rel).lower()
                        if ".github" in s or "node_modules" in s or s.endswith(".settings.json"):
                            continue
                        files.append({"name": wf.stem, "relPath": str(rel).replace("\\", "/")})
                    groups.append({"repo": repo, "dir": str(dest), "name": repo_name, "files": files})
                    self._log(f"  {repo_name}: 发现 {len(files)} 条工作流")
                except Exception as e:
                    self._log(f"  {repo_name} 拉取失败: {str(e)}")
                    groups.append({"repo": repo, "dir": "", "name": repo_name,
                                   "files": [], "error": str(e)})
            return {"success": True, "groups": groups}
        except Exception as e:
            logger.error(f"[ZeroInstall] 工作流预览失败: {e}")
            return {"success": False, "error_message": str(e)}

    def select_workflow_files(self):
        """
        多选本地工作流文件（.json）

        Returns:
            dict: {"success": bool, "paths": [str]}
        """
        try:
            import webview
            window = getattr(self.environment_manager, "_window", None) or self._get_any_window()
            if window is None:
                return {"success": False, "error_message": "窗口未初始化"}
            result = window.create_file_dialog(
                dialog_type=webview.FileDialog.OPEN,
                directory=str(Path.home()),
                allow_multiple=True,
                file_types=("Workflow files (*.json)", "All files (*.*)"),
            )
            if result:
                return {"success": True, "paths": [str(p) for p in result]}
            return {"success": False, "error_message": "未选择文件"}
        except Exception as e:
            logger.error(f"[ZeroInstall] 工作流文件选择失败: {e}")
            return {"success": False, "error_message": str(e)}

    def _get_any_window(self):
        try:
            import webview
            windows = webview.windows
            return windows[0] if windows else None
        except Exception:
            return None

    @serialize_response
    def zero_start_install(self, config: Dict) -> Dict:
        """
        启动完整安装流程（后台线程执行，前端轮询 zero_get_progress）

        config: {
            installDir: str,
            assetUrl: str, assetName: str, assetSize: int,
            attentions: [{id, wheelUrl?}, ...],
            plugins: [{name, url}, ...],
            workflowRepos: [url, ...],
        }
        """
        with self._lock:
            if self._progress.get("running"):
                return {"success": False, "error_message": "已有安装任务在进行中"}

            install_dir = (config or {}).get("installDir", "").strip()
            asset_url = (config or {}).get("assetUrl", "").strip()
            if not install_dir or not asset_url:
                return {"success": False, "error_message": "缺少安装位置或下载地址"}

            # 路径安全检查：全英文无空格无特殊字符（用户已获建议，这里软校验）
            if re.search(r"[^\w\-\\/ :.()（）\u4e00-\u9fa5]", install_dir):
                return {"success": False, "error_message": "安装路径包含特殊字符，建议使用全英文路径"}

            self._progress = {
                "running": True, "done": False, "error": "",
                "step": "准备中", "percent": 0, "logs": [],
                "installDir": install_dir,
            }
            self._cancel_event.clear()

        thread = threading.Thread(
            target=self._install_pipeline, args=(config,), daemon=True, name="zero-install"
        )
        thread.start()
        return {"success": True}

    @serialize_response
    def zero_get_progress(self) -> Dict:
        with self._lock:
            p = dict(self._progress)
            p["logs"] = p.get("logs", [])[-200:]
        return {"success": True, "progress": p}

    @serialize_response
    def zero_cancel_install(self) -> Dict:
        self._cancel_event.set()
        self._log("已请求取消安装...")
        return {"success": True}

    # ---------- 内部工具 ----------

    def _get_install_dir(self) -> str:
        return (self._progress.get("installDir") or "").strip()

    def _probe_remote_size(self, url: str) -> int:
        """探测远程文件大小（size_hint 未知时用，决定是否启用 aria2 多线程）"""
        try:
            r = requests.head(url, allow_redirects=True, timeout=(8, 15),
                              headers={"User-Agent": "ComfyNexus/1.0"})
            if r.status_code >= 400:
                r = requests.get(url, stream=True, timeout=(8, 15),
                                 headers={"User-Agent": "ComfyNexus/1.0", "Range": "bytes=0-0"})
                r.close()
            cl = r.headers.get("Content-Length")
            return int(cl) if cl else 0
        except Exception:
            return 0

    def _resolve_hf_redirect(self, url: str):
        """
        解析 HF resolve 地址的真实 CDN 直链

        hf-mirror/huggingface 的 /resolve/ 地址会 302 到 CDN，aria2 直连该地址
        拿不到 Content-Length（0B/0B）→ 无法分片、无进度。预解析出真实直链。

        Returns:
            (final_url, size_bytes)——解析失败返回 (原 url, 0)
        """
        try:
            r = requests.head(url, allow_redirects=True, timeout=(15, 30),
                              headers={"User-Agent": "ComfyNexus/1.0"})
            if r.status_code >= 400:
                r = requests.get(url, stream=True, timeout=(15, 30),
                                 headers={"User-Agent": "ComfyNexus/1.0", "Range": "bytes=0-0"})
                r.close()
            size = int(r.headers.get("Content-Length") or 0)
            return r.url, size
        except Exception:
            return url, 0

    def _robust_rmtree(self, path: Path, retries: int = 4, delay: float = 2.0):
        """
        健壮删除目录：git pack-*.idx 等文件常被 git 后台守护（gc/fsmonitor）或杀毒
        短暂占用（WinError 5）。策略：清只读属性 → 等待重试（占用通常瞬时释放）。
        """
        import os
        import stat as _stat
        last_err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                shutil.rmtree(path)
                return
            except PermissionError as e:
                last_err = e
                # 清除只读属性（Windows 删除的常见阻碍）
                for f in path.rglob("*"):
                    try:
                        os.chmod(f, _stat.S_IWRITE)
                    except OSError:
                        pass
                try:
                    os.chmod(path, _stat.S_IWRITE)
                except OSError:
                    pass
                if attempt < retries - 1:
                    self._log(f"  {path.name} 部分文件被占用（第 {attempt + 1} 次），{delay:.0f}s 后重试...")
                    time.sleep(delay)
        raise last_err  # type: ignore[misc]

    def _log(self, msg: str):
        logger.info(f"[ZeroInstall] {msg}")
        ts = time.strftime("%H:%M:%S")
        with self._lock:
            self._progress["logs"].append(f"[{ts}] {msg}")

    def _set_step(self, step: str, percent: int, step_percent=None):
        """percent=总进度；step_percent=None 时保留当前步骤进度（避免进度条被清零）"""
        with self._lock:
            self._progress["step"] = step
            self._progress["percent"] = percent
            if step_percent is not None:
                self._progress["stepPercent"] = max(0, min(100, int(step_percent)))

    def _begin_download_group(self, total_bytes: int = 0):
        """
        开始一个下载组（一个步骤内的若干文件算作一组）。

        进度口径：**组内已下载总字节 / 组总字节**——不论组内是一个文件还是多个文件，
        进度条都按字节总量推进（多文件时不会因切换文件而归零重算）。

        total_bytes：已知总量时传入（各文件 size 之和），未知则传 0，
        此时组总量在下载过程中随各文件上报的 Content-Length 动态增长。
        """
        with self._lock:
            self._dl_group_total = max(0, int(total_bytes or 0))
            self._dl_files = {}
            self._dl_done = 0
            self._progress["stepPercent"] = 0

    def _end_download_group(self):
        """结束当前下载组（保留已累计的字节，用于最终结算）"""
        with self._lock:
            self._dl_files = {}
            self._dl_done = 0

    def _update_download(self, name: str, done: int, total: int):
        """
        更新当前文件下载详情，并按**组内字节总量**推进步骤进度。

        - 组内多文件：每个文件各自记录 done/total，组进度 = Σdone / max(已知总量, Σtotal)
        - 断点续传时 done 从已有字节数开始，仍计入组总量
        """
        now = time.time()
        with self._lock:
            # ---- 组内累计 ----
            prev = self._dl_files.get(name)
            if prev is None:
                self._dl_files[name] = {"done": done, "total": total}
            else:
                # 同名重试（换源重下）时 done 可能回退 → 以最新为准
                self._dl_files[name] = {"done": done, "total": total}
            sum_done = sum(v["done"] for v in self._dl_files.values())
            sum_total = sum(v["total"] for v in self._dl_files.values())
            group_total = max(self._dl_group_total, sum_total)
            group_done = min(sum_done, group_total) if group_total else sum_done
            self._dl_done = group_done
            if group_total > 0:
                self._progress["stepPercent"] = max(0, min(100, int(group_done * 100 / group_total)))

            # ---- 当前文件详情（5s 节流刷新）----
            info = self._progress.get("downloadInfo")
            if info and info.get("name") == name:
                d_ts = info.get("_ts", 0)
                d_done = info.get("done", 0)
            else:
                d_ts, d_done = 0.0, 0
            if now - d_ts < 5.0 and total and done < total:
                return  # 5s 内不刷新
            speed = (done - d_done) / max(now - d_ts, 0.001) if d_ts else 0
            self._progress["downloadInfo"] = {
                "name": name, "done": done, "total": total,
                "speed": max(int(speed), 0), "_ts": now,
                "groupDone": group_done, "groupTotal": group_total,
            }
            log_line = None
            if group_total > 0:
                pct = min(100, int(group_done * 100 / group_total))
                log_line = (f"[下载中] {name}  {done / 1048576:.1f}/{total / 1048576:.1f} MB"
                            f" | 总计 {group_done / 1048576:.1f}/{group_total / 1048576:.1f} MB"
                            f" ({pct}%)  速度 {max(int(speed), 0) / 1048576:.2f} MB/s")
            else:
                log_line = f"[下载中] {name}  {done / 1048576:.1f} MB"
        if log_line:
            self._log(log_line)  # 锁外调用（_log 内部也拿 _lock）

    def _end_download(self):
        with self._lock:
            self._progress["downloadInfo"] = None

    # ---------- 工作流下载：单链接优先 + 慢速换源 + 源数上限 ----------

    # 优质加速源候选（按稳定性排序；不够时再从脚本镜像列表/预设回退补齐）
    _WORKFLOW_FALLBACK_MIRRORS = [
        "gh-proxy.com", "ghfast.top", "ghproxy.net", "cdn.gh-proxy.org",
        "hk.gh-proxy.org", "wget.la", "gh.h233.eu.org", "gh.ddlc.top",
        "github.moeyy.xyz", "gh.monlor.com", "gh.catmak.name",
        "gh.77yun.com.cn", "g.blfrp.cn", "gh-proxy.net",
    ]
    # 单源下载速度下限（字节/秒）：低于此值视为"慢"，主动换源
    _WORKFLOW_MIN_SPEED = 16 * 1024        # 16 KB/s
    _WORKFLOW_SPEED_WINDOW = 6.0           # 速度采样窗口（秒）
    _WORKFLOW_MAX_SOURCES = 10             # 最多尝试的源数

    def _build_workflow_sources(self, url: str) -> List[str]:
        """
        为工作流 URL 构建候选下载源列表（最多 _WORKFLOW_MAX_SOURCES 个）。

        顺序：直连（单链接优先）→ 各加速源。
        非 GitHub 域名（如 huggingface）只返回直连，由调用方的通用回退处理。
        """
        sources: List[str] = []
        if not url:
            return sources
        sources.append(url)
        if "github.com" not in url:
            return sources
        # 已是镜像形式（形如 https://gh-proxy.com/https://github.com/...）不再叠加
        if "/https://github.com/" in url:
            return sources

        mirrors: List[str] = []
        # 1) 脚本维护的加速站列表（持续更新，优先）
        try:
            from backend.src.utils.mirror_script import fetch_script_mirrors
            sm = fetch_script_mirrors()
            if sm:
                mirrors.extend(m for m in sm if m and m not in mirrors)
        except Exception:
            pass
        # 2) 内置优质源
        mirrors.extend(m for m in self._WORKFLOW_FALLBACK_MIRRORS if m not in mirrors)
        # 3) 预设里的主镜像
        try:
            from backend.src.utils.github_mirror import github_mirror_manager
            primary = github_mirror_manager.get_mirror_for_type("release")
            if primary and primary not in mirrors:
                mirrors.append(primary)
        except Exception:
            pass

        for m in mirrors:
            if len(sources) >= self._WORKFLOW_MAX_SOURCES:
                break
            mirrored = url.replace("https://github.com", f"https://{m}/https://github.com", 1)
            if mirrored != url and mirrored not in sources:
                sources.append(mirrored)
        return sources[:self._WORKFLOW_MAX_SOURCES]

    def _download_workflow_file(self, url: str, dest: Path,
                                size_hint: int = 0) -> bool:
        """
        工作流文件下载：**单链接优先**，速度过慢则换源，最多尝试 10 个源。

        与通用下载的区别：
        - 不用 aria2 多源并行（工作流是小文件，单连接更稳、更易判定"慢"）
        - 速度低于阈值持续一个采样窗口 → 判定该源慢，主动换下一个源
        - 全部源失败 → 返回 False（调用方跳过该工作流，不中断整体安装）

        Returns:
            bool: 是否下载成功
        """
        sources = self._build_workflow_sources(url)
        if not sources:
            return False
        if len(sources) > 1:
            self._log(f"  可用源 {len(sources)} 个（上限 {self._WORKFLOW_MAX_SOURCES}）")
        last_error = ""
        for idx, src in enumerate(sources):
            if self._cancel_event.is_set():
                raise RuntimeError("安装已被用户取消")
            label = "直连" if idx == 0 else f"源 {idx}"
            # 速度采样窗口：记录窗口内下载字节数与耗时
            state = {"t0": time.time(), "b0": 0}
            slow = {"hit": False}

            def wf_cb(done: int, total: int, _st=state, _sl=slow):
                now = time.time()
                dt = now - _st["t0"]
                if dt >= self._WORKFLOW_SPEED_WINDOW:
                    speed = (done - _st["b0"]) / max(dt, 0.001)
                    _st["t0"], _st["b0"] = now, done
                    if speed < self._WORKFLOW_MIN_SPEED and (total <= 0 or done < total):
                        _sl["hit"] = True
                        raise _WorkflowSourceSlow(
                            f"速度过慢（{speed / 1024:.1f} KB/s < {self._WORKFLOW_MIN_SPEED / 1024:.0f} KB/s）")
                if total:
                    self._update_download(dest.name, done, total)
                else:
                    self._update_download(dest.name, done, 0)

            try:
                self._log(f"  下载 {label}: {src}")
                self._download_one(src, dest, wf_cb, size_hint=size_hint)
                self._end_download()
                return True
            except _WorkflowSourceSlow as e:
                last_error = str(e)
                self._log(f"  {label} 慢（{last_error}），换下一个源")
                # 清理半截文件，避免下一个源续传脏数据
                for p in (dest.with_suffix(dest.suffix + ".part"), dest):
                    try:
                        if p.exists():
                            p.unlink()
                    except OSError:
                        pass
            except Exception as e:
                last_error = str(e)
                self._log(f"  {label} 失败: {str(e)[:120]}")
                for p in (dest.with_suffix(dest.suffix + ".part"), dest):
                    try:
                        if p.exists():
                            p.unlink()
                    except OSError:
                        pass
        self._log(f"  已尝试 {len(sources)} 个源仍失败，跳过该工作流（{last_error[:80]}）")
        self._end_download()
        return False

    def _check_cancel(self):
        if self._cancel_event.is_set():
            raise RuntimeError("安装已被用户取消")

    def _download_with_fallback(self, url: str, dest: Path,
                                progress_cb: Optional[Callable[[int, int], None]] = None,
                                size_hint: int = 0) -> None:
        """
        下载：直连与 GitHub 镜像（gh-proxy 方式优先）逐个重试 → 全部失败抛带引导的错误。

        无系统代理且文件较大（>10MB）时镜像优先——大文件直连 GitHub 极不稳定。
        """
        from backend.src.utils.system_proxy import has_system_proxy
        from backend.src.utils import download_manifest as dm
        candidates = [url]
        # 全面测速结论优先：直连更快则直连优先（须在使用前赋值）
        direct_first = False
        try:
            from backend.src.utils.github_mirror import github_mirror_manager
            is_hf = "huggingface.co" in url or "hf-mirror.com" in url
            direct_first = github_mirror_manager.get_benchmark_direct_first(
                "huggingface" if is_hf else "github")
        except Exception:
            pass
        mirror_first = not has_system_proxy()  # 无代理默认镜像优先
        if direct_first:
            mirror_first = False  # 全面测速：直连更快 → 直连优先
        # 已完整下载（大小校验通过）→ 直接跳过，不再请求网络
        if dm.is_download_complete(self._get_install_dir(), url, dest, size_hint):
            self._log(f"已下载完成且校验通过，跳过: {dest.name}")
            if progress_cb and size_hint:
                progress_cb(size_hint, size_hint)
            return
        try:
            from backend.src.utils.github_mirror import github_mirror_manager
            preset = github_mirror_manager.get_current_preset() or {}
            is_raw = "raw.githubusercontent.com" in url
            fallback = (preset.get("fallback") or {}).get("raw" if is_raw else "release", [])
            # fallback 列表已按实测速度排列（cdn.gh-proxy.org 最快）——以它为主序；
            # 主镜像若不在列表中则追加到末尾（未实测的站不占前排）
            mirrors = [m for m in fallback if m]
            # 加速脚本镜像（最新列表）插到最前：脚本维护者会持续更新可用站
            try:
                from backend.src.utils.mirror_script import fetch_script_mirrors
                sm = fetch_script_mirrors()
                if sm:
                    mirrors = sm + [m for m in mirrors if m not in sm]
            except Exception:
                pass
            primary = github_mirror_manager.get_mirror_for_type("raw" if is_raw else "release")
            if primary and primary not in mirrors:
                mirrors.append(primary)
            if "/https://github.com/" in url:
                mirrors = []  # 已是镜像形式，避免双重前缀
            for mirror in mirrors:
                if not mirror:
                    continue
                # 镜像站 URL 规范（gh-proxy 系列）：完整前缀形式
                #   https://{mirror}/https://github.com/{owner}/{repo}/...
                # 非前缀型镜像（如 jsDelivr：https://cdn.jsdelivr.net/gh/{repo}）需按其文档单独拼接，
                # 连接数遵循各站限制（CDN/Cloudflare 一般不限单客户端并发，
                # 但可能限频——429 会自动切下一镜像）。64 分片通过「多镜像并行」实现
                #（aria2 单服务器硬上限 16 连接/站）。
                if is_raw:
                    mirrored = url.replace("https://raw.githubusercontent.com", f"https://{mirror}/https://raw.githubusercontent.com", 1)
                else:
                    mirrored = url.replace("https://github.com", f"https://{mirror}/https://github.com", 1)
                if mirrored != url and mirrored not in candidates:
                    candidates.append(mirrored)
        except Exception:
            # 兜底静态镜像列表（同为前缀型）
            for m in ["gh-proxy.com", "ghfast.top", "ghproxy.net"]:
                if "github.com" in url:
                    mirrored = url.replace("https://github.com", f"https://{m}/https://github.com", 1)
                    if mirrored not in candidates:
                        candidates.append(mirrored)

        # 大文件测速排名（50-70MB 级真实文件采样，速度快延迟低者优先）
        ranking = None
        try:
            from backend.src.utils.github_mirror import github_mirror_manager
            # 排名优先级：分类型全面测速（zip/raw/release）> 总排名 > 心跳测速 > 预设顺序
            kind = ("zip" if "codeload.github.com" in url
                    else "raw" if "raw.githubusercontent.com" in url else "release")
            ranking = (github_mirror_manager.get_benchmark_ranking_by_type(kind)
                       or github_mirror_manager.get_benchmark_mirror_ranking()
                       or github_mirror_manager.get_release_mirror_ranking())
            self._log(f"按 {kind} 类型测速排名选择镜像")
        except Exception:
            pass
        if direct_first:
            self._log("测速结论：直连更快，优先直连下载")

        if ranking:
            # 有测速排名：镜像按测速名次排序，直连接其理论速度插在最后或最前
            mirror_cands = [c for c in candidates[1:]]
            mirror_cands.sort(key=lambda c: next(
                (i for i, m in enumerate(ranking) if c.startswith(f"https://{m}/")), 999))
            if mirror_first:
                candidates = mirror_cands + [candidates[0]]
                self._log(f"未开系统代理，按实测速度优先使用镜像加速")
            else:
                candidates = [candidates[0]] + mirror_cands
        elif mirror_first and len(candidates) > 1:
            candidates = [candidates[1]] + [candidates[0]] + candidates[2:]
            self._log(f"未开系统代理，镜像加速优先")

        last_error = ""
        not_found = 0  # 404 计数：全部候选 404 = 分支/资源不存在，快速失败
        for idx, candidate in enumerate(candidates):
            if self._cancel_event.is_set():
                raise RuntimeError("安装已被用户取消")
            # 标签按 URL 是否为原始直连判定（镜像优先排序后 idx==0 也可能是镜像）
            label = "直连" if candidate == url else f"镜像 {idx}"
            try:
                self._log(f"下载: {label} {candidate}")
                # aria2 多源：只取最快的 3 个（候选已按测速/列表速度排序），
                # 慢源过多会拖累整体（实测 gh-proxy.com 0.2MB/s vs cdn 1.6MB/s）
                extra = [c for c in candidates if c != candidate][:2]
                self._download_one(candidate, dest, progress_cb, size_hint=size_hint,
                                   extra_urls=extra or None)
                try:
                    dm.record_download(self._get_install_dir(), url, dest, done=True)
                except Exception:
                    pass
                return
            except RuntimeError:
                raise
            except Exception as e:
                last_error = str(e)
                if "404 Client Error" in last_error:
                    not_found += 1
                self._log(f"  {label} 失败: {last_error}")

        # 全部候选 404 = 资源/分支不存在（换镜像无意义）→ 快速失败供分支自适应切换
        if not_found and not_found == len(candidates):
            raise RuntimeError(f"__BRANCH_NOT_FOUND__ {url}")

        raise RuntimeError(f"下载失败: {last_error}。{PROXY_GUIDE}")

    def _download_one(self, url: str, dest: Path,
                      progress_cb: Optional[Callable[[int, int], None]] = None,
                      size_hint: int = 0,
                      extra_urls: Optional[List[str]] = None) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # 断点续传衔接：上次单线程中断留下的 .part 移交 aria2 续传
        # （--continue 对无控制文件的已存在文件从末尾续传，数据不弃用）
        part_file = dest.with_suffix(dest.suffix + ".part")
        if part_file.exists() and part_file.stat().st_size > 0:
            if not dest.exists():
                try:
                    part_file.replace(dest)
                    self._log(f"  检测到未完成的下载（{part_file.stat().st_size / 1048576:.1f}MB），继续下载")
                except OSError:
                    pass
        # 大文件（>10MB）且 aria2 可用 → 多线程多源下载（默认 64 分片，失败 32/16 降级）
        from backend.src.utils.aria2_helper import aria2_download, find_aria2
        # size_hint 未知（插件 zip/工作流等）先探测真实大小，避免大文件退化成单线程
        if size_hint <= 0 and find_aria2():
            probed = self._probe_remote_size(url) or (
                self._probe_remote_size(extra_urls[0]) if extra_urls else 0)
            if probed > 1024 * 1024:
                size_hint = probed
                self._log(f"  文件大小 {(probed / 1048576):.1f}MB，启用多线程下载")
        if size_hint > 1024 * 1024 and find_aria2():  # >1MB 即多线程（镜像站单连接限速严重）
            conn_desc = min(64, max(1, int(size_hint // (1024 * 1024)))) if size_hint else 64
            self._log(f"  使用 aria2 多线程下载（{conn_desc} 分片，多镜像源并行）...")
            if aria2_download([url] + (extra_urls or []), dest, progress_cb, size_hint,
                              cancel_ev=self._cancel_event, log_fn=self._log,
                              max_connections=max(1, min(64, int(size_hint // (1024 * 1024))))):
                return
            self._log("  回退单线程下载")
        tmp = dest.with_suffix(dest.suffix + ".part")
        # 断点续传：.part 已有内容则从其大小续传（服务器不支持 Range 时从头重来）
        # aria2 中断的 dest 部分文件（无 .aria2 控制时）也衔接为 .part 续传
        if not tmp.exists() and dest.exists() and 0 < dest.stat().st_size != size_hint:
            try:
                dest.replace(tmp)
                self._log(f"  检测到未完成的下载（{dest.stat().st_size / 1048576:.1f}MB），继续下载")
            except OSError:
                pass
        headers = {"User-Agent": "ComfyNexus/1.0"}
        mode = "wb"
        done = 0
        part_size = tmp.stat().st_size if tmp.exists() else 0
        if part_size > 0:
            headers["Range"] = f"bytes={part_size}-"
        with requests.get(url, stream=True, timeout=(30, 120),
                          headers=headers, allow_redirects=True) as r:
            r.raise_for_status()
            resumed = (r.status_code == 206 and part_size > 0)
            if resumed:
                done = part_size
                mode = "ab"
                self._log(f"  断点续传: 从 {done / 1048576:.1f}MB 继续")
            else:
                done = 0  # 服务器不支持 Range，从头下载
            total = int(r.headers.get("Content-Length") or 0) + (done if resumed else 0)
            with open(tmp, mode) as f:
                for chunk in r.iter_content(1 << 20):
                    self._check_cancel()
                    if chunk:
                        f.write(chunk)
                        done += len(chunk)
                        if progress_cb:
                            progress_cb(done, total)
            # 完整性：期望大小已知则校验
            if size_hint > 0 and done != size_hint and total != done:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(f"下载不完整（{done}/{size_hint} 字节），已删除待重下")
            tmp.replace(dest)

    def _fetch_repo_zip(self, repo_url: str, dest: Path) -> bool:
        """
        GitHub 仓库获取（zip 方式，走镜像加速 + aria2 多线程 + 断点续传）：
        1. 下载整个仓库压缩包（main → master 分支自适应）
        2. 解压后把 {repo}-{branch}/ 内层内容规范移到目标目录（消除嵌套）

        Returns:
            bool: 是否成功；失败调用方可回退 git clone
        """
        repo = re.sub(r"^https?://[^/]+/", "", repo_url.strip().strip("/"))
        repo = re.split(r"/(tree|blob|resolve)/", repo)[0].strip("/")
        repo = repo[:-4] if repo.endswith(".git") else repo  # 剥 .git 后缀（zip 地址不含 .git）
        if repo.count("/") < 1:
            return False
        owner_repo = repo
        repo_name = repo.split("/")[-1]

        # 解压工作区放系统临时目录（避免 custom_nodes 里残留 _zip_* 文件夹）
        import tempfile as _tf
        work = Path(_tf.mkdtemp(prefix=f"cnx_zip_{repo_name}_"))
        try:
            for branch in ("main", "master"):
                # codeload 是 GitHub 专用打包端点：镜像站对它支持度远高于 archive
                # （实测 gh-proxy.org/edgeone 对 codeload 返回 206，对 archive 返回 000）
                zip_url = f"https://codeload.github.com/{owner_repo}/zip/refs/heads/{branch}"
                tmp_zip = work / f"{repo_name}_{branch}.zip"
                try:
                    # 统一下载缓存：zip 先落全局缓存，再从缓存解压（重装/换目录复用）
                    from backend.src.utils import download_cache as dc
                    def _zip_cb(done, total, _n=f"{repo_name}.zip"):
                        self._update_download(_n, done, total)
                    probed = self._probe_remote_size(zip_url)
                    cached_zip = dc.fetch(zip_url, f"{repo_name}_{branch}.zip",
                                          size_hint=probed, progress_cb=_zip_cb,
                                          cancel_ev=self._cancel_event, log_fn=self._log)
                    self._end_download()
                    tmp_zip = cached_zip
                    extract = work / f"_extract_{branch}"
                    shutil.rmtree(extract, ignore_errors=True)
                    extract.mkdir(parents=True, exist_ok=True)
                    # zip 用 Python 内置 zipfile（7zr 不支持 zip 格式）
                    import zipfile
                    with zipfile.ZipFile(tmp_zip) as zf:
                        zf.extractall(extract)
                    # 嵌套规范化：zip 内顶层为 {repo}-{branch}/
                    inner = extract / f"{repo_name}-{branch}"
                    if not inner.is_dir():
                        dirs = [p for p in extract.iterdir() if p.is_dir()]
                        inner = dirs[0] if len(dirs) == 1 else None
                    if inner is None:
                        raise RuntimeError("zip 内未找到仓库根目录")
                    dest.mkdir(parents=True, exist_ok=True)
                    for item in inner.iterdir():
                        target = dest / item.name
                        if target.exists():
                            if item.is_dir():
                                shutil.rmtree(target)
                            else:
                                target.unlink()
                        shutil.move(str(item), str(target))
                    return True
                except Exception as e:
                    if "__BRANCH_NOT_FOUND__" in str(e):
                        self._log(f"  {branch} 分支不存在（404），尝试其他分支...")
                    else:
                        logger.debug(f"[ZeroInstall] zip 方式失败 ({branch}): {e}")
                    # 清掉失败的半截 zip（保留成功的供重装跳过下载）
                    if tmp_zip.exists():
                        tmp_zip.unlink(missing_ok=True)
                    continue
            return False
        finally:
            # zip 在全局缓存（dc.fetch），工作区整个清掉
            shutil.rmtree(work, ignore_errors=True)

    def _bind_git_remote(self, dest: Path, repo_url: str) -> None:
        """给 zip 安装的插件自动 init + 绑定原始 GitHub 地址（插件管理页识别更新地址用）"""
        try:
            from backend.src.core.plugin.git_utils import GitUtils
            from backend.src.utils.git_config import get_git_executable
            gu = GitUtils(git_path=get_git_executable())
            # 归一化为纯 https://github.com/owner/repo（剥离 codeload 形态与镜像前缀）
            import re as _re
            norm = repo_url.strip().rstrip("/")
            # 1. 剥离镜像前缀：.../https://github.com/owner/repo → github.com/owner/repo
            if "/https://github.com/" in norm:
                norm = norm.split("/https://github.com/", 1)[1]
            # 2. codeload 形态 → github.com/owner/repo
            if "codeload.github.com/" in norm:
                m = _re.search(r"codeload\.github\.com/([^/]+/[^/]+)", norm)
                if m:
                    norm = m.group(1)
            # 3. 统一补 https://github.com/ 前缀
            if not norm.startswith("https://github.com/"):
                norm = f"https://github.com/{norm}"
            ok, msg = gu.add_remote_url(dest, norm)
            if ok:
                # 后台 fetch + 对齐远端分支（建立完整 git 关联，避免「分支不存在」）
                gu.finalize_bind_async(dest)
            self._log(f"  绑定更新地址: {norm}" + ("" if ok else f"（{msg}）"))
        except Exception as e:
            logger.debug(f"[ZeroInstall] 绑定 git 地址失败 {dest.name}: {e}")

    def _mirror_clone(self, repo_url: str, dest: Path, depth: bool = True) -> None:
        """git clone（复用 GitManager 的镜像 fallback）"""
        from backend.src.core.git_manager import GitManager
        args = ["clone", repo_url, str(dest)]
        if depth:
            args = ["clone", "--depth", "1", repo_url, str(dest)]
        gm = GitManager(repo_path=str(dest.parent))
        result = gm._run_git_command(args, cwd=dest.parent, timeout=600)
        if not result.get("success"):
            raise RuntimeError(f"git clone 失败: {result.get('error', '')}")

    def _run_python(self, python_exe: Path, args: List[str], timeout: int = 1800) -> subprocess.CompletedProcess:
        """
        执行 python 子进程。

        pip install 走 PyPI 镜像（若启用）；**流式**读取输出并解析
        "Collecting/Installing <包名>" 行，实时推送当前正在处理的依赖到
        progress["currentDeps"]（前端滚动展示），而不是等进程结束才拿结果。
        """
        import subprocess
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        # pip install 走 PyPI 镜像（若启用）
        try:
            from backend.src.utils.pypi_mirror import pypi_mirror_manager
            if pypi_mirror_manager.is_enabled() and "install" in args:
                index = pypi_mirror_manager.get_pip_index_url()
                args = args + ["-i", index]
        except Exception:
            pass
        cmd = [str(python_exe)] + args

        # ---- 流式执行：实时解析 pip 输出 ----
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creation,
            )
        except Exception:
            # 无法流式时回退一次性执行
            return subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                creationflags=creation, encoding="utf-8", errors="replace",
            )

        out_lines: List[str] = []
        dep_re = re.compile(r"^\s*(?:Collecting|Downloading|Using cached)\s+([A-Za-z0-9._\-]+)")
        inst_re = re.compile(r"^\s*Installing collected packages:\s*(.+)$")
        try:
            if proc.stdout:
                for line in proc.stdout:
                    line = line.rstrip("\n")
                    out_lines.append(line)
                    # 解析当前依赖名（pip 输出行首可能有进度条 \r，用最后一段）
                    seg = line.split("\r")[-1]
                    m = inst_re.match(seg)
                    if m:
                        names = [x.strip() for x in m.group(1).split(",") if x.strip()]
                        if names:
                            self._set_current_dep(f"安装 {names[0]}" + (f" 等 {len(names)} 个包" if len(names) > 1 else ""))
                        continue
                    m = dep_re.match(seg)
                    if m:
                        self._set_current_dep(f"下载 {m.group(1)}")
        except Exception:
            pass
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            raise
        finally:
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass

        stdout = "\n".join(out_lines)
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stdout)

    def _set_current_dep(self, text: str):
        """更新当前正在安装的依赖（前端滚动展示）"""
        with self._lock:
            self._progress["currentDep"] = text

    # ---------- 主流程各步骤 ----------

    def _install_pipeline(self, config: Dict):
        try:
            install_dir = Path(config["installDir"])
            asset_url = config["assetUrl"]
            asset_name = config.get("assetName", "ComfyUI_portable.7z")

            # ---- 步骤 1：下载 7z ----
            self._set_step("下载 ComfyUI 便携包", 2, 0)
            # ---- 步骤 0：安装前全面测速（aria2，确定后续下载的镜像排名/直连优选）----
            self._set_step("测速中（检查各加速站速度）", 1, 0)
            self._log("=== 第 0 步：全面测速（原始链接 / 系统代理 / 各加速站）===")
            try:
                from backend.src.utils.speed_benchmark import run_full_speed_test
                run_full_speed_test(log_fn=self._log)
            except Exception as e:
                self._log(f"  测速跳过: {e}")

            self._log(f"=== 第 1 步：下载 {asset_name} ===")
            tmp_dir = install_dir / "_comfynexus_tmp"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            # 统一下载缓存：旧临时目录的包先迁入全局缓存（升级不重下）
            from backend.src.utils import download_cache as dc
            dc.migrate_legacy(install_dir, log_fn=self._log)
            archive = dc.cached_path(asset_url, asset_name)
            # 历史坏缓存清理：上次解压 Data Error 的包会在 _download_with_fallback
            # 里通过「解压后校验」重新标记；这里先清掉明确损坏的缓存文件（7z 测不通）
            _damaged_flag = archive.with_suffix(archive.suffix + ".bad")
            if _damaged_flag.exists():
                self._log("检测到损坏缓存标记，删除坏包重新下载")
                archive.unlink(missing_ok=True)
                _damaged_flag.unlink(missing_ok=True)

            asset_size = int(config.get("assetSize") or 0)
            # 便携包为单文件下载，组总量即包大小
            self._begin_download_group(asset_size)

            def dl_cb(done: int, total: int):
                total = total or asset_size
                pct = min(30, 2 + int(done * 28 / total)) if total else 2
                self._set_step(f"下载便携包", pct)
                self._update_download(asset_name, done, total)

            self._download_with_fallback(asset_url, archive, dl_cb, size_hint=asset_size)
            self._end_download()

            # ---- 步骤 2：解压 + 规范化 ----
            self._set_step("解压便携包", 32, 0)
            self._log("=== 第 2 步：解压（约 1-3 分钟）===")
            extract_to = tmp_dir / "extracted"
            # 清掉上次解压残留，防止新旧文件混合
            shutil.rmtree(extract_to, ignore_errors=True)
            extract_to.mkdir(parents=True, exist_ok=True)
            # 默认直接使用 7-Zip（BCJ2 等 7z 全编码器原生支持，速度也更快）
            try:
                self._extract_with_7z(archive, extract_to)
            except FileNotFoundError:
                # 完全没有 7-Zip（系统未装且内置 7zr 缺失）→ py7zr 兜底
                self._log("未找到 7-Zip，回退内置 py7zr 解压...")
                import py7zr
                with py7zr.SevenZipFile(str(archive), mode="r") as z:
                    z.extractall(path=str(extract_to))
            # 保留安装包：重装时跳过下载直接解压（manifest 已记录，完整性校验通过即跳过）
            self._log(f"已保留安装包（{archive.stat().st_size / 1048576:.0f}MB），重装时将跳过下载")

            # 规范化：定位含 run_nvidia_gpu.bat / main.py 的真实根，消除嵌套
            root = self._locate_portable_root(extract_to)
            if root is None:
                raise RuntimeError("解压后未找到 ComfyUI 结构（run_*.bat 或 ComfyUI/main.py）")

            self._log(f"便携包根目录: {root.name}")
            # 把根内容移到 install_dir（重装语义：先彻底清空旧内容，防止 move 嵌套进残留目录）
            if root.resolve() != install_dir.resolve():
                from backend.src.utils.download_manifest import MANIFEST_NAME
                # 保留：下载记录 manifest、当前解压工作目录 _comfynexus_tmp（源文件在里面）
                keep = {MANIFEST_NAME, "_comfynexus_tmp"}
                for old_item in list(install_dir.iterdir()):
                    if old_item.name in keep:
                        continue
                    try:
                        if old_item.is_dir():
                            self._robust_rmtree(old_item)
                        else:
                            old_item.unlink()
                    except OSError as oe:
                        raise RuntimeError(
                            f"清空旧安装目录失败（{old_item.name}）：文件可能被占用，"
                            f"请关闭 ComfyUI / git 后台进程 / 资源管理器中该目录的窗口后重试。{oe}"
                        )
                try:
                    for item in root.iterdir():
                        shutil.move(str(item), str(install_dir / item.name))
                except OSError as oe:
                    raise RuntimeError(f"移动安装文件失败: {oe}")
            # 只清解压目录，保留安装包（重装时跳过下载直接解压）
            shutil.rmtree(tmp_dir / "extracted", ignore_errors=True)

            comfy_dir = install_dir / "ComfyUI"
            if not (comfy_dir / "main.py").exists():
                # 兜底诊断：嵌套结构检测
                nested = list(install_dir.glob("*/ComfyUI/main.py")) + list(install_dir.glob("*/*/ComfyUI/main.py"))
                hint = f"（检测到嵌套结构：{nested[0]}，请重试安装）" if nested else ""
                raise RuntimeError(f"目录规范化失败：{comfy_dir} 下没有 main.py {hint}")
            self._log(f"目录校验通过: {install_dir}")

            python_exe = self._find_embedded_python(install_dir)
            if python_exe is None:
                raise RuntimeError("未找到便携包内置 Python（python_embeded/python.exe）")

            # 补齐 Python 开发文件（embeddable 版缺 include/libs，编译类节点需要）
            try:
                from backend.src.utils.python_dev_headers import ensure_python_dev_headers
                ensure_python_dev_headers(python_exe, log_fn=self._log)
            except Exception as e:
                self._log(f"  include/libs 补全跳过: {e}")
            self._progress["env"] = {"python_exe": str(python_exe)}

            # ---- 步骤 3：注意力后端 ----
            attentions = config.get("attentions") or []
            if attentions:
                self._set_step("安装注意力后端", 55, 0)
                self._log("=== 第 3 步：安装注意力后端 ===")
                for att in attentions:
                    self._check_cancel()
                    att_id = att.get("id")
                    if att_id in ("ck", "split", "pytorch", "quad"):
                        self._log(f"  {att.get('name', att_id)}: 官方已包含，跳过")
                        continue
                    if att_id == "sage":
                        self._log("  Sage Attention: pip 安装中...")
                        r = self._run_python(python_exe, ["-m", "pip", "install", "sageattention"], timeout=900)
                        if r.returncode == 0:
                            self._log("  Sage Attention 安装成功")
                        else:
                            self._log(f"  Sage Attention 安装失败（不影响使用，可稍后手动装）: {r.stderr[-200:]}")
                        continue
                    if att_id == "flash":
                        wheel_url = att.get("wheelUrl")
                        if not wheel_url:
                            self._log("  Flash Attention: 未选择 whl 版本，跳过")
                            continue
                        self._log(f"  Flash Attention: 下载 whl...")
                        try:
                            # 统一缓存：whl 落 /download（重装/多环境复用，不再删除）
                            from backend.src.utils import download_cache as dc
                            whl_file = dc.fetch(wheel_url, wheel_url.split("/")[-1],
                                                size_hint=int(att.get("size") or 0),
                                                cancel_ev=self._cancel_event, log_fn=self._log)
                            r = self._run_python(python_exe, ["-m", "pip", "install", str(whl_file)], timeout=900)
                            self._log("  Flash Attention " + ("安装成功" if r.returncode == 0 else f"安装失败: {r.stderr[-200:]}"))
                        except Exception as e:
                            self._log(f"  Flash Attention 下载失败: {str(e)[:150]}")

            # ---- 步骤 4：大模型下载（勾选的 HF 文件）----
            models = config.get("models") or []
            self._log(f"[模型] 本次收到 {len(models)} 个待下载模型")
            if not models:
                self._log("=== 第 4 步：未勾选模型，跳过模型下载 ===")
            if models:
                self._set_step("下载模型", 62, 0)
                # 多模型组：总量 = 各模型 size 之和（未知则为 0，随下载动态增长）
                _model_total = sum(int(m.get("size") or 0) for m in models)
                self._begin_download_group(_model_total)
                self._log(f"=== 第 4 步：下载模型文件（共 {len(models)} 个，hf-mirror 镜像）===")
                models_base = (config.get("sharedModelDir") or "").strip() or str(comfy_dir / "models")
                for m in models:
                    self._check_cancel()
                    url = m.get("url", "")
                    name = m.get("name", "")
                    group = (m.get("group") or "").strip() or "未分组"
                    dir_type = m.get("dir") or "unet"
                    if not url:
                        continue
                    # 目标：models_base/<dir_type>/<模型名>/<文件名>
                    dest_dir = Path(models_base) / dir_type / group
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    dest = dest_dir / name
                    m_size = int(m.get("size") or 0)
                    if dest.exists() and (m_size <= 0 or dest.stat().st_size == m_size):
                        self._log(f"  {name}: 已存在且校验通过，跳过")
                        continue
                    if dest.exists():
                        self._log(f"  {name}: 检测到未完成的下载（{dest.stat().st_size / 1048576:.0f}/{m_size / 1048576:.0f}MB），继续下载")
                    size_text = f"{m.get('size', 0) / 1073741824:.2f}GB" if m.get("size") else "?"
                    self._log(f"  {name} ({size_text}) -> {dest_dir}")
                    try:
                        # hf-mirror 失败自动回退官方源
                        m_size = int(m.get('size') or 0)
                        # hf /resolve/ 地址会 302，aria2 直连拿不到 Content-Length 无法分片：
                        # 预解析真实 CDN 直链，镜像源 + 官方源双源并行（aria2 2x16 连接竞速）
                        real_url, real_size = self._resolve_hf_redirect(url)
                        official_url = url.replace("https://hf-mirror.com/", "https://huggingface.co/", 1)
                        if real_url != url:
                            self._log(f"  已解析加速直链（{real_size / 1048576:.0f}MB），双源并行下载")
                        real_official, official_size = self._resolve_hf_redirect(official_url)
                        src_urls = [u for u in {real_url, real_official} if u]
                        main_size = real_size or official_size or m_size
                        def model_cb(done, total, _name=name):
                            self._update_download(_name, done, total or main_size)
                        try:
                            # 统一缓存：先下到全局缓存（断点续传/重装复用），再复制到 models
                            from backend.src.utils import download_cache as dc
                            main_src = src_urls[0] if src_urls else url
                            backup = src_urls[1:] if len(src_urls) > 1 else None
                            cached = dc.fetch(main_src, name, size_hint=main_size,
                                              progress_cb=model_cb, extra_urls=backup,
                                              cancel_ev=self._cancel_event, log_fn=self._log)
                            if cached.resolve() != dest.resolve():
                                shutil.copy2(str(cached), str(dest))
                            self._log(f"  {name}: 从缓存复制完成")
                        except Exception as e:
                            if '__BRANCH_NOT_FOUND__' not in str(e):
                                self._log(f"  加速直链失败，回退官方 resolve 地址: {official_url}")
                            self._download_one(official_url, dest, model_cb, size_hint=main_size)
                            from backend.src.utils import download_manifest as _dm
                            _dm.record_download(self._get_install_dir(), url, dest, done=True)
                        self._end_download()
                        self._log(f"  {name} 完成")
                    except Exception as e:
                        self._log(f"  {name} 下载失败: {str(e)}（可稍后手动下载）")

            # ---- 步骤 5：插件 ----
            plugins = config.get("plugins") or []
            if plugins:
                self._set_step("安装插件", 70, 0)
                # 清理历史版本残留的 _zip_* 工作目录（旧实现遗留在 custom_nodes 里）
                try:
                    cn_dir = install_dir / "ComfyUI" / "custom_nodes"
                    if cn_dir.is_dir():
                        for zd in cn_dir.glob("_zip_*"):
                            shutil.rmtree(zd, ignore_errors=True)
                except Exception:
                    pass
                self._log("=== 第 5 步：安装插件（custom_nodes）===")
                nodes_dir = comfy_dir / "custom_nodes"
                nodes_dir.mkdir(exist_ok=True)
                for p in plugins:
                    self._check_cancel()
                    url = p.get("url", "")
                    name = p.get("name") or url.rstrip("/").split("/")[-1]
                    dest = nodes_dir / name
                    if dest.exists():
                        self._log(f"  {name}: 已存在，跳过")
                        continue
                    self._log(f"  安装插件 {name} ...")
                    try:
                        # 优先 zip 整包下载（镜像加速 + aria2 多线程），失败回退 git clone（镜像）
                        if self._fetch_repo_zip(url, dest):
                            # zip 方式无 .git → 自动 init + 绑定原始 GitHub 地址，
                            # 使插件管理页能识别更新地址（无需用户手动填写）
                            self._bind_git_remote(dest, url)
                            self._log(f"  {name} 完成")
                        else:
                            self._log(f"  zip 下载不可用，回退 git clone...")
                            try:
                                self._mirror_clone(url, dest)
                                self._log(f"  {name} 完成")
                            except Exception as clone_err:
                                # 所有自动方案失败：提示用户手动处理（多方案兜底终点）
                                self._log(
                                    f"  {name} 多种方式均失败（zip 镜像/直连/克隆）："
                                    f"{clone_err}"
                                )
                                self._log(
                                    f"  请手动下载 {url} 的压缩包，解压到 "
                                    f"{dest} 后重新点击安装（已下载的其余文件会跳过）"
                                )
                                raise
                    except Exception as e:
                        self._log(f"  {name} 失败: {str(e)}（不影响其他插件）")

            # ---- 步骤 6：工作流（按用户逐条选择拷贝）----
            selected_workflows = config.get("workflows") or []
            legacy_repos = config.get("workflowRepos") or []
            if selected_workflows or legacy_repos:
                self._set_step("安装工作流", 78, 0)
                self._log("=== 第 6 步：安装工作流 ===")
                wf_dir = comfy_dir / "user" / "default" / "workflows"
                wf_dir.mkdir(parents=True, exist_ok=True)
                tmp_base = install_dir / "_wf_tmp"
                count = 0

                # 新模式：逐条拷贝预取的选中项
                for w in selected_workflows:
                    rel = (w.get("relPath") or "").replace("/", "\\")
                    repo_name = w.get("repoName") or ""
                    src = tmp_base / repo_name / rel
                    if not src.is_file():
                        self._log(f"  跳过（预取文件缺失）: {w.get('name')}")
                        continue
                    target = wf_dir / f"{repo_name}_{Path(rel).name}"
                    shutil.copy2(str(src), str(target))
                    count += 1

                # 兼容旧模式：直接传仓库列表（全量拷贝）
                for repo in legacy_repos:
                    repo_name = repo.rstrip("/").split("/")[-1]
                    src_dir = tmp_base / repo_name
                    if not src_dir.is_dir():
                        continue
                    for wf in src_dir.rglob("*.json"):
                        if ".github" in str(wf).lower():
                            continue
                        shutil.copy2(str(wf), str(wf_dir / f"{repo_name}_{wf.name}"))
                        count += 1

                self._log(f"已放入 {count} 条工作流到 ComfyUI/user/default/workflows")
            # ---- 步骤 6b：自定义工作流（本地导入 / 泛网址）----
            custom_workflows = config.get("customWorkflows") or []
            if custom_workflows:
                self._set_step("安装自定义工作流", 80, 0)
                wf_dir = comfy_dir / "user" / "default" / "workflows"
                wf_dir.mkdir(parents=True, exist_ok=True)
                for cw in custom_workflows:
                    self._check_cancel()
                    try:
                        if cw.get("type") == "file":
                            src = Path(cw["path"])
                            if src.is_file():
                                shutil.copy2(str(src), str(wf_dir / src.name))
                                self._log(f"  已导入本地工作流: {src.name}")
                            else:
                                self._log(f"  本地文件不存在，跳过: {src}")
                        elif cw.get("type") == "url":
                            url = cw["url"]
                            name = cw.get("name") or url.rstrip("/").split("/")[-1]
                            # URL 解码（%E5%... 中文文件名）并剥离 .json 之外的编码
                            import urllib.parse as _up
                            name = _up.unquote(name)
                            if not name.endswith(".json"):
                                name += ".json"
                            dest = wf_dir / name
                            self._log(f"  下载自定义工作流: {name}")
                            # GitHub blob 页面地址 → raw 文件地址
                            raw_url = re.sub(r"/blob/", "/raw/", url)
                            # 多源下载：单链接优先，速度慢则换源，最多 10 个源；
                            # 全部失败则跳过该工作流（不中断整体安装）
                            if self._download_workflow_file(raw_url, dest, size_hint=0):
                                self._log(f"  {name} 完成")
                            else:
                                self._log(f"  跳过工作流 {name}（所有源均失败）")
                                try:
                                    if dest.exists():
                                        dest.unlink()
                                except OSError:
                                    pass
                    except Exception as e:
                        self._log(f"  自定义工作流失败: {str(e)}")
            try:
                shutil.rmtree(tmp_base, ignore_errors=True)
            except (NameError, UnboundLocalError):
                pass  # 未执行过工作流预取，无临时目录

            # ---- 步骤 7：依赖 ----
            self._set_step("安装 Python 依赖", 90, 0)
            self._log("=== 第 7 步：安装 ComfyUI 依赖（requirements.txt）===")
            req_file = comfy_dir / "requirements.txt"
            if req_file.exists():
                r = self._run_python(python_exe, ["-m", "pip", "install", "-r", str(req_file)], timeout=3600)
                if r.returncode == 0:
                    self._log("ComfyUI 依赖安装完成")
                else:
                    self._log(f"依赖安装存在告警/失败项: ...{r.stderr[-300:]}")
            else:
                self._log("未找到 requirements.txt，跳过")
            self._set_current_dep("")

            # ---- 插件依赖：收集各插件 requirements.txt 一起安装（自动并入，冲突检测）----
            self._log("--- 安装各插件的 requirements.txt ---")
            cn_dir = comfy_dir / "custom_nodes"
            plugin_reqs: List[Path] = []
            if cn_dir.is_dir():
                for pr in sorted(cn_dir.glob("*/requirements.txt")):
                    plugin_reqs.append(pr)
            merged = None
            if plugin_reqs:
                self._log(f"发现 {len(plugin_reqs)} 个插件依赖文件，合并安装中...")
                merged = cn_dir / "_merged_plugin_requirements.txt"
                seen_lines = set()
                with open(merged, "w", encoding="utf-8") as out:
                    for pr in plugin_reqs:
                        try:
                            for line in pr.read_text(encoding="utf-8", errors="replace").splitlines():
                                s = line.strip()
                                if s and not s.startswith("#") and s.lower() not in seen_lines:
                                    seen_lines.add(s.lower())
                                    out.write(s + "\n")
                        except Exception:
                            continue
                rm = self._run_python(python_exe, ["-m", "pip", "install", "-r", str(merged)], timeout=3600)
                self._log("插件依赖合并安装完成" if rm.returncode == 0
                          else f"插件依赖安装存在告警/失败项: ...{rm.stderr[-300:]}")
                try:
                    merged.unlink(missing_ok=True)
                except Exception:
                    pass

            # ---- 兼容性冲突检测：pip check + 自动修复提示 ----
            self._log("--- 依赖兼容性检查（pip check）---")
            rc = self._run_python(python_exe, ["-m", "pip", "check"], timeout=120)
            if rc.returncode == 0:
                self._log("依赖兼容性检查通过，无版本冲突")
            else:
                conflicts = (rc.stdout or rc.stderr or "").strip()
                self._log(f"检测到依赖冲突，尝试自动修复（按冲突项重装兼容版本）...")
                # 逐条解析“X requires Y which is not installed / has incompatible version”
                fixed = 0
                for line in conflicts.splitlines():
                    line = line.strip()
                    if "which requires" in line and "but you have" in line:
                        try:
                            # 形如：pkgA requires pkgB<ver, but you have pkgB other-ver.
                            req_part = line.split(" which requires ")[1].split(", but you have")[0].strip()
                            # 取“包名+约束”重装（pip 会解析为满足约束的版本）
                            if req_part and not req_part.startswith("-"):
                                self._log(f"  修复: pip install {req_part}")
                                fr = self._run_python(python_exe, ["-m", "pip", "install", *req_part.split()], timeout=600)
                                if fr.returncode == 0:
                                    fixed += 1
                        except Exception:
                            continue
                rc2 = self._run_python(python_exe, ["-m", "pip", "check"], timeout=120)
                if rc2.returncode == 0:
                    self._log(f"冲突已自动修复（{fixed} 项），兼容性检查通过")
                else:
                    self._log(f"仍有 {fixed} 项自动修复完成，其余冲突需手动处理：")
                    for line in (rc2.stdout or "").splitlines()[:6]:
                        self._log(f"  {line.strip()}")

            # ---- 共享文件夹映射落地 ----
            model_paths = config.get("modelPaths") or {}
            workspace = config.get("workspace") or {}
            if model_paths or workspace:
                self._set_step("写入目录映射", 96, 0)
                try:
                    self._write_mappings(install_dir, model_paths, workspace)
                except Exception as me:
                    self._log(f"目录映射写入失败（不影响主流程）: {me}")

            # ---- 完成 ----
            self._set_step("安装完成", 100, 100)
            self._log("=== ✅ 全部完成 ===")
            self._log(f"安装位置: {install_dir}")
            if not (config.get("models") or []):
                self._log("未勾选模型下载；如需模型请按向导第 4 步的链接自行下载并放入对应文件夹。")
            self._log("现在可以到【工作台】把环境指向该目录并启动 ComfyUI。")
            with self._lock:
                self._progress["done"] = True
                self._progress["running"] = False
        except Exception as e:
            logger.error(f"[ZeroInstall] 安装失败: {e}", exc_info=True)
            with self._lock:
                self._progress["running"] = False
                self._progress["done"] = True
                self._progress["error"] = str(e)
                self._progress["step"] = "安装失败"
                if "无法连接" in str(e) or "下载失败" in str(e):
                    self._progress["error"] = str(e)

    def _extract_with_7z(self, archive: Path, extract_to: Path):
        """
        用 7-Zip 解压（BCJ2 等编码器 py7zr 不支持时的回退）

        顺序：系统已装 7-Zip → 打包内置 tools/7zr.exe → 报错
        7zr.exe 为 7-Zip 官方精简命令行版（602KB），支持全部 .7z 编码器。
        """
        import subprocess

        candidates = []
        # 系统 7-Zip
        for pf in ["C:\\Program Files\\7-Zip\\7z.exe", "C:\\Program Files (x86)\\7-Zip\\7z.exe"]:
            p = Path(pf)
            if p.is_file():
                candidates.append(p)
        # 内置 7zr.exe：与 aria2c 同目录（tools/，frozen=exe 同级 / 开发=backend/tools）
        from backend.src.utils.aria2_helper import find_aria2 as _find_aria2_exe
        _aria2 = _find_aria2_exe()
        if _aria2:
            candidates.append(_aria2.parent / "7zr.exe")

        seven_zip = next((c for c in candidates if c.is_file()), None)
        if seven_zip is None:
            raise FileNotFoundError("未找到 7-Zip（系统与内置 7zr.exe 均不存在）")

        self._log(f"使用 {seven_zip.name} 解压...")
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            [str(seven_zip), "x", str(archive), f"-o{extract_to}", "-y", "-bso0", "-bsp0"],
            capture_output=True, text=True, timeout=1800,
            creationflags=creation, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout) or ""
            if "Data Error" in err or "CRC" in err:
                # 下载包损坏（多源签名不一致等）→ 标记坏缓存，下次自动重下
                bad = archive.with_suffix(archive.suffix + ".bad")
                try:
                    bad.write_text("damaged", encoding="utf-8")
                except Exception:
                    pass
                self._log("检测到下载包损坏（Data Error），已标记，下次将自动重新下载")
            raise RuntimeError(f"7-Zip 解压失败: {err}")
        self._log("7-Zip 解压完成")

    def _locate_portable_root(self, base: Path) -> Optional[Path]:
        """定位便携包真实根目录（防嵌套）：含 run_*.bat 或 ComfyUI/main.py 的最浅目录"""
        candidates = [base] + list(base.iterdir())
        for c in candidates:
            if not c.is_dir():
                continue
            has_bat = any(c.glob("run_*.bat"))
            has_main = (c / "ComfyUI" / "main.py").exists()
            if has_bat or has_main:
                return c
        # 更深一层（罕见双层嵌套）
        for sub in base.iterdir():
            if sub.is_dir():
                for c in sub.iterdir():
                    if c.is_dir() and (any(c.glob("run_*.bat")) or (c / "ComfyUI" / "main.py").exists()):
                        return c
        return None

    def _find_embedded_python(self, install_dir: Path) -> Optional[Path]:
        for name in ["python_embeded", "standalone-env", "python"]:
            for exe in [install_dir / name / "python.exe", install_dir / name / "Scripts" / "python.exe"]:
                if exe.exists():
                    return exe
        return None
