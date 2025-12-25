"""
结构化错误日志模块

提供统一的错误日志格式，包含：
- timestamp: 错误发生时间
- error_type: 错误类型
- message: 错误消息
- openid: 用户标识（脱敏）
- request_id: 请求ID
- context: 上下文信息

Requirements: 9.5
"""
import logging
import json
import uuid
import traceback
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from enum import Enum
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# 请求上下文变量
_request_id: ContextVar[str] = ContextVar("request_id", default="")
_openid: ContextVar[str] = ContextVar("openid", default="")


class ErrorType(Enum):
    """错误类型枚举"""
    MODEL_API_ERROR = "ModelAPIError"
    MODEL_TIMEOUT = "ModelTimeout"
    MODEL_RATE_LIMIT = "ModelRateLimit"
    CONFIG_ERROR = "ConfigError"
    VALIDATION_ERROR = "ValidationError"
    IMAGE_UPLOAD_ERROR = "ImageUploadError"
    VOICE_RECOGNITION_ERROR = "VoiceRecognitionError"
    STREAM_INTERRUPTED = "StreamInterrupted"
    DATABASE_ERROR = "DatabaseError"
    NETWORK_ERROR = "NetworkError"
    UNKNOWN_ERROR = "UnknownError"


def generate_request_id() -> str:
    """生成请求ID"""
    return f"req_{uuid.uuid4().hex[:12]}"


def set_request_context(request_id: str = None, openid: str = None):
    """设置请求上下文"""
    if request_id:
        _request_id.set(request_id)
    if openid:
        _openid.set(openid)


def get_request_id() -> str:
    """获取当前请求ID"""
    return _request_id.get() or generate_request_id()


def get_openid() -> str:
    """获取当前用户openid"""
    return _openid.get()


def mask_openid(openid: str) -> str:
    """脱敏处理openid"""
    if not openid:
        return "unknown"
    if len(openid) <= 8:
        return f"{openid[:4]}***"
    return f"{openid[:8]}***"


class StructuredErrorLog:
    """结构化错误日志"""
    
    def __init__(
        self,
        error_type: ErrorType,
        message: str,
        openid: str = None,
        request_id: str = None,
        context: Dict[str, Any] = None,
        exception: Exception = None,
    ):
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.error_type = error_type.value
        self.message = message
        self.openid = mask_openid(openid or get_openid())
        self.request_id = request_id or get_request_id()
        self.context = context or {}
        self.stack_trace = None
        
        if exception:
            self.stack_trace = traceback.format_exc()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        log_dict = {
            "timestamp": self.timestamp,
            "level": "ERROR",
            "error_type": self.error_type,
            "message": self.message,
            "openid": self.openid,
            "request_id": self.request_id,
            "context": self.context,
        }
        if self.stack_trace:
            log_dict["stack_trace"] = self.stack_trace
        return log_dict
    
    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    def log(self, level: int = logging.ERROR):
        """记录日志"""
        logger.log(level, self.to_json())


def log_error(
    error_type: ErrorType,
    message: str,
    openid: str = None,
    request_id: str = None,
    context: Dict[str, Any] = None,
    exception: Exception = None,
) -> StructuredErrorLog:
    """
    记录结构化错误日志
    
    Args:
        error_type: 错误类型
        message: 错误消息
        openid: 用户标识
        request_id: 请求ID
        context: 上下文信息
        exception: 异常对象
    
    Returns:
        StructuredErrorLog 对象
    """
    error_log = StructuredErrorLog(
        error_type=error_type,
        message=message,
        openid=openid,
        request_id=request_id,
        context=context,
        exception=exception,
    )
    error_log.log()
    return error_log


def log_model_error(
    message: str,
    platform: str,
    model: str,
    openid: str = None,
    status_code: int = None,
    response_body: str = None,
    exception: Exception = None,
) -> StructuredErrorLog:
    """
    记录模型API错误
    
    Args:
        message: 错误消息
        platform: 模型平台
        model: 模型名称
        openid: 用户标识
        status_code: HTTP状态码
        response_body: 响应内容
        exception: 异常对象
    """
    # 根据状态码判断错误类型
    if status_code == 429:
        error_type = ErrorType.MODEL_RATE_LIMIT
    elif status_code == 408 or "timeout" in message.lower():
        error_type = ErrorType.MODEL_TIMEOUT
    else:
        error_type = ErrorType.MODEL_API_ERROR
    
    context = {
        "platform": platform,
        "model": model,
    }
    if status_code:
        context["status_code"] = status_code
    if response_body:
        # 截断响应内容
        context["response_body"] = response_body[:500] if len(response_body) > 500 else response_body
    
    return log_error(
        error_type=error_type,
        message=message,
        openid=openid,
        context=context,
        exception=exception,
    )


def log_config_error(
    message: str,
    openid: str = None,
    config_type: str = None,
    exception: Exception = None,
) -> StructuredErrorLog:
    """记录配置错误"""
    context = {}
    if config_type:
        context["config_type"] = config_type
    
    return log_error(
        error_type=ErrorType.CONFIG_ERROR,
        message=message,
        openid=openid,
        context=context,
        exception=exception,
    )


def log_stream_error(
    message: str,
    openid: str = None,
    partial_content_length: int = None,
    exception: Exception = None,
) -> StructuredErrorLog:
    """记录流式传输错误"""
    context = {}
    if partial_content_length is not None:
        context["partial_content_length"] = partial_content_length
    
    return log_error(
        error_type=ErrorType.STREAM_INTERRUPTED,
        message=message,
        openid=openid,
        context=context,
        exception=exception,
    )


def log_image_upload_error(
    message: str,
    openid: str = None,
    retry_count: int = None,
    file_size: int = None,
    exception: Exception = None,
) -> StructuredErrorLog:
    """记录图片上传错误"""
    context = {}
    if retry_count is not None:
        context["retry_count"] = retry_count
    if file_size is not None:
        context["file_size"] = file_size
    
    return log_error(
        error_type=ErrorType.IMAGE_UPLOAD_ERROR,
        message=message,
        openid=openid,
        context=context,
        exception=exception,
    )
