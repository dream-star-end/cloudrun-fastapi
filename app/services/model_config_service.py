"""
模型配置服务模块
负责从云数据库读取用户的模型配置，支持缓存和配置合并

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class ModelConfigService:
    """
    用户模型配置服务
    
    负责从云数据库读取用户配置的默认模型，支持：
    - 内存缓存（5分钟TTL）减少数据库查询
    - 配置合并（用户配置覆盖系统默认）
    - 多种模型类型（text/voice/multimodal）
    """
    
    # 内存缓存，key: openid, value: (config, expire_time)
    _cache: Dict[str, tuple] = {}
    _cache_ttl = timedelta(minutes=5)
    
    # 系统默认配置
    DEFAULT_CONFIG = {
        "text": {
            "platform": "deepseek",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        },
        "vision": {
            "platform": "deepseek",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        },
        "voice": {
            "platform": "deepseek",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        },
        "multimodal": {
            "platform": "deepseek",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
        },
    }
    
    # 内置平台配置（与小程序端保持一致）
    BUILTIN_PLATFORMS = {
        "deepseek": {
            "name": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
        },
        "qwen": {
            "name": "通义千问",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        },
        "zhipu": {
            "name": "智谱AI",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
        },
        "siliconflow": {
            "name": "硅基流动",
            "base_url": "https://api.siliconflow.cn/v1",
        },
        "minimax": {
            "name": "MiniMax",
            "base_url": "https://api.minimax.chat/v1",
        },
        "openai": {
            "name": "OpenAI",
            "base_url": "https://api.openai.com/v1",
        },
    }
    
    @classmethod
    async def get_user_config(cls, openid: str) -> Dict[str, Any]:
        """
        获取用户模型配置，支持缓存
        
        Args:
            openid: 用户的 openid
            
        Returns:
            用户的完整模型配置，包含 platformConfigs, customPlatforms, defaults
        """
        # 检查缓存
        if openid in cls._cache:
            config, expire_time = cls._cache[openid]
            if datetime.now() < expire_time:
                logger.debug(f"[ModelConfigService] 使用缓存配置: openid={openid[:8]}...")
                return config
            else:
                # 缓存过期，删除
                del cls._cache[openid]
                logger.debug(f"[ModelConfigService] 缓存已过期: openid={openid[:8]}...")
        
        # 从数据库读取
        logger.info(f"[ModelConfigService] 从数据库读取配置: openid={openid[:8]}...")
        
        try:
            from ..db import get_db
            db = get_db()
            
            # 查询 model_configs 集合
            user_config = await db.get_one("model_configs", {"_openid": openid})
            
            if user_config:
                logger.info(f"[ModelConfigService] 找到用户配置: openid={openid[:8]}...")
                # 合并配置
                merged_config = cls._merge_with_defaults(user_config)
            else:
                logger.info(f"[ModelConfigService] 用户无配置，使用默认: openid={openid[:8]}...")
                # 返回默认配置
                merged_config = {
                    "platformConfigs": {},
                    "customPlatforms": [],
                    "defaults": {
                        "text": None,
                        "voice": None,
                        "multimodal": None,
                    },
                    "_merged_defaults": cls.DEFAULT_CONFIG.copy(),
                }
            
            # 写入缓存
            cls._cache[openid] = (merged_config, datetime.now() + cls._cache_ttl)
            logger.debug(f"[ModelConfigService] 配置已缓存: openid={openid[:8]}...")
            
            return merged_config
            
        except Exception as e:
            logger.error(f"[ModelConfigService] 读取配置失败: {type(e).__name__}: {e}")
            # 出错时返回默认配置
            return {
                "platformConfigs": {},
                "customPlatforms": [],
                "defaults": {
                    "text": None,
                    "voice": None,
                    "multimodal": None,
                },
                "_merged_defaults": cls.DEFAULT_CONFIG.copy(),
            }
    
    @classmethod
    async def get_model_for_type(
        cls,
        openid: str,
        model_type: str,
    ) -> Dict[str, Any]:
        """
        获取指定类型的模型配置
        
        Args:
            openid: 用户的 openid
            model_type: 模型类型 (text/voice/multimodal/vision)
            
        Returns:
            模型配置字典，包含 platform, model, base_url, api_key, model_types, api_format 等
            model_types: 模型支持的输入类型列表，如 ["text", "voice"]
            api_format: API 格式，openai 或 gemini
        """
        # vision 和 multimodal 统一处理
        if model_type == "vision":
            model_type = "multimodal"
        
        user_config = await cls.get_user_config(openid)
        defaults = user_config.get("defaults", {})
        platform_configs = user_config.get("platformConfigs", {})
        custom_platforms = user_config.get("customPlatforms", [])
        
        # 获取用户设置的默认模型
        default_setting = defaults.get(model_type)
        
        if default_setting and default_setting.get("configId"):
            config_id = default_setting["configId"]
            model_id = default_setting.get("modelId")
            model_name = default_setting.get("modelName")
            # 获取模型支持的输入类型（用户在配置时选择的标签）
            model_types = default_setting.get("modelTypes", [])
            
            # 查找平台配置
            platform_config = cls._find_platform_config(
                config_id, platform_configs, custom_platforms
            )
            
            # 优先使用平台配置中的 apiKey，如果没有则使用 default_setting 中直接存储的 apiKey
            # （小程序在保存默认模型时会将 apiKey 直接存储在 defaults 中）
            api_key = None
            base_url = None
            api_format = "openai"
            
            if platform_config:
                api_key = platform_config.get("apiKey")
                base_url = platform_config.get("baseUrl")
                api_format = platform_config.get("apiFormat", "openai")
            
            # 如果平台配置中没有 apiKey，尝试从 default_setting 中获取
            if not api_key:
                api_key = default_setting.get("apiKey")
            if not base_url:
                base_url = default_setting.get("baseUrl")
            
            if api_key:
                logger.info(f"[ModelConfigService] 使用用户配置: type={model_type}, platform={config_id}, model={model_id}, model_types={model_types}, api_format={api_format}")
                return {
                    "platform": config_id,
                    "model": model_id or model_name,
                    "model_name": model_name,
                    "base_url": base_url or cls._get_platform_base_url(config_id),
                    "api_key": api_key,
                    "is_user_config": True,
                    "model_types": model_types,  # 模型支持的输入类型
                    "api_format": api_format,  # API 格式
                }
        
        # 用户未配置或配置无效，使用系统默认
        logger.info(f"[ModelConfigService] 使用系统默认: type={model_type}")
        system_default = cls.DEFAULT_CONFIG.get(model_type, cls.DEFAULT_CONFIG["text"])
        
        # 系统默认配置不包含 API Key，需要用户自行配置
        # 返回空 api_key，让调用方处理（如显示配置提示）
        return {
            "platform": system_default["platform"],
            "model": system_default["model"],
            "model_name": system_default["model"],
            "base_url": system_default["base_url"],
            "api_key": "",  # 系统默认不提供 API Key，需要用户配置
            "is_user_config": False,
            "model_types": ["text"],  # 系统默认只支持文本
            "api_format": "openai",  # 系统默认使用 OpenAI 格式
        }
    
    @classmethod
    def _merge_with_defaults(
        cls,
        user_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        合并用户配置与系统默认配置
        
        Args:
            user_config: 用户在数据库中的配置
            
        Returns:
            合并后的完整配置
        """
        platform_configs = user_config.get("platformConfigs", {})
        custom_platforms = user_config.get("customPlatforms", [])
        defaults = user_config.get("defaults", {})
        
        # 构建合并后的默认模型配置
        merged_defaults = {}
        
        for model_type in ["text", "voice", "multimodal"]:
            default_setting = defaults.get(model_type)
            
            if default_setting and default_setting.get("configId"):
                config_id = default_setting["configId"]
                platform_config = cls._find_platform_config(
                    config_id, platform_configs, custom_platforms
                )
                
                # 优先使用平台配置中的 apiKey，如果没有则使用 default_setting 中直接存储的 apiKey
                api_key = None
                base_url = None
                
                if platform_config:
                    api_key = platform_config.get("apiKey")
                    base_url = platform_config.get("baseUrl")
                
                # 如果平台配置中没有，尝试从 default_setting 中获取
                if not api_key:
                    api_key = default_setting.get("apiKey")
                if not base_url:
                    base_url = default_setting.get("baseUrl")
                
                if api_key:
                    # 用户配置有效
                    merged_defaults[model_type] = {
                        "platform": config_id,
                        "model": default_setting.get("modelId") or default_setting.get("modelName"),
                        "base_url": base_url or cls._get_platform_base_url(config_id),
                        "api_key": api_key,
                    }
                else:
                    # 用户配置无效，使用系统默认
                    merged_defaults[model_type] = cls.DEFAULT_CONFIG[model_type].copy()
            else:
                # 用户未配置，使用系统默认
                merged_defaults[model_type] = cls.DEFAULT_CONFIG[model_type].copy()
        
        # vision 类型与 multimodal 相同
        merged_defaults["vision"] = merged_defaults["multimodal"].copy()
        
        return {
            "platformConfigs": platform_configs,
            "customPlatforms": custom_platforms,
            "defaults": defaults,
            "_merged_defaults": merged_defaults,
        }
    
    @classmethod
    def _find_platform_config(
        cls,
        config_id: str,
        platform_configs: Dict[str, Any],
        custom_platforms: list,
    ) -> Optional[Dict[str, Any]]:
        """
        查找平台配置
        
        Args:
            config_id: 平台ID
            platform_configs: 内置平台的用户配置
            custom_platforms: 自定义平台列表
            
        Returns:
            平台配置字典，包含 apiKey, baseUrl, apiFormat 等
        """
        # 先查找内置平台配置
        if config_id in platform_configs:
            builtin_config = platform_configs[config_id]
            if builtin_config.get("apiKey"):
                return {
                    "apiKey": builtin_config["apiKey"],
                    "baseUrl": builtin_config.get("baseUrl") or cls._get_platform_base_url(config_id),
                    "enabled": builtin_config.get("enabled", True),
                    "apiFormat": "openai",  # 内置平台默认使用 OpenAI 格式
                }
        
        # 查找自定义平台
        for custom in custom_platforms:
            if custom.get("id") == config_id:
                return {
                    "apiKey": custom.get("apiKey"),
                    "baseUrl": custom.get("baseUrl"),
                    "enabled": custom.get("enabled", True),
                    "apiFormat": custom.get("apiFormat", "openai"),  # 自定义平台可配置格式
                }
        
        return None
    
    @classmethod
    def _get_platform_base_url(cls, platform_id: str) -> str:
        """
        获取内置平台的默认 base_url
        
        Args:
            platform_id: 平台ID
            
        Returns:
            平台的 API base URL
        """
        platform = cls.BUILTIN_PLATFORMS.get(platform_id)
        if platform:
            return platform["base_url"]
        return cls.DEFAULT_CONFIG["text"]["base_url"]
    
    @classmethod
    def clear_cache(cls, openid: Optional[str] = None):
        """
        清除缓存
        
        Args:
            openid: 指定用户的 openid，为 None 时清除所有缓存
        """
        if openid:
            if openid in cls._cache:
                del cls._cache[openid]
                logger.info(f"[ModelConfigService] 已清除用户缓存: openid={openid[:8]}...")
        else:
            cls._cache.clear()
            logger.info("[ModelConfigService] 已清除所有缓存")
    
    @classmethod
    def get_cache_stats(cls) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            缓存统计字典
        """
        now = datetime.now()
        valid_count = sum(1 for _, (_, expire) in cls._cache.items() if expire > now)
        
        return {
            "total_entries": len(cls._cache),
            "valid_entries": valid_count,
            "expired_entries": len(cls._cache) - valid_count,
            "ttl_minutes": cls._cache_ttl.total_seconds() / 60,
        }
