"""
配置管理模块
支持从环境变量读取敏感配置
"""
import os
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """应用配置"""
    
    # 服务配置
    APP_NAME: str = "AI Learning Coach API"
    APP_VERSION: str = "2.0.0"  # 升级到 Agent 版本
    DEBUG: bool = False
    
    # DeepSeek AI 配置（文本模型）
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_BASE: str = "https://api.deepseek.com/v1"  # LangChain 使用 api_base
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    
    # DeepSeek 视觉模型
    DEEPSEEK_VISION_MODEL: str = "deepseek-chat"  # DeepSeek 视觉模型
    
    # 视觉模型配置（备用）
    VISION_API_KEY: str = os.getenv("VISION_API_KEY", "")
    VISION_BASE_URL: str = "https://api.gptsapi.net/v1"
    VISION_MODEL: str = "gpt-4o"
    
    # Tavily 搜索配置
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
    TAVILY_BASE_URL: str = "https://api.tavily.com"
    
    # 腾讯云 COS 配置（用于 PDF 处理）
    COS_SECRET_ID: str = os.getenv("COS_SECRET_ID", "")
    COS_SECRET_KEY: str = os.getenv("COS_SECRET_KEY", "")
    COS_BUCKET: str = os.getenv("COS_BUCKET", "")
    COS_REGION: str = "ap-shanghai"
    
    # 跨域配置
    CORS_ORIGINS: list = ["*"]
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# 全局配置实例
settings = Settings()


# AI 模型配置字典
AI_MODELS = {
    "text": {
        "api_key": settings.DEEPSEEK_API_KEY,
        "base_url": settings.DEEPSEEK_BASE_URL,
        "model": settings.DEEPSEEK_MODEL,
        "max_tokens": 4000,
    },
    "vision": {
        "api_key": settings.VISION_API_KEY,
        "base_url": settings.VISION_BASE_URL,
        "model": settings.VISION_MODEL,
        "max_tokens": 4000,
    },
    "longtext": {
        "api_key": settings.DEEPSEEK_API_KEY,
        "base_url": settings.DEEPSEEK_BASE_URL,
        "model": settings.DEEPSEEK_MODEL,
        "max_tokens": 8000,
    },
}
