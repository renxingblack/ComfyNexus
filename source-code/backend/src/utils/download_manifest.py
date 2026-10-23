"""
0基础安装下载管理：下载记录 + 完整性校验 + 断点续传

- 下载记录持久化到 <install_dir>/_download_manifest.json：
  {url: {"dest": 路径, "size": 字节数, "mtime": 时间戳, "done": bool}}
- 完整性判定：目标文件存在 且 （期望大小匹配 或 manifest 记录大小匹配）
- 断点续传：requests 单线程走 .part 文件 + Range 请求；aria2 自带 --continue
- 取消/中断不删除任何已下载内容，下次安装自动跳过已完成的文件
"""

import json
import time
from pathlib import Path
from typing import Dict, Optional

from backend.src.utils.logger import app_logger as logger

MANIFEST_NAME = "_download_manifest.json"


def _manifest_path(install_dir: str) -> Path:
    return Path(install_dir) / MANIFEST_NAME


def load_manifest(install_dir: str) -> Dict:
    try:
        p = _manifest_path(install_dir)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.debug(f"[DownloadManifest] 读取失败: {e}")
    return {}


def save_manifest(install_dir: str, manifest: Dict):
    try:
        p = _manifest_path(install_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        logger.debug(f"[DownloadManifest] 写入失败: {e}")


def record_download(install_dir: str, url: str, dest: Path, done: bool = True):
    """记录一次下载（成功或中断），供下次安装判断跳过/续传"""
    manifest = load_manifest(install_dir)
    entry = manifest.get(url, {})
    try:
        size = dest.stat().st_size if dest.is_file() else entry.get("size", 0)
    except OSError:
        size = entry.get("size", 0)
    manifest[url] = {
        "dest": str(dest),
        "size": size,
        "mtime": time.time(),
        "done": bool(done),
    }
    save_manifest(install_dir, manifest)


def is_download_complete(install_dir: str, url: str, dest: Path,
                         expected_size: int = 0) -> bool:
    """
    判断文件是否已完整下载（可直接跳过）：
    - 目标文件存在 且 期望大小已知且匹配 → 完整
    - 期望大小未知 → manifest 记录的 size 匹配 且 done=True → 完整
    - 任何 .part / .aria2 残留 → 视为未完成（需续传）
    """
    try:
        if not dest.is_file():
            return False
        actual = dest.stat().st_size
        # 有未完成标记文件 → 未完成
        for suffix in (".part", ".aria2"):
            if dest.with_suffix(dest.suffix + suffix).exists():
                return False
        if expected_size > 0:
            return actual == expected_size
        manifest = load_manifest(install_dir)
        entry = manifest.get(url) or {}
        recorded = entry.get("size", 0)
        return bool(entry.get("done")) and recorded > 0 and actual == recorded
    except OSError:
        return False
