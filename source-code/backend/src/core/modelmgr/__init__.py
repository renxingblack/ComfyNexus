"""
模型库管理模块

提供 ComfyUI 环境的本地模型扫描与多源下载能力：
- model_scanner.py   本地模型扫描（models/ 全部子目录）
- model_downloader.py 网络模型下载（HuggingFace / HF-Mirror / ModelScope / Civitai / 直链）
- model_linker.py    网络链接关联（魔搭/ HF 搜索 + 批量同步）
"""

from .model_scanner import ModelInfo, ModelScanner, MODEL_DIR_LABELS
from .model_downloader import ModelDownloader, DownloadTask
from .model_linker import ModelLinker, ModelLinkStore

__all__ = [
    "ModelInfo",
    "ModelScanner",
    "MODEL_DIR_LABELS",
    "ModelDownloader",
    "DownloadTask",
    "ModelLinker",
    "ModelLinkStore",
]
