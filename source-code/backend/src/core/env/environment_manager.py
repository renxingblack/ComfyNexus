"""
Environment manager for ComfyNexus.

This module provides core functionality for managing ComfyUI environments,
including adding, deleting, updating, and switching environments.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .dependency_detector import DependencyDetector
from .environment_config_manager import EnvironmentConfigManager
from .environment_scanner import EnvironmentScanner
from .error_codes import ErrorCode, get_error_message
from .types import DependencyInfo, Environment, EnvironmentConfig, EnvironmentInfo
from ...utils.logger import app_logger as logger


_GENERAL_FIELD_MAPPING = {
    "comfyui_path": "comfyuiPath",
    "python_path": "pythonPath",
    "pip_path": "pipPath",
    # git_path 一直被 config_validator 当作路径字段校验、被 zero_install 使用，
    # 但之前漏在这张表里 —— 与 workflow_directory 完全同一个 bug：
    # 保存时丢弃、读取时也丢弃，前端永远看不到自己填的 Git 路径。
    "git_path": "gitPath",
}

_ACCELERATION_FIELD_MAPPING = {
    "compute_device": "computeDevice",
    "vram_mode": "vramStrategy",
    "use_cpu": "cpuOnly",
    "use_gpu_only": "gpuOnly",
    "reserve_vram": "reserveVram",
    "unet_precision": "unetPrecision",
    "vae_precision": "vaePrecision",
    "text_enc_precision": "textEncPrecision",
    "attention_type": "attentionMode",
    "disable_xformers": "disableXformers",
    "disable_smart_memory": "disableSmartMemory",
    "force_channels_last": "forceChannelsLast",
    "cache_lru": "cacheLru",
    "deterministic": "deterministic",
    "fast_mode": "fastMode",
    "cuda_malloc": "cudaMalloc",
    "listen": "listenNetwork",
    "listen_address": "listenAddress",
    "port": "port",
    "enable_cors": "enableCors",
    "tls_keyfile": "tlsKeyfile",
    "tls_certfile": "tlsCertfile",
    "base_directory": "baseDirectory",
    "input_directory": "inputDirectory",
    "output_directory": "outputDirectory",
    "temp_directory": "tempDirectory",
    "user_directory": "userDirectory",
    # 工作流目录：启动前以 NTFS 目录联接映射到 ComfyUI 的 user/default/workflows。
    # 漏了这一行会导致「保存成功但界面空着」——写盘能进去，读回来时被
    # _map_fields_with_defaults 的白名单过滤掉（它只遍历映射表的 key）。
    "workflow_directory": "workflowDirectory",
    "extra_model_paths_config": "extraModelPathsConfig",
    "preview_method": "previewMethod",
    "preview_size": "previewSize",
    "disable_all_custom_nodes": "safeMode",
    "enable_manager": "enableManager",
    "verbose": "logLevel",
    "disable_metadata": "disableMetadata",
    "auto_download_missing_nodes": "autoDownloadMissingNodes",
}

_GEEK_MODE_FIELD_MAPPING = {
    "enabled": "enabled",
    "custom_args": "customArgs",
    "current_preset_id": "currentPresetId",
}

_ACCELERATION_DEFAULTS = {
    "compute_device": "",
    "vram_mode": "auto",
    "use_cpu": False,
    "use_gpu_only": False,
    "reserve_vram": 0,
    "unet_precision": "auto",
    "vae_precision": "auto",
    "text_enc_precision": "auto",
    "attention_type": "auto",
    "disable_xformers": False,
    "disable_smart_memory": False,
    "force_channels_last": False,
    "cache_lru": 0,
    "deterministic": False,
    "fast_mode": False,
    "cuda_malloc": "auto",
    "listen": False,
    # 映射表引用了 listen_address，默认值表却漏了 —— 未配置时前端会收到 None
    # 而不是空串（Input 能显示，但类型不对，且会和「未设置」混淆）。
    "listen_address": "",
    "port": 8188,
    "enable_cors": False,
    "tls_keyfile": "",
    "tls_certfile": "",
    "base_directory": "",
    "input_directory": "",
    "output_directory": "",
    "temp_directory": "",
    "user_directory": "",
    # 默认必须给空串：_map_fields_with_defaults 用 defaults.get(key) 兜底，
    # 缺省会得到 None，前端 Input 的 value={... || ''} 虽然能兜住显示，
    # 但类型上不再是 string，容易在后续逻辑里踩到。
    "workflow_directory": "",
    "extra_model_paths_config": "",
    "preview_method": "auto",
    "preview_size": 512,
    "disable_all_custom_nodes": False,
    "enable_manager": False,
    "verbose": "INFO",
    "disable_metadata": False,
    "auto_download_missing_nodes": False,
}

_GENERAL_DEFAULTS = {
    "comfyui_path": "",
    "python_path": "",
    "pip_path": "",
    "git_path": "",
}

_GEEK_MODE_DEFAULTS = {
    "enabled": False,
    "custom_args": "",
    "current_preset_id": "custom",
}


class EnvironmentManager:
    """Manager for ComfyUI environments."""
    
    def __init__(self):
        """Initialize the environment manager."""
        self.config_manager = EnvironmentConfigManager()
        self.scanner = EnvironmentScanner()
        self.dependency_detector = DependencyDetector()
    
    def _migrate_config(self, config: dict) -> dict:
        """
        迁移旧配置到新格式
        
        此方法负责将旧版本的配置文件迁移到新格式：
        1. 删除 general.gpuSelection 字段
        2. 迁移 acceleration.cudaDevice → acceleration.computeDevice
        3. 删除 acceleration.directML 字段
        4. 设置默认值
        
        Args:
            config: 旧配置字典
            
        Returns:
            迁移后的新配置字典
        """
        try:
            # 1. 删除 general.gpuSelection
            if "general" in config and "gpuSelection" in config["general"]:
                del config["general"]["gpuSelection"]
                logger.info("[EnvironmentManager] 已删除 general.gpuSelection 字段")
            
            # 2. 迁移 acceleration 配置
            if "acceleration" in config:
                acc = config["acceleration"]
                
                # 迁移 cudaDevice → computeDevice
                if "cudaDevice" in acc and "computeDevice" not in acc:
                    cuda_device = acc["cudaDevice"]
                    acc["computeDevice"] = f"nvidia:{cuda_device}"
                    del acc["cudaDevice"]
                    logger.info(f"[EnvironmentManager] 已迁移 cudaDevice: {cuda_device} → computeDevice: nvidia:{cuda_device}")
                
                # 迁移旧格式 gpu:X → nvidia:X
                if "computeDevice" in acc and acc["computeDevice"].startswith("gpu:"):
                    old_value = acc["computeDevice"]
                    acc["computeDevice"] = old_value.replace("gpu:", "nvidia:", 1)
                    logger.info(f"[EnvironmentManager] 已迁移 computeDevice: {old_value} → {acc['computeDevice']}")
                
                # 删除 directML
                if "directML" in acc:
                    del acc["directML"]
                    logger.info("[EnvironmentManager] 已删除 acceleration.directML 字段")
                
                # 设置默认值
                if "computeDevice" not in acc:
                    acc["computeDevice"] = "auto"
                    logger.info("[EnvironmentManager] 已设置默认 computeDevice: auto")
                elif acc["computeDevice"] == "":
                    acc["computeDevice"] = "auto"
                    logger.info("[EnvironmentManager] 已迁移空值 computeDevice → auto")
            
            return config
            
        except Exception as e:
            logger.error(f"[EnvironmentManager] 配置迁移失败: {e}")
            # 迁移失败不影响加载，返回原配置
            return config
    
    def _generate_unique_alias(self, base_name: str) -> str:
        """
        Generate alias for the environment.

        不再自动追加序号，直接返回原始名称。
        如果别名重复，由用户自行修改。

        Args:
            base_name: Base name for the alias

        Returns:
            Alias string (same as base_name)
        """
        return base_name

    def _sync_manager_missing_nodes_config(self, comfyui_path: str, enabled: bool) -> None:
        """
        把「自动下载缺失节点」开关同步到 ComfyUI-Manager 插件的 config.ini。

        ComfyUI-Manager 的一键安装缺失节点（Install Missing Custom Nodes）能力由
        security_level 门控：normal 及以下允许安装注册节点包；strong 全部禁止。
        因此开关映射为：开=normal（功能可用），关=strong（功能关闭）。

        配置路径兼容：
        - ComfyUI v0.3.76+ / Manager V3.38+：<comfyui>/user/__manager/config.ini
        - 旧版：<comfyui>/user/default/ComfyUI-Manager/config.ini

        任何异常仅记录日志，不影响环境配置保存。
        """
        import configparser
        from pathlib import Path

        if not comfyui_path:
            logger.warning("[ManagerSync] 未配置 ComfyUI 路径，跳过同步 ComfyUI-Manager 配置")
            return

        user_dir = Path(comfyui_path) / "user"
        candidates = [
            user_dir / "__manager" / "config.ini",                # Manager V3.38+
            user_dir / "default" / "ComfyUI-Manager" / "config.ini",  # 旧版
        ]

        target = None
        for c in candidates:
            if c.exists():
                target = c
                break
        if target is None:
            # 都不存在：按新版路径创建（Manager 首次运行会读取该目录）
            target = candidates[0]

        parser = configparser.ConfigParser()
        try:
            if target.exists():
                parser.read(target, encoding="utf-8")
        except Exception as e:
            logger.warning(f"[ManagerSync] 读取 {target} 失败: {e}")

        if not parser.has_section("default"):
            parser.add_section("default")

        parser.set("default", "security_level", "normal" if enabled else "strong")

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                parser.write(f)
            logger.info(f"[ManagerSync] 已同步 ComfyUI-Manager 缺失节点安装功能: security_level={'normal' if enabled else 'strong'} -> {target}")
        except Exception as e:
            logger.warning(f"[ManagerSync] 写入 {target} 失败: {e}")

    def _map_fields_with_defaults(self, source_dict: dict, field_mapping: dict, defaults: dict = None) -> dict:
        """
        使用映射配置将源字典的字段映射到目标字典，并设置默认值
        
        Args:
            source_dict: 源字典（后端格式，蛇形命名）
            field_mapping: 字段映射表 {后端字段: 前端字段}
            defaults: 默认值表 {后端字段: 默认值}
            
        Returns:
            映射后的字典（前端格式，驼峰命名）
        """
        if defaults is None:
            defaults = {}
        
        result = {}
        for backend_key, frontend_key in field_mapping.items():
            value = source_dict.get(backend_key, defaults.get(backend_key))
            result[frontend_key] = value
        
        return result
    
    def _format_general_config(self, general_config: dict) -> dict:
        """
        格式化 general 配置块为前端格式
        
        Args:
            general_config: general 配置字典（后端格式）
            
        Returns:
            格式化后的 general 配置字典（前端格式）
        """
        return self._map_fields_with_defaults(general_config, _GENERAL_FIELD_MAPPING, _GENERAL_DEFAULTS)
    
    def _format_geek_mode_config(self, geek_mode_dict: dict) -> dict:
        """
        格式化 geek_mode 配置块为前端格式
        
        Args:
            geek_mode_dict: geek_mode 配置字典（后端格式）
            
        Returns:
            格式化后的 geek_mode 配置字典（前端格式）
        """
        if not isinstance(geek_mode_dict, dict):
            return _GEEK_MODE_DEFAULTS.copy()
        
        return self._map_fields_with_defaults(geek_mode_dict, _GEEK_MODE_FIELD_MAPPING, _GEEK_MODE_DEFAULTS)
    
    def _format_acceleration_config(self, accel_config: dict) -> dict:
        """
        格式化 acceleration 配置块为前端格式
        
        Args:
            accel_config: acceleration 配置字典（后端格式）
            
        Returns:
            格式化后的 acceleration 配置字典（前端格式）
        """
        result = self._map_fields_with_defaults(accel_config, _ACCELERATION_FIELD_MAPPING, _ACCELERATION_DEFAULTS)
        
        geek_mode_dict = accel_config.get("geek_mode", {})
        result["geekMode"] = self._format_geek_mode_config(geek_mode_dict)
        
        return result
    
    def _format_environment_for_frontend(self, env: Environment, current_env_id: Optional[str] = None) -> dict:
        """
        将环境对象格式化为前端所需的格式
        
        此方法负责协调各个配置块的格式化，并组装最终结果
        
        Args:
            env: 环境对象
            current_env_id: 当前激活的环境 ID（可选）
            
        Returns:
            格式化后的环境字典（前端格式）
        """
        env_dict = env.to_dict()
        env_dict = self._migrate_config(env_dict)
        
        general_config = env.config.general.to_dict()
        general_frontend = self._format_general_config(general_config)
        
        dependencies_frontend = self._map_dependency_fields(env.dependencies)
        
        accel_config = env.config.acceleration.to_dict()
        accel_frontend = self._format_acceleration_config(accel_config)
        
        result_dict = {
            "id": env.id,
            "name": env.name,
            "alias": env.alias,
            "path": env.path,  # 添加路径字段
            "version": env.version,
            "versionInfo": env.version_info.to_dict() if env.version_info else {},
            "isActive": (env.id == current_env_id) if current_env_id else False,
            "envType": env.env_type,  # 添加环境类型字段
            "desktopDataPath": env.desktop_data_path,  # 添加桌面版数据目录字段
            "general": general_frontend,
            "dependencies": dependencies_frontend,
            "acceleration": accel_frontend,
            "advancedEnvVars": env.config.advanced_env_vars or "",
            "modelPathConfigs": [cfg.to_dict() for cfg in env.model_path_configs],
            "createdAt": env.created_at,
            "updatedAt": env.updated_at
        }
        
        return result_dict
    
    def _map_dependency_fields(self, dep_info: Optional[DependencyInfo]) -> dict:
        """
        将 DependencyInfo 的字段映射为前端期望的驼峰命名格式。
        
        此方法负责将后端的蛇形命名字段转换为前端期望的驼峰命名字段，
        确保前后端数据格式的一致性。
        
        字段映射关系：
        - python -> pythonVersion
        - pytorch -> pytorchVersion
        - cuda -> cudaVersion
        - sageattention -> sageAttentionVersion
        - flash_attention -> flashAttnVersion
        - triton -> tritonVersion
        - xformers -> xformersVersion
        
        Args:
            dep_info: DependencyInfo 对象，可以为 None
            
        Returns:
            包含驼峰命名字段的字典，空值显示为 "Unknown"
            
        Examples:
            >>> dep_info = DependencyInfo(python="3.11.0", pytorch="2.0.0")
            >>> result = self._map_dependency_fields(dep_info)
            >>> result["pythonVersion"]
            '3.11.0'
            >>> result["pytorchVersion"]
            '2.0.0'
            >>> result["cudaVersion"]
            'Unknown'
        """
        if dep_info is None:
            return {
                "pythonVersion": "Unknown",
                "pytorchVersion": "Unknown",
                "cudaVersion": "Unknown",
                "sageAttentionVersion": "Unknown",
                "flashAttnVersion": "Unknown",
                "tritonVersion": "Unknown",
                "xformersVersion": "Unknown",
                "ckAttentionVersion": "Unknown"
            }

        return {
            "pythonVersion": dep_info.python or "Unknown",
            "pytorchVersion": dep_info.pytorch or "Unknown",
            "cudaVersion": dep_info.cuda or "Unknown",
            "sageAttentionVersion": dep_info.sageattention or "Unknown",
            "flashAttnVersion": dep_info.flash_attention or "Unknown",
            "tritonVersion": dep_info.triton or "Unknown",
            "xformersVersion": dep_info.xformers or "Unknown",
            # Comfy Kitchen Attention 为 ComfyUI v0.32.0+ 内置后端，按版本判定
            "ckAttentionVersion": self._detect_ck_attention_version(),
        }

    def _detect_ck_attention_version(self) -> str:
        """检测当前环境的 Comfy Kitchen Attention 可用性（ComfyUI >= v0.32.0 内置）"""
        try:
            from backend.src.utils.paths import get_internal_dir
            # 环境的 ComfyUI 目录在环境配置里，这里从通用路径兜底检测
            import re
            from pathlib import Path as _Path
            comfyui_path = getattr(self, '_current_comfyui_path', '') or ''
            if not comfyui_path:
                return "Unknown"
            vf = _Path(comfyui_path) / "comfyui_version.py"
            if not vf.is_file():
                vf = _Path(comfyui_path) / "ComfyUI" / "comfyui_version.py"
            if not vf.is_file():
                return "Unknown"
            m = re.search(r'VERSION\s*=\s*["\']?v?([0-9]+)\.([0-9]+)',
                          vf.read_text(encoding="utf-8", errors="replace"))
            if not m:
                return "Unknown"
            major, minor = int(m.group(1)), int(m.group(2))
            if (major, minor) >= (0, 32):
                return f"内置可用 (v{major}.{minor}+)"
            return f"不支持 (需 v0.32+)"
        except Exception:
            return "Unknown"
    
    def _get_comfyui_version(self, comfyui_path: str) -> str:
        """
        获取 ComfyUI 版本号
        
        从 comfyui_version.py 文件读取版本信息
        
        Args:
            comfyui_path: ComfyUI 安装路径
            
        Returns:
            版本号字符串，如 "0.3.27"，失败返回 "Unknown"
        """
        try:
            version_file = Path(comfyui_path) / "comfyui_version.py"
            
            if version_file.exists():
                with open(version_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip().startswith('__version__'):
                            # 提取版本号: __version__ = "0.3.27"
                            version = line.split('=')[1].strip().strip('"').strip("'")
                            return version
            
            return "Unknown"
        except Exception as e:
            logger.warning(f"[_get_comfyui_version] 获取版本失败: {e}")
            return "Unknown"
    
    def _get_version_info(self, comfyui_path: str) -> "VersionInfo":
        """
        获取 ComfyUI 版本详细信息
        
        包括 commit hash/tag、是否为 dev 标签、最后更新时间
        
        Args:
            comfyui_path: ComfyUI 安装路径
            
        Returns:
            VersionInfo 对象
        """
        from .types import VersionInfo
        
        try:
            logger.debug(f"[_get_version_info] 开始获取版本信息: {comfyui_path}")
            
            # 导入 GitManager
            from ..git_manager import GitManager
            
            # 创建 GitManager 实例
            git_manager = GitManager(repo_path=comfyui_path)
            
            # 获取当前版本信息
            version_info = git_manager.get_current_version()
            
            logger.debug(f"[_get_version_info] Git版本信息: {version_info}")
            
            if version_info and version_info.get("id"):
                # 提取信息
                is_dev = version_info.get("type", "dev") == "dev"
                timestamp = version_info.get("timestamp", "")
                
                # 根据是否为dev版本决定显示tag还是短hash
                if is_dev:
                    # 开发版本:显示短hash
                    commit_hash = version_info.get("id", "")[:7]  # 前7位
                    logger.debug(f"[_get_version_info] 开发版本,使用短hash: {commit_hash}")
                else:
                    # 稳定版本:显示tag
                    tag = version_info.get("tag", "")
                    if tag:
                        commit_hash = tag
                        logger.debug(f"[_get_version_info] 稳定版本,使用tag: {commit_hash}")
                    else:
                        # 如果没有tag,使用短hash
                        commit_hash = version_info.get("id", "")[:7]
                        logger.debug(f"[_get_version_info] 稳定版本但无tag,使用短hash: {commit_hash}")
                
                # 转换时间戳格式为 ISO 格式
                if timestamp:
                    try:
                        from datetime import datetime
                        import re
                        timestamp_clean = re.sub(r'\s[+-]\d{4}$', '', timestamp)
                        dt = datetime.strptime(timestamp_clean, "%Y-%m-%d %H:%M:%S")
                        last_updated = dt.isoformat()
                    except Exception as e:
                        logger.warning(f"[_get_version_info] 时间戳转换失败: {e}")
                        last_updated = timestamp
                else:
                    last_updated = ""
                
                result = VersionInfo(
                    commit_hash=commit_hash,
                    is_dev=is_dev,
                    last_updated=last_updated
                )
                logger.debug(f"[_get_version_info] 版本信息获取成功: hash={commit_hash}, is_dev={is_dev}")
                return result
            else:
                logger.warning("[_get_version_info] Git版本信息为空或无效")
                return VersionInfo()
                
        except Exception as e:
            logger.error(f"[_get_version_info] 获取版本详细信息失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return VersionInfo()
    
    def _update_version_info(self, env_id: str, comfyui_path: str) -> bool:
        """
        更新环境的版本信息
        
        在版本切换后调用,更新版本号和版本详细信息
        
        Args:
            env_id: 环境 ID
            comfyui_path: ComfyUI 安装路径
            
        Returns:
            bool: 是否更新成功
        """
        try:
            # 加载当前配置
            config_data = self.config_manager.load_config()
            
            # 查找环境
            environment = None
            env_index = -1
            for i, env_dict in enumerate(config_data.get("environments", [])):
                if env_dict["id"] == env_id:
                    environment = Environment.from_dict(env_dict)
                    env_index = i
                    break
            
            if not environment:
                logger.warning(f"[_update_version_info] 环境未找到: {env_id}")
                return False
            
            # 获取新的版本号
            new_version = self._get_comfyui_version(comfyui_path)
            
            # 获取新的版本详细信息
            new_version_info = self._get_version_info(comfyui_path)
            
            # 更新环境
            environment.version = new_version
            environment.version_info = new_version_info
            environment.updated_at = datetime.now().isoformat()
            
            # 保存到配置文件
            config_data["environments"][env_index] = environment.to_dict()
            self.config_manager.save_config(config_data)
            
            logger.info(f"[_update_version_info] 版本信息已更新: {new_version}, commit: {new_version_info.commit_hash}")
            return True
            
        except Exception as e:
            logger.error(f"[_update_version_info] 更新版本信息失败: {e}")
            return False
    
    def add_environment(self, path: str, name: Optional[str] = None, lang: str = "en") -> dict:
        """
        Add a new ComfyUI environment.
        
        Args:
            path: Path to the ComfyUI installation
            name: Optional name for the environment. If not provided, auto-generated.
            lang: Language code ("en" or "zh")
            
        Returns:
            Dictionary with success status and environment data or error message
        """
        try:
            # 检测环境类型
            from .environment_type_detector import EnvironmentTypeDetector
            comfyui_path, env_type, desktop_data_path, error_message = EnvironmentTypeDetector.detect(path)
            
            # 桌面版检测失败（config.json 不存在）
            if error_message and env_type == "unknown" and (Path(path) / "ComfyUI.exe").exists():
                return {
                    "success": False,
                    "error_code": ErrorCode.VALIDATION_FAILED,
                    "error_message": error_message,
                    "env_type": "desktop"
                }
            
            # 记录检测到的环境类型
            logger.info(f"[add_environment] 检测到环境类型: {env_type}, 路径: {comfyui_path}, 数据目录: {desktop_data_path}")
            
            # 使用检测到的路径
            path = comfyui_path
            path_obj = Path(path)
            
            # 创建带语言参数的扫描器
            scanner = EnvironmentScanner(lang=lang)
            
            # Scan the environment (传递 env_type 和 desktop_data_path)
            scan_result = scanner.scan_environment(path, env_type, desktop_data_path)
            
            if not scan_result["is_valid"]:
                return {
                    "success": False,
                    "error_code": ErrorCode.INVALID_COMFYUI_INSTALLATION,
                    "error_message": scan_result.get("error_message", "Invalid ComfyUI installation")
                }
            
            # ---- 路径去重：同路径已存在则复用，避免重复添加（0 基础安装自动加入环境时防重复）----
            try:
                for existing in self.config_manager.get_environments():
                    existing_path = getattr(existing, "path", "") or ""
                    if existing_path and str(Path(existing_path).resolve()) == str(Path(path).resolve()):
                        logger.info(f"[add_environment] 路径已存在，复用现有环境 {existing.id}: {path}")
                        # 关键：把已有环境设为当前环境（否则前端仍显示欢迎页）
                        try:
                            self.config_manager.set_current_environment_id(existing.id)
                        except Exception as _se:
                            logger.debug(f"[add_environment] 设为当前环境失败: {_se}")
                        return {
                            "success": True,
                            "environment": self._format_environment_for_frontend(existing, existing.id),
                            "reused": True,
                        }
            except Exception as _e:
                logger.debug(f"[add_environment] 路径去重检查失败: {_e}")
            
            # Generate environment ID
            env_id = str(uuid.uuid4())
            
            # 获取 ComfyUI 版本
            comfyui_version = self._get_comfyui_version(path)
            
            # Generate environment name if not provided
            if not name:
                path_obj = Path(path)
                # 使用父级目录名作为环境名
                # 例如：D:\Projects\ComfyUI-Main\ComfyUI -> 环境名为 "ComfyUI-Main"
                parent_name = path_obj.parent.name
                # 如果父目录名为空或为根目录，则使用当前目录名
                if not parent_name or parent_name == path_obj.anchor:
                    base_name = path_obj.name
                else:
                    base_name = parent_name
            else:
                base_name = name
            
            # Generate unique alias (不包含版本号)
            alias = self._generate_unique_alias(base_name)
            
            # name 字段使用别名
            name = alias
            
            # Create environment configuration
            config = EnvironmentConfig()
            config.general.comfyui_path = path
            config.general.python_path = scan_result.get("python_directory", "")
            config.general.pip_path = scan_result.get("pip_directory", "")
            
            path_obj = Path(path)
            
            # 不设置默认目录路径，让 ComfyUI 使用自己的默认路径
            # 用户可以在需要时手动配置
            config.acceleration.input_directory = ""
            config.acceleration.output_directory = ""
            config.acceleration.temp_directory = ""
            config.acceleration.user_directory = ""
            
            config.acceleration.compute_device = "auto"
            
            # 设置默认端口（避免冲突）
            config.acceleration.port = 8188
            
            config.acceleration.enable_cors = False
            
            from .types import GeekMode
            config.acceleration.geek_mode = GeekMode(
                enabled=False,
                custom_args="",
                current_preset_id="custom"
            )
            
            # 初始化依赖信息
            # 尝试检测依赖信息,如果失败则使用空值
            dependencies = DependencyInfo()
            python_path = scan_result.get("python_directory", "")
            if python_path:
                try:
                    logger.debug(f"[add_environment] 开始检测依赖信息: {python_path}")
                    dependencies = self.dependency_detector.get_dependencies(python_path)
                    logger.info(f"[add_environment] 依赖信息检测完成: Python {dependencies.python}, PyTorch {dependencies.pytorch}")
                except Exception as e:
                    logger.warning(f"[add_environment] 依赖信息检测失败: {e}")
                    # 失败时使用空的依赖信息
                    dependencies = DependencyInfo()
            
            # 获取版本详细信息
            version_info = self._get_version_info(path)
            
            # Create environment (版本号作为独立字段)
            environment = Environment(
                id=env_id,
                name=name,
                alias=alias,
                path=path,
                version=comfyui_version,  # 版本号独立保存
                version_info=version_info,  # 版本详细信息
                config=config,
                is_default=False,
                dependencies=dependencies,  # 初始为空，后续异步更新
                env_type=env_type,  # 环境类型
                desktop_data_path=desktop_data_path  # 桌面版数据目录
            )
            
            # Load current config
            config_data = self.config_manager.load_config()
            
            # Add environment to config
            config_data["environments"].append(environment.to_dict())
            
            # 将新添加的环境设置为当前环境
            config_data["current_environment_id"] = env_id
            
            # Save config
            self.config_manager.save_config(config_data)
            
            # 新增：触发插件后台初始化
            try:
                # 获取插件控制器实例
                plugin_controller = self._get_plugin_controller()
                
                # 收集所有 custom_nodes 路径（主路径 + 外置路径）
                custom_nodes_paths = [Path(path) / "custom_nodes"]
                
                # 从环境的 model_path_configs 中提取外置 custom_nodes 路径
                env_obj = self.config_manager.get_environment(env_id)
                if env_obj and hasattr(env_obj, 'model_path_configs'):
                    for config in env_obj.model_path_configs:
                        cn_rel = config.paths.get("custom_nodes") or config.paths.get("customNodes")
                        if cn_rel:
                            ext_path = Path(config.base_path) / cn_rel
                            if ext_path.exists() and ext_path not in custom_nodes_paths:
                                custom_nodes_paths.append(ext_path)
                
                # 检查主 custom_nodes 目录是否存在
                primary_path = custom_nodes_paths[0]
                if not primary_path.exists():
                    logger.info(f"[add_environment] custom_nodes 目录不存在，跳过插件初始化: {primary_path}")
                else:
                    # 设置环境并触发后台更新
                    plugin_controller.set_environment(env_id, custom_nodes_paths)
                    
                    # 触发后台更新任务（异步，不阻塞返回）
                    trigger_result = plugin_controller.trigger_background_update()
                    
                    if trigger_result.get("success"):
                        logger.info(f"[add_environment] 已触发插件后台初始化: env_id={env_id}, paths={custom_nodes_paths}")
                    else:
                        logger.warning(f"[add_environment] 插件后台初始化触发失败: {trigger_result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                # 插件初始化失败不影响环境添加的成功
                logger.error(f"[add_environment] 触发插件初始化时发生错误: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
            # 使用统一的格式化方法，确保返回的数据格式与 get_environments() 一致
            formatted_environment = self._format_environment_for_frontend(environment, env_id)
            
            return {
                "success": True,
                "environment": formatted_environment
            }
        except Exception as e:
            return {
                "success": False,
                "error_code": ErrorCode.UNKNOWN_ERROR,
                "error_message": str(e)
            }
    
    def delete_environment(self, env_id: str) -> dict:
        """
        Delete a ComfyUI environment.
        
        Args:
            env_id: ID of the environment to delete
            
        Returns:
            Dictionary with success status or error message
        """
        try:
            # Load current config
            config_data = self.config_manager.load_config()
            
            # Find and remove the environment
            environments = config_data.get("environments", [])
            original_count = len(environments)
            
            environments = [env for env in environments if env["id"] != env_id]
            
            if len(environments) == original_count:
                return {
                    "success": False,
                    "error_code": ErrorCode.VALIDATION_FAILED,
                    "error_message": f"Environment not found: {env_id}"
                }
            
            # Update config
            config_data["environments"] = environments
            
            # If deleted environment was current, clear current environment
            if config_data.get("current_environment_id") == env_id:
                config_data["current_environment_id"] = None
            
            # Save config
            self.config_manager.save_config(config_data)
            
            return {
                "success": True
            }
        except Exception as e:
            return {
                "success": False,
                "error_code": ErrorCode.UNKNOWN_ERROR,
                "error_message": str(e)
            }
    
    def update_environment(self, env_id: str, config: dict) -> dict:
        """
        Update a ComfyUI environment configuration.
        
        Args:
            env_id: ID of the environment to update
            config: New configuration data (can be partial or full environment object)
            
        Returns:
            Dictionary with success status and updated environment data or error message
        """
        try:
            # Load current config
            config_data = self.config_manager.load_config()
            
            # Find the environment
            environment = None
            env_index = -1
            for i, env in enumerate(config_data.get("environments", [])):
                if env["id"] == env_id:
                    environment = env
                    env_index = i
                    break
            
            if not environment:
                return {
                    "success": False,
                    "error_code": ErrorCode.VALIDATION_FAILED,
                    "error_message": f"Environment not found: {env_id}"
                }
            
            # 更新环境配置
            # 支持更新 name、alias、general、acceleration 等字段
            if "name" in config:
                environment["name"] = config["name"]
            if "alias" in config:
                environment["alias"] = config["alias"]
            if "general" in config:
                # 前端传递的是驼峰命名，需要转换为蛇形命名
                general_config = config["general"]
                if "config" not in environment:
                    environment["config"] = {"general": {}, "acceleration": {}}
                if "general" not in environment["config"]:
                    environment["config"]["general"] = {}
                
                # 转换驼峰命名到蛇形命名
                if "comfyuiPath" in general_config:
                    old_comfyui_path = environment.get("config", {}).get("general", {}).get("comfyui_path", "")
                    new_comfyui_path = general_config["comfyuiPath"]
                    environment["config"]["general"]["comfyui_path"] = new_comfyui_path
                    environment["path"] = new_comfyui_path
                    if old_comfyui_path and old_comfyui_path != new_comfyui_path:
                        shortcuts = environment.get("config", {}).get("folder_shortcuts", [])
                        for shortcut in shortcuts:
                            old_shortcut_path = shortcut.get("path", "")
                            if old_shortcut_path and old_shortcut_path.startswith(old_comfyui_path):
                                shortcut["path"] = old_shortcut_path.replace(old_comfyui_path, new_comfyui_path)
                        logger.info(f"[update_environment] 已同步顶层 path 和 folder_shortcuts: {old_comfyui_path} -> {new_comfyui_path}")
                if "pythonPath" in general_config:
                    environment["config"]["general"]["python_path"] = general_config["pythonPath"]
                if "pipPath" in general_config:
                    environment["config"]["general"]["pip_path"] = general_config["pipPath"]
                if "gitPath" in general_config:
                    environment["config"]["general"]["git_path"] = general_config["gitPath"]
            
            if "acceleration" in config:
                # 前端传递的是驼峰命名，需要转换为蛇形命名
                accel_config = config["acceleration"]
                if "config" not in environment:
                    environment["config"] = {"general": {}, "acceleration": {}}
                if "acceleration" not in environment["config"]:
                    environment["config"]["acceleration"] = {}
                
                # 完整的字段映射表（驼峰→蛇形）
                # 确保所有前端字段都正确映射到后端字段
                field_mapping = {
                    # 设备与预设
                    "computeDevice": "compute_device",
                    # VRAM 管理
                    "vramStrategy": "vram_mode",
                    "cpuOnly": "use_cpu",
                    "gpuOnly": "use_gpu_only",
                    "reserveVram": "reserve_vram",
                    # 精度设置
                    "unetPrecision": "unet_precision",
                    "vaePrecision": "vae_precision",
                    "textEncPrecision": "text_enc_precision",
                    # 注意力机制
                    "attentionMode": "attention_type",
                    "disableXformers": "disable_xformers",
                    # 内存优化
                    "disableSmartMemory": "disable_smart_memory",
                    "forceChannelsLast": "force_channels_last",
                    "cacheLru": "cache_lru",
                    # 性能选项
                    "deterministic": "deterministic",
                    "fastMode": "fast_mode",
                    "cudaMalloc": "cuda_malloc",
                    # 网络设置
                    "listenNetwork": "listen",
                    "listenAddress": "listen_address",
                    "port": "port",
                    "enableCors": "enable_cors",
                    "tlsKeyfile": "tls_keyfile",
                    "tlsCertfile": "tls_certfile",
                    # 目录设置
                    "baseDirectory": "base_directory",
                    "inputDirectory": "input_directory",
                    "outputDirectory": "output_directory",
                    "tempDirectory": "temp_directory",
                    "userDirectory": "user_directory",
                    # 工作流目录：前端必须映射进来，否则用户填的值根本写不进
                    # acceleration，磁盘上永远没有 workflow_directory。
                    "workflowDirectory": "workflow_directory",
                    "extraModelPathsConfig": "extra_model_paths_config",
                    # 启动选项
                    # 预览设置
                    "previewMethod": "preview_method",
                    "previewSize": "preview_size",
                    # 安全与管理
                    "safeMode": "disable_all_custom_nodes",
                    "enableManager": "enable_manager",
                    # 日志与元数据
                    "logLevel": "verbose",
                    "disableMetadata": "disable_metadata",
                    # 缺失节点处理（同步到 ComfyUI-Manager 插件配置）
                    "autoDownloadMissingNodes": "auto_download_missing_nodes",
                }

                # 应用字段映射
                for frontend_key, backend_key in field_mapping.items():
                    if frontend_key in accel_config:
                        environment["config"]["acceleration"][backend_key] = accel_config[frontend_key]

                # 「自动下载缺失节点」开关变化时，同步 ComfyUI-Manager 插件的 config.ini：
                # 开 = 打开 Manager 的安装权限（一键安装缺失节点可用）
                # 关 = 收回权限（恢复默认，不允许自动安装）
                if "autoDownloadMissingNodes" in accel_config:
                    try:
                        enabled = bool(accel_config["autoDownloadMissingNodes"])
                        self._sync_manager_missing_nodes_config(
                            environment.get("config", {}).get("general", {}).get("comfyui_path", ""),
                            enabled,
                        )
                    except Exception as e:
                        logger.warning(f"[update_environment] 同步 ComfyUI-Manager 缺失节点配置失败: {e}")
                
                # 特殊处理：极客模式配置（嵌套对象）
                if "geekMode" in accel_config:
                    geek_mode = accel_config["geekMode"]
                    if isinstance(geek_mode, dict):
                        environment["config"]["acceleration"]["geek_mode"] = {
                            "enabled": geek_mode.get("enabled", False),
                            "custom_args": geek_mode.get("customArgs", ""),
                            "current_preset_id": geek_mode.get("currentPresetId", "custom")
                        }
                        logger.debug(f"[update_environment] 已更新极客模式配置: enabled={geek_mode.get('enabled')}, currentPresetId={geek_mode.get('currentPresetId')}")
                
                logger.debug(f"[update_environment] 已映射 {len([k for k in field_mapping.keys() if k in accel_config])} 个加速配置字段")
            
            # 处理高级环境变量（在 config 根级别，不在 acceleration 中）
            if "advancedEnvVars" in config:
                if "config" not in environment:
                    environment["config"] = {"general": {}, "acceleration": {}}
                environment["config"]["advanced_env_vars"] = config["advancedEnvVars"]
                logger.debug(f"[update_environment] 已更新高级环境变量配置: {len(config['advancedEnvVars'])} 字符")
            
            # 处理模型路径配置
            if "modelPathConfigs" in config:
                model_path_configs = []
                for cfg in config["modelPathConfigs"]:
                    if isinstance(cfg, dict):
                        model_path_configs.append({
                            "name": cfg.get("name", ""),
                            "base_path": cfg.get("basePath", cfg.get("base_path", "")),
                            "is_default": cfg.get("isDefault", cfg.get("is_default", False)),
                            "paths": cfg.get("paths", {})
                        })
                environment["model_path_configs"] = model_path_configs
                logger.debug(f"[update_environment] 已更新模型路径配置: {len(model_path_configs)} 个配置")
            
            # Update timestamp
            environment["updated_at"] = datetime.now().isoformat()
            
            # Save config
            config_data["environments"][env_index] = environment
            self.config_manager.save_config(config_data)
            
            # 如果更新了模型路径配置，自动生成 YAML 文件
            if "modelPathConfigs" in config:
                try:
                    from .model_path_manager import ModelPathManager
                    model_path_manager = ModelPathManager(self)
                    yaml_result = model_path_manager.generate_yaml(env_id)
                    if yaml_result.get("success"):
                        logger.debug(f"[update_environment] 已生成 extra_model_paths.yaml")
                    else:
                        logger.warning(f"[update_environment] 生成 YAML 文件失败: {yaml_result.get('error_message')}")
                except Exception as e:
                    logger.warning(f"[update_environment] 生成 YAML 文件异常: {e}")
            
            logger.debug(f"[update_environment] 环境配置已更新: {env_id}")
            
            updated_env = Environment.from_dict(environment)
            current_env_id = self.config_manager.get_current_environment_id()
            result_dict = self._format_environment_for_frontend(updated_env, current_env_id)
            
            return {
                "success": True,
                "environment": result_dict
            }
        except Exception as e:
            import traceback
            logger.error(f"[update_environment] 更新失败: {e}")
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "error_code": ErrorCode.UNKNOWN_ERROR,
                "error_message": str(e)
            }
    
    def set_current_environment(self, env_id: str) -> dict:
        """
        Set the current active environment.
        
        Args:
            env_id: ID of the environment to set as current
            
        Returns:
            Dictionary with success status or error message
        """
        try:
            # Load current config
            config_data = self.config_manager.load_config()
            
            # Check if environment exists
            environment_exists = False
            for env in config_data.get("environments", []):
                if env["id"] == env_id:
                    environment_exists = True
                    break
            
            if not environment_exists:
                return {
                    "success": False,
                    "error_code": ErrorCode.VALIDATION_FAILED,
                    "error_message": f"Environment not found: {env_id}"
                }
            
            # Set current environment
            config_data["current_environment_id"] = env_id
            
            # Save config
            self.config_manager.save_config(config_data)
            
            return {
                "success": True
            }
        except Exception as e:
            return {
                "success": False,
                "error_code": ErrorCode.UNKNOWN_ERROR,
                "error_message": str(e)
            }
    
    def get_environments(self, include_dependencies: bool = False) -> dict:
        """
        Get all ComfyUI environments.
        
        Args:
            include_dependencies: 是否包含依赖信息（默认 False，提升性能）
                                 注意：此参数已废弃，依赖信息始终从配置文件读取
        
        Returns:
            Dictionary with success status and list of environments
        """
        try:
            environments = self.config_manager.get_environments()
            
            current_env_id = self.config_manager.get_current_environment_id()
            
            env_list = []
            for env in environments:
                formatted_env = self._format_environment_for_frontend(env, current_env_id)
                env_list.append(formatted_env)
            
            return {
                "success": True,
                "environments": env_list,
                "current_environment_id": current_env_id
            }
        except Exception as e:
            logger.error(f"[get_environments] 异常: {type(e).__name__}: {e}")
            return {
                "success": False,
                "error_code": ErrorCode.UNKNOWN_ERROR,
                "error_message": str(e)
            }
    
    def get_environment(self, env_id: str) -> dict:
        """
        Get a specific ComfyUI environment.
        
        Args:
            env_id: ID of the environment
            
        Returns:
            Dictionary with success status and environment data or error message
        """
        try:
            environment = self.config_manager.get_environment(env_id)
            
            if not environment:
                return {
                    "success": False,
                    "error_code": ErrorCode.VALIDATION_FAILED,
                    "error_message": f"Environment not found: {env_id}"
                }
            
            current_env_id = self.config_manager.get_current_environment_id()
            formatted_env = self._format_environment_for_frontend(environment, current_env_id)
            
            return {
                "success": True,
                "environment": formatted_env
            }
        except Exception as e:
            return {
                "success": False,
                "error_code": ErrorCode.UNKNOWN_ERROR,
                "error_message": str(e)
            }
    
    def scan_environment(self, path: str, lang: str = "en") -> dict:
        """
        Scan a ComfyUI environment and return detailed information.
        
        Args:
            path: Path to the ComfyUI installation
            lang: Language code ("en" or "zh")
            
        Returns:
            Dictionary with scan results
        """
        try:
            # 检测环境类型
            from .environment_type_detector import EnvironmentTypeDetector
            comfyui_path, env_type, desktop_data_path, _ = EnvironmentTypeDetector.detect(path)
            
            # 创建带语言参数的扫描器
            scanner = EnvironmentScanner(lang=lang)
            scan_result = scanner.scan_environment(comfyui_path, env_type, desktop_data_path)
            
            # Get dependencies if Python is available
            dependencies = {}
            if scan_result.get("python_directory"):
                python_exe = Path(scan_result["python_directory"]) / ("python.exe" if Path(scan_result["python_directory"]).joinpath("python.exe").exists() else "python")
                if python_exe.exists():
                    dep_info = self.dependency_detector.get_dependencies(str(python_exe))
                    dependencies = dep_info.to_dict()
            
            scan_result["dependencies"] = dependencies
            scan_result["env_type"] = env_type
            
            return {
                "success": True,
                "scan_result": scan_result
            }
        except Exception as e:
            return {
                "success": False,
                "error_code": ErrorCode.UNKNOWN_ERROR,
                "error_message": str(e)
            }
    
    def update_dependencies(self, env_id: str, save_config: bool = True) -> dict:
        """
        Update dependency information for a specific environment and save to config.
        
        此方法用于手动刷新环境的依赖信息：
        1. 检测最新的依赖版本
        2. 更新到 Environment 对象
        3. 保存到配置文件（可选）
        
        Args:
            env_id: ID of the environment
            save_config: 是否立即保存配置文件（默认 True，批量更新时可设为 False）
            
        Returns:
            Dictionary with success status and updated dependency information or error message
        """
        try:
            # Load current config
            config_data = self.config_manager.load_config()
            
            # Find the environment
            environment = None
            env_index = -1
            for i, env_dict in enumerate(config_data.get("environments", [])):
                if env_dict["id"] == env_id:
                    environment = Environment.from_dict(env_dict)
                    env_index = i
                    break
            
            if not environment:
                return {
                    "success": False,
                    "error_code": ErrorCode.VALIDATION_FAILED,
                    "error_message": f"Environment not found: {env_id}"
                }
            
            # Get Python path from environment config
            python_path = environment.config.general.python_path
            if not python_path:
                return {
                    "success": False,
                    "error_code": ErrorCode.PYTHON_NOT_FOUND,
                    "error_message": "Python path not configured"
                }
            
            # Detect dependencies
            dependencies = self.dependency_detector.get_dependencies(python_path)
            logger.debug(f"[update_dependencies] 依赖信息检测完成: Python {dependencies.python}, PyTorch {dependencies.pytorch}")
            
            # Update environment dependencies
            environment.dependencies = dependencies
            environment.updated_at = datetime.now().isoformat()
            
            # Update config
            config_data["environments"][env_index] = environment.to_dict()
            
            # Save config (optional)
            if save_config:
                self.config_manager.save_config(config_data)
            
            return {
                "success": True,
                "dependencies": self._map_dependency_fields(dependencies),
                "config_data": config_data  # 返回更新后的配置数据，供批量保存使用
            }
        except Exception as e:
            return {
                "success": False,
                "error_code": ErrorCode.UNKNOWN_ERROR,
                "error_message": str(e)
            }
    
    def get_dependencies(self, env_id: str) -> dict:
        """
        Get dependency information for a specific environment.
        
        此方法会主动更新依赖信息并保存到配置文件，
        相当于用户点击"刷新依赖"按钮的操作。
        
        Args:
            env_id: ID of the environment
            
        Returns:
            Dictionary with success status and dependency information or error message
        """
        # 调用 update_dependencies 更新并返回最新依赖
        return self.update_dependencies(env_id)
    
    def get_current_environment(self) -> Optional[Environment]:
        """
        获取当前环境对象
        
        Returns:
            Environment: 当前环境对象，如果没有当前环境则返回 None
        """
        try:
            # 获取当前环境 ID
            current_env_id = self.config_manager.get_current_environment_id()
            
            if not current_env_id:
                return None
            
            # 获取环境对象
            environment = self.config_manager.get_environment(current_env_id)
            
            return environment
            
        except Exception as e:
            logger.error(f"[get_current_environment] 获取当前环境失败: {e}")
            return None
    def get_current_environment_id(self) -> Optional[str]:
        """
        获取当前环境 ID

        Returns:
            str: 当前环境 ID，如果没有当前环境则返回 None
        """
        try:
            return self.config_manager.get_current_environment_id()
        except Exception as e:
            logger.error(f"[get_current_environment_id] 获取当前环境 ID 失败: {e}")
            return None
    
    def reorder_environments(self, env_ids: List[str]) -> dict:
        """
        重新排序环境列表
        
        Args:
            env_ids: 按新顺序排列的环境 ID 列表
            
        Returns:
            dict: 操作结果
        """
        try:
            # 加载当前配置
            config_data = self.config_manager.load_config()
            
            # 获取当前环境列表
            environments = config_data.get("environments", [])
            
            # 创建 ID 到环境的映射
            env_map = {env["id"]: env for env in environments}
            
            # 验证所有 ID 都存在
            for env_id in env_ids:
                if env_id not in env_map:
                    return {
                        "success": False,
                        "error_code": ErrorCode.VALIDATION_FAILED,
                        "error_message": f"Environment not found: {env_id}"
                    }
            
            # 按新顺序重新排列
            reordered_environments = [env_map[env_id] for env_id in env_ids]
            
            # 更新配置
            config_data["environments"] = reordered_environments
            
            # 保存配置
            self.config_manager.save_config(config_data)
            
            logger.info(f"[reorder_environments] 环境排序已更新: {env_ids}")
            
            return {
                "success": True,
                "message": "环境排序已更新"
            }
            
        except Exception as e:
            logger.error(f"[reorder_environments] 排序失败: {e}")
            return {
                "success": False,
                "error_code": ErrorCode.UNKNOWN_ERROR,
                "error_message": str(e)
            }

    
    def save_environment_config(self, env_id: str, config: EnvironmentConfig) -> dict:
        """
        保存环境配置
        
        Args:
            env_id: 环境 ID
            config: 环境配置对象
            
        Returns:
            dict: 操作结果
        """
        try:
            # 加载当前配置
            config_data = self.config_manager.load_config()
            
            # 查找环境
            environment = None
            env_index = -1
            for i, env_dict in enumerate(config_data.get("environments", [])):
                if env_dict["id"] == env_id:
                    environment = Environment.from_dict(env_dict)
                    env_index = i
                    break
            
            if not environment:
                return {
                    "success": False,
                    "error_code": ErrorCode.VALIDATION_FAILED,
                    "error_message": f"Environment not found: {env_id}"
                }
            
            # 更新配置
            environment.config = config
            if config.general.comfyui_path:
                environment.path = config.general.comfyui_path
            environment.updated_at = datetime.now().isoformat()
            
            # 保存到配置文件
            config_data["environments"][env_index] = environment.to_dict()
            self.config_manager.save_config(config_data)
            
            return {
                "success": True,
                "message": "环境配置保存成功"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error_code": ErrorCode.UNKNOWN_ERROR,
                "error_message": str(e)
            }
    
    def _get_plugin_controller(self) -> "PluginController":
        """
        获取插件控制器实例（单例模式）
        
        此方法使用延迟导入避免循环依赖，并确保在整个 EnvironmentManager 
        生命周期中只创建一个 PluginController 实例。
        
        配置说明：
        - cache_dir: 插件缓存目录，存储在 backend/config/plugins
        - git_path: Git 可执行文件路径，使用系统默认的 "git"
        - python_path: Python 路径，设置为 None（由 PluginController 自动检测）
        - max_workers: 最大并发数，设置为 10（平衡性能和资源占用）
        
        Returns:
            PluginController: 插件控制器实例
        """
        if not hasattr(self, '_plugin_controller'):
            # 延迟导入避免循环依赖
            from ..plugin.plugin_controller import PluginController
            from ...utils.git_config import GIT_EXECUTABLE
            from ...utils.paths import get_config_dir
            
            # 配置缓存目录（使用绝对路径）
            cache_dir = get_config_dir("plugins")
            
            # 创建插件控制器实例
            self._plugin_controller = PluginController(
                cache_dir=cache_dir,
                git_path=GIT_EXECUTABLE,
                python_path=None,
                max_workers=10
            )
            
            logger.debug("[_get_plugin_controller] 插件控制器实例已创建")
        
        return self._plugin_controller
