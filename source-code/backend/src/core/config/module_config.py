"""
模块配置管理器
负责读取、写入和验证模块配置文件
"""

import json
from pathlib import Path
from typing import Dict, Optional

from ..config.config_migrator import ConfigMigrator
from backend.src.utils.logger import app_logger as logger


class ModuleConfigManager(ConfigMigrator):
    """模块配置管理器"""

    # 1.1.0：侧边栏顺序重排（依赖管理移到 AI 助手之前等），见 _apply_version_migrations
    CURRENT_VERSION = "1.3.0"
    CONFIG_FILENAME = "modules.json"
    
    def __init__(self):
        from backend.src.utils.paths import get_config_dir
        config_dir = get_config_dir()
        super().__init__(config_dir)
    
    def get_default_config(self) -> Dict:
        """
        获取默认配置（基础模式，只启用已开发的模块）

        侧边栏顺序（用户指定）：
        首页、工作台、终端、核心管理、插件管理、插件市场、LoRA管理、模型管理、
        依赖管理、AI助手、工作流库、提示词库、资产库、监控中心、环境设置、
        系统设置、关于、问题反馈

        Returns:
            Dict: 默认配置对象
        """
        return {
            "version": self.CURRENT_VERSION,
            "preset": "basic",
            "modules": {
                "home": {"enabled": True, "order": 1},           # 首页
                "workspace": {"enabled": True, "order": 2},       # 工作台
                "terminal": {"enabled": True, "order": 3},        # 终端
                "version-manage": {"enabled": True, "order": 4},  # 核心管理
                "plugin-manage": {"enabled": True, "order": 5},   # 插件管理
                "plugin-market": {"enabled": True, "order": 6},   # 插件市场
                "model-manage": {"enabled": True, "order": 7},    # LoRA管理
                "model-library": {"enabled": True, "order": 8},   # 模型管理（本地+多源下载）
                "dependency-manage": {"enabled": True, "order": 9},   # 依赖管理
                "ai-assistant": {"enabled": True, "order": 10},   # AI助手
                "workflow-manage": {"enabled": True, "order": 11},    # 工作流库
                "prompt-manage": {"enabled": True, "order": 12},  # 提示词库
                "output-gallery": {"enabled": True, "order": 13}, # 资产库
                "monitor-center": {"enabled": True, "order": 14}, # 监控中心
                "env-manage": {"enabled": True, "order": 15},     # 环境设置
                "system-settings": {"enabled": True, "order": 16},# 系统设置
                "about": {"enabled": True, "order": 17},          # 关于
                "feedback": {"enabled": True, "order": 18}        # 问题反馈
            },
            "ui": {
                "theme": "dark",
                "language": "zh-CN"
            }
        }

    def _apply_version_migrations(self, config: Dict, old_version: str, new_version: str) -> Dict:
        """
        版本特定迁移

        1.0.0 -> 1.1.0：按新默认顺序重排模块（保留用户对每个模块的启用/禁用状态）
        """
        if old_version < new_version:
            default_config = self.get_default_config()
            default_modules = default_config.get("modules", {})
            user_modules = config.get("modules", {})

            reordered = {}
            for module_id, meta in default_modules.items():
                user_meta = user_modules.get(module_id, {})
                reordered[module_id] = {
                    "enabled": user_meta.get("enabled", meta["enabled"]),
                    "order": meta["order"],
                }
            # 用户配置里多出来的模块（未来版本）追加保留
            for module_id, meta in user_modules.items():
                if module_id not in reordered:
                    reordered[module_id] = meta
            config["modules"] = reordered
            config["preset"] = default_config.get("preset", config.get("preset", "basic"))
        return config
    
    @property
    def config_dir_str(self) -> str:
        """
        配置目录路径（字符串格式）
        
        Returns:
            str: 配置目录的字符串路径
        """
        return str(self.config_dir)
    
    @property
    def config_file_str(self) -> str:
        """
        配置文件路径（字符串格式）
        
        Returns:
            str: 配置文件的字符串路径
        """
        return str(self.config_file)
    
    def reset_config(self) -> bool:
        """
        重置模块配置为默认值（保留其他设置如主题、语言等）
        
        Returns:
            bool: 重置是否成功
        """
        try:
            # 加载当前配置
            current_config = self.load_config()
            
            # 获取默认的模块配置
            default_config = self.get_default_config()
            
            # 只重置模块部分，保留 UI 设置
            current_config['modules'] = default_config['modules']
            current_config['preset'] = default_config['preset']
            
            # 保存修改后的配置
            return self.save_config(current_config)
        except Exception as e:
            logger.error(f"重置模块配置失败: {e}")
            return False
