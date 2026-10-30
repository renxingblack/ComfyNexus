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


def ensure_workflow_junction(comfyui_path: str, workflow_dir: str, user_directory: str = "") -> bool:
    """返回是否成功（失败不阻塞启动流程）

    user_directory: 若设置了 --user-directory，ComfyUI 实际读取的工作流目录是
    <user_directory>/user/default/workflows，而不是 <comfyui_path>/user/default/workflows。
    junction 必须建在前者，否则会因路径错位而失效（v1.3.5 之前的 bug：
    user_directory 与 workflow_directory 同时设置时看不到任何工作流）。
    """
    try:
        if not comfyui_path or not workflow_dir:
            return False
        target = Path(workflow_dir)
        target.mkdir(parents=True, exist_ok=True)

        # 基准目录：设置了 user_directory（--user-directory 生效）时，ComfyUI
        # 真实读取位置在 <user_directory>/user/default/workflows，而非 comfyui_path 下。
        base = Path(user_directory) if user_directory else Path(comfyui_path)

        # 防护：workflow_dir 恰好等于 user 默认工作流目录时，再建 junction 会自指向，
        # 此时 workflows 已随 user_directory 原生生效，直接跳过。
        if user_directory:
            try:
                if Path(workflow_dir).resolve() == (base / "user" / "default" / "workflows").resolve():
                    logger.info("[workflow-junction] workflow_dir 已等于 user 默认工作流目录，无需 junction")
                    return True
            except OSError:
                pass

        link = base / "user" / "default" / "workflows"
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
