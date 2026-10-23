"""
模型管理配置管理器

用于管理「模型管理」页面的：
- 本地模型文件夹扫描路径（scan_paths）：默认添加「当前环境 models 根 + 共享模型目录 +
  环境设置外置模型类型目录」；用户清空后不再自动添加（scanPathsInitialized 标记），
  完全按用户输入的文件夹显示。
- 网络链接默认源（default_source）：modelscope（魔搭，默认）/ huggingface / auto
  （先魔搭，没有再 HuggingFace）。
"""

import os
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from .config_migrator import ConfigMigrator
from backend.src.utils.logger import app_logger as logger


class ModelConfigManager(ConfigMigrator):
    """模型管理配置管理器"""

    CURRENT_VERSION = "1.3.0"
    CONFIG_FILENAME = "model_config.json"

    def __init__(self, config_dir: str = None):
        """
        初始化模型管理配置管理器

        Args:
            config_dir: 配置文件目录，如果为 None 则使用默认路径
        """
        if config_dir is None:
            from backend.src.utils.paths import get_config_dir
            config_dir = get_config_dir()

        super().__init__(Path(config_dir))

    def get_default_config(self) -> Dict:
        """
        获取默认配置

        - scan_paths 首次由 ensure_default_model_paths() 填充默认文件夹；
        - default_source 默认 modelscope（魔搭社区）。

        Returns:
            默认配置字典
        """
        return {
            "version": self.CURRENT_VERSION,
            "scan_paths": [],
            "default_source": "modelscope",
        }

    def get_config(self) -> Dict:
        """获取完整配置"""
        try:
            config = self.load_config()
            return {
                "success": True,
                "config": config,
            }
        except Exception as e:
            logger.error(f"[ModelConfigManager] 读取配置失败: {str(e)}")
            return {
                "success": False,
                "message": f"读取配置失败: {str(e)}",
                "config": {},
            }

    def update_config(self, updates: Dict) -> Dict:
        """
        更新配置

        - 字典类小节做深度合并；
        - 非字典值（如 scan_paths 列表）整体替换。

        Args:
            updates: 要更新的配置项

        Returns:
            dict: 操作结果
        """
        try:
            config = self.load_config()

            for section, values in updates.items():
                if section in config and isinstance(config[section], dict) and isinstance(values, dict):
                    config[section].update(values)
                else:
                    config[section] = values

            save_result = self.save_config(config)

            if not save_result:
                logger.error("[ModelConfigManager] 保存配置失败")
                return {
                    "success": False,
                    "message": "保存配置失败",
                }

            logger.debug("[ModelConfigManager] 配置已成功保存")
            return {
                "success": True,
                "message": "配置已保存",
                "config": config,
            }
        except Exception as e:
            logger.error(f"[ModelConfigManager] 更新配置失败: {str(e)}")
            return {
                "success": False,
                "message": f"更新配置失败: {str(e)}",
            }

    def get_scan_paths(self) -> Dict:
        """
        获取扫描路径列表（仅返回已配置的路径；不做自动添加）

        Returns:
            dict: {"success": bool, "paths": list}
        """
        try:
            config = self.load_config()
            scan_paths = config.get("scan_paths", [])
            return {
                "success": True,
                "paths": scan_paths,
            }
        except Exception as e:
            logger.error(f"[ModelConfigManager] 读取扫描路径失败: {str(e)}")
            return {
                "success": False,
                "message": f"读取扫描路径失败: {str(e)}",
                "paths": [],
            }

    # ---------- 默认路径填充（仅首次） ----------

    def ensure_default_model_paths(self, default_roots: List[str]) -> Dict:
        """
        首次使用时把默认模型文件夹加入 scan_paths（当前环境 models 根、共享模型目录、
        环境设置的外置模型类型目录）。

        - 仅首次执行（config 打 scanPathsInitialized 标记），之后完全尊重用户增删：
          用户清空后保存即不再扫描任何文件夹、列表为空，不会被自动恢复。
        - 目录即使暂不存在也加入（后续创建即可被扫描）。

        Args:
            default_roots: 默认根目录候选列表（绝对路径）

        Returns:
            dict: {"success": bool, "added": [path, ...], "skipped": bool}
        """
        try:
            config = self.load_config()

            if config.get("scanPathsInitialized"):
                return {"success": True, "added": [], "skipped": True}

            scan_paths = config.get("scan_paths", [])
            existing = {os.path.normcase(p.get("path", "")) for p in scan_paths if p.get("path")}
            added: List[str] = []

            for root in (default_roots or []):
                p = str(root or "").strip()
                if not p:
                    continue
                key = os.path.normcase(p)
                if key in existing:
                    continue
                scan_paths.append({
                    "id": str(uuid.uuid4()),
                    "path": p,
                    "name": os.path.basename(p.rstrip("\\/")) or p,
                    "category": "uncategorized",
                    "enabled": True,
                })
                existing.add(key)
                added.append(p)

            config["scan_paths"] = scan_paths
            config["scanPathsInitialized"] = True
            self.save_config(config)
            if added:
                logger.info(f"[ModelConfigManager] 已默认添加模型扫描路径: {added}")
            return {"success": True, "added": added, "skipped": False}
        except Exception as e:
            logger.error(f"[ModelConfigManager] 确保默认模型路径失败: {str(e)}")
            return {"success": False, "added": [], "skipped": False}

    # ---------- 网络链接默认源 ----------

    def get_default_source(self) -> Dict:
        """
        获取网络链接默认源

        Returns:
            dict: {"success": bool, "source": "modelscope" | "huggingface" | "auto"}
        """
        try:
            config = self.load_config()
            source = config.get("default_source", "modelscope")
            if source not in ("modelscope", "huggingface", "auto"):
                source = "modelscope"
            return {"success": True, "source": source}
        except Exception as e:
            logger.error(f"[ModelConfigManager] 读取默认源失败: {str(e)}")
            return {"success": False, "source": "modelscope"}

    def set_default_source(self, source: str) -> Dict:
        """
        设置网络链接默认源

        Args:
            source: "modelscope" | "huggingface" | "auto"

        Returns:
            dict: {"success": bool, "message": str}
        """
        if source not in ("modelscope", "huggingface", "auto"):
            return {"success": False, "message": f"无效的默认源: {source}"}
        try:
            config = self.load_config()
            config["default_source"] = source
            save_result = self.save_config(config)
            if not save_result:
                return {"success": False, "message": "保存配置失败"}
            logger.debug(f"[ModelConfigManager] 网络链接默认源已设置为: {source}")
            return {"success": True, "message": "默认源已保存"}
        except Exception as e:
            logger.error(f"[ModelConfigManager] 设置默认源失败: {str(e)}")
            return {"success": False, "message": f"设置默认源失败: {str(e)}"}
