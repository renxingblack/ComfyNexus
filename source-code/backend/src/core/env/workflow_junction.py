"""
工作流目录 NTFS 联接映射

ComfyUI 不支持 --workflow-directory 启动参数，通过目录联接（junction）
把 <comfyui>/user/default/workflows 无损映射到用户指定目录。

行为：
- 目标目录不存在时自动创建
- 联接已指向目标 → 不做任何事
- 已有联接指向别处 → 删除重建
- 已有真实目录 → 内容先迁移到目标目录（robocopy /E），再替换为联接
"""

import subprocess
from pathlib import Path

from backend.src.utils.logger import app_logger as logger


def ensure_workflow_junction(comfyui_path: str, workflow_dir: str) -> bool:
    """返回是否成功（失败不阻塞启动流程）"""
    try:
        if not comfyui_path or not workflow_dir:
            return False
        target = Path(workflow_dir)
        target.mkdir(parents=True, exist_ok=True)

        link = Path(comfyui_path) / "user" / "default" / "workflows"
        link.parent.mkdir(parents=True, exist_ok=True)

        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        # 已存在且已是联接
        if link.exists():
            try:
                resolved = Path(str(link.resolve()))
                if resolved == target.resolve():
                    return True  # 已指向目标
            except OSError:
                pass
            if link.is_symlink():
                link.unlink()

        # 已有真实目录：迁移内容到目标后替换
        if link.exists() and not link.is_symlink():
            if any(link.iterdir()):
                logger.info(f"[workflow-junction] 迁移现有工作流到 {target}")
                subprocess.run(
                    ["robocopy", str(link), str(target), "/E", "/NFL", "/NDL", "/NJH", "/NJS"],
                    capture_output=True, creationflags=creation,
                )
            subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True, creationflags=creation)

        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, creationflags=creation,
        )
        if link.exists():
            logger.info(f"[workflow-junction] 工作流目录已映射: {link} -> {target}")
            return True
        logger.warning(f"[workflow-junction] mklink 失败: {result.stderr.decode('gbk', 'replace')[:150]}")
        return False
    except Exception as e:
        logger.warning(f"[workflow-junction] 工作流目录映射失败: {e}")
        return False
