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
    
    # 微信小程序配置
    WX_APPID: str = os.getenv("WX_APPID", "")
    WX_SECRET: str = os.getenv("WX_SECRET", "")
    
    # 微信云开发配置
    TCB_ENV: str = os.getenv("TCB_ENV", "prod-3gvp927wbf0bbf20")  # 云环境ID
    
    # 跨域配置
    CORS_ORIGINS: list = ["*"]
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# 全局配置实例
settings = Settings()

# 是否在云托管环境中（多种方式检测）
IS_CLOUDRUN = any([
    os.environ.get('TCB_CONTEXT_KEYS'),      # 云托管标准环境变量
    os.environ.get('TENCENTCLOUD_RUNENV'),   # 腾讯云运行环境
    os.environ.get('TCB_ENV'),               # 云环境 ID
    os.environ.get('WX_API_TOKEN'),          # 微信 API Token
    '/app' in os.getcwd(),                   # Docker 容器中通常在 /app 目录
])

# 强制禁用 SSL 验证（如果环境检测不准确，可以通过环境变量强制设置）
DISABLE_SSL_VERIFY = os.environ.get('DISABLE_SSL_VERIFY', 'true').lower() == 'true'


def get_http_client_kwargs(timeout: float = 30.0) -> dict:
    """
    获取 HTTP 客户端的通用配置
    
    在云托管环境中禁用 SSL 验证（因为是内网通信）
    
    Args:
        timeout: 超时时间（秒）
    
    Returns:
        httpx.AsyncClient 的参数字典
    """
    # 云托管环境或强制禁用时，不验证 SSL
    verify_ssl = not (IS_CLOUDRUN or DISABLE_SSL_VERIFY)
    
    return {
        "timeout": timeout,
        "verify": verify_ssl,
        "http2": False,  # 禁用 HTTP/2 提高兼容性
    }


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
