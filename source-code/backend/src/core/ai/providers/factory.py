"""
ProviderFactory 工厂类

负责根据配置创建对应的 AI Provider 实例。
使用工厂模式实现 Provider 的动态创建和注册。
"""

from typing import Dict, Any, Type
from .base_provider import BaseProvider
from .openai_provider import OpenAIProvider
from .spark_provider import SparkProvider
from .volcengine_provider import VolcengineProvider
from .zhipu_provider import ZhipuProvider
from .ollama_provider import OllamaProvider


class ProviderFactory:
    """AI Provider 工厂类
    
    负责创建和管理不同类型的 AI Provider 实例。
    支持动态注册新的 Provider 类型。
    """
    
    # Provider 注册表：provider_name -> Provider 类
    # 说明：除 spark/volcengine/zhipu/ollama 有专属实现外，
    # 其余服务商均提供 OpenAI 兼容接口，统一复用 OpenAIProvider。
    _providers: Dict[str, Type[BaseProvider]] = {
        # ---- OpenAI 兼容 ----
        'openai': OpenAIProvider,           # OpenAI 官方
        'custom-openai': OpenAIProvider,    # 通用 OpenAI API（自定义 baseUrl）
        'deepseek': OpenAIProvider,
        'moonshot': OpenAIProvider,         # Kimi
        'qwen': OpenAIProvider,             # 阿里百炼/通义千问
        'minimax': OpenAIProvider,
        'hunyuan': OpenAIProvider,          # 腾讯混元（OpenAI 兼容端点）
        'qianfan': OpenAIProvider,          # 百度千帆（v2 OpenAI 兼容端点）
        'siliconflow': OpenAIProvider,      # 硅基流动
        'groq': OpenAIProvider,
        'mistral': OpenAIProvider,
        'xai': OpenAIProvider,              # Grok
        'gemini': OpenAIProvider,           # Google OpenAI 兼容层
        'anthropic': OpenAIProvider,        # Claude（官方 OpenAI 兼容端点）
        'openrouter': OpenAIProvider,
        'together': OpenAIProvider,
        'fireworks': OpenAIProvider,
        'cohere': OpenAIProvider,           # 实验性兼容端点
        # ---- 本地模型 ----
        'ollama': OllamaProvider,
        'llamacpp': OpenAIProvider,         # llama.cpp server (http://127.0.0.1:8080/v1)
        # ---- 项目合作/既有 ----
        'xflow': OpenAIProvider,
        'iflow': OpenAIProvider,
        'spark': SparkProvider,
        'volcengine': VolcengineProvider,
        'zhipu': ZhipuProvider,
    }

    # Provider 默认 Base URL 配置
    _default_base_urls: Dict[str, str] = {
        'openai': 'https://api.openai.com/v1',
        'deepseek': 'https://api.deepseek.com/v1',
        'moonshot': 'https://api.moonshot.cn/v1',
        'qwen': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'minimax': 'https://api.minimax.chat/v1',
        'hunyuan': 'https://api.hunyuan.cloud.tencent.com/v1',
        'qianfan': 'https://qianfan.baidubce.com/v2',
        'siliconflow': 'https://api.siliconflow.cn/v1',
        'groq': 'https://api.groq.com/openai/v1',
        'mistral': 'https://api.mistral.ai/v1',
        'xai': 'https://api.x.ai/v1',
        'gemini': 'https://generativelanguage.googleapis.com/v1beta/openai',
        'anthropic': 'https://api.anthropic.com/v1',
        'openrouter': 'https://openrouter.ai/api/v1',
        'together': 'https://api.together.xyz/v1',
        'fireworks': 'https://api.fireworks.ai/inference/v1',
        'cohere': 'https://api.cohere.ai/compatibility/v1',
        'ollama': 'http://localhost:11434',
        'llamacpp': 'http://127.0.0.1:8080/v1',
        'xflow': 'https://api.xflow.cc/v1',
        'iflow': 'https://apis.iflow.cn/v1',
        'volcengine': 'https://ark.cn-beijing.volces.com/api/v3',
        'zhipu': 'https://open.bigmodel.cn/api/paas/v4',
    }
    
    @classmethod
    def create(cls, provider_name: str, config: Dict[str, Any], use_proxy: bool = False) -> BaseProvider:
        """创建 Provider 实例
        
        Args:
            provider_name: Provider 名称（openai/spark/volcengine/zhipu/ollama）
            config: Provider 配置字典
                {
                    "api_key": str,
                    "base_url": str,  # 可选
                    "model": str,
                    "temperature": float,
                    "max_tokens": int,
                    ...
                }
            use_proxy: 是否使用系统代理（默认 False）
        
        Returns:
            BaseProvider: Provider 实例
        
        Raises:
            ValueError: 当 provider_name 不存在时抛出
        
        Example:
            config = {
                "api_key": "sk-xxx",
                "model": "gpt-4o",
                "temperature": 0.7
            }
            provider = ProviderFactory.create("openai", config, use_proxy=True)
        """
        # 检查 provider_name 是否有效
        if provider_name not in cls._providers:
            available = ', '.join(cls._providers.keys())
            raise ValueError(
                f"未知的 Provider: '{provider_name}'. "
                f"可用的 Provider: {available}"
            )
        
        # 复制配置，避免修改原始配置
        config = config.copy()
        
        # 如果 base_url 为空且该 provider 有默认 URL，则设置默认值
        if not config.get('base_url') and provider_name in cls._default_base_urls:
            config['base_url'] = cls._default_base_urls[provider_name]

        # 本地推理服务（llama.cpp server / LM Studio 等）不校验 API Key，
        # 但 OpenAIProvider 强制要求非空，这里注入占位值放行。
        if provider_name == 'llamacpp' and not config.get('api_key'):
            config['api_key'] = 'not-needed'
        
        # 获取 Provider 类
        provider_class = cls._providers[provider_name]
        
        # 创建并返回实例（传递 use_proxy 参数）
        return provider_class(config, use_proxy=use_proxy)
    
    @classmethod
    def register(cls, provider_name: str, provider_class: Type[BaseProvider]) -> None:
        """注册新的 Provider 类型
        
        Args:
            provider_name: Provider 名称
            provider_class: Provider 类（必须继承自 BaseProvider）
        
        Raises:
            TypeError: 当 provider_class 不是 BaseProvider 的子类时抛出
        
        Example:
            class CustomProvider(BaseProvider):
                ...
            
            ProviderFactory.register("custom", CustomProvider)
        """
        # 验证 provider_class 是 BaseProvider 的子类
        if not issubclass(provider_class, BaseProvider):
            raise TypeError(
                f"Provider 类必须继承自 BaseProvider, "
                f"但得到: {provider_class.__name__}"
            )
        
        # 注册到注册表
        cls._providers[provider_name] = provider_class
    
    @classmethod
    def get_available_providers(cls) -> list[str]:
        """获取所有已注册的 Provider 名称列表
        
        Returns:
            Provider 名称列表
        
        Example:
            providers = ProviderFactory.get_available_providers()
            # ['openai', 'spark', 'volcengine', ...]
        """
        return list(cls._providers.keys())
    
    @classmethod
    def is_provider_available(cls, provider_name: str) -> bool:
        """检查指定的 Provider 是否可用
        
        Args:
            provider_name: Provider 名称
        
        Returns:
            是否可用
        
        Example:
            if ProviderFactory.is_provider_available("openai"):
                provider = ProviderFactory.create("openai", config)
        """
        return provider_name in cls._providers
