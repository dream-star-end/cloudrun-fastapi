"""
模型分发器基类和注册表模块

定义：
- ModelDispatcher: 分发器抽象基类
- DispatcherRegistry: 分发器注册表
- 响应事件类型定义
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, AsyncGenerator, Optional, Type, TypedDict, Literal, Union

logger = logging.getLogger(__name__)


# ============== 响应事件类型定义 ==============

class TextEvent(TypedDict):
    """文本内容事件"""
    type: Literal["text"]
    content: str


class DoneEvent(TypedDict):
    """完成事件"""
    type: Literal["done"]


class StreamInterruptedEvent(TypedDict):
    """流中断事件"""
    type: Literal["stream_interrupted"]
    message: str
    partial_content_length: int


class TranscriptionEvent(TypedDict):
    """语音转录事件"""
    type: Literal["transcription"]
    text: str


class ErrorEvent(TypedDict):
    """错误事件"""
    type: Literal["error"]
    error: str


# 响应事件联合类型
ResponseEvent = Union[TextEvent, DoneEvent, StreamInterruptedEvent, TranscriptionEvent, ErrorEvent]


# ============== 分发器基类 ==============

class ModelDispatcher(ABC):
    """
    模型调用分发器基类
    
    所有分发器必须继承此类并实现 call() 和 supports() 方法
    """
    
    @abstractmethod
    async def call(
        self,
        config: Dict[str, Any],
        messages: List[Dict],
        stream: bool,
        openid: Optional[str] = None,
        voice_url: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        调用模型 API
        
        Args:
            config: 模型配置，包含 base_url, api_key, model, platform 等
            messages: OpenAI 格式的消息列表
            stream: 是否使用流式响应
            openid: 用户标识（可选）
            voice_url: 语音文件 URL（可选，用于音频理解）
            
        Yields:
            响应事件字典，类型包括：
            - {"type": "text", "content": "..."}
            - {"type": "done"}
            - {"type": "stream_interrupted", "message": "...", "partial_content_length": N}
            - {"type": "transcription", "text": "..."}
            - {"type": "error", "error": "..."}
        """
        pass

    @classmethod
    @abstractmethod
    def supports(cls, platform: str, model: str, has_voice: bool = False) -> bool:
        """
        判断是否支持指定的平台和模型
        
        Args:
            platform: 平台名称（如 openai, gemini, deepseek）
            model: 模型名称
            has_voice: 是否包含语音输入
            
        Returns:
            True 如果支持，否则 False
        """
        pass
    
    @classmethod
    def priority(cls) -> int:
        """
        分发器优先级
        
        数值越大优先级越高。当多个分发器都支持同一请求时，
        选择优先级最高的分发器。
        
        默认优先级为 0，子类可以覆盖此方法。
        
        Returns:
            优先级数值
        """
        return 0
    
    @staticmethod
    def get_dispatcher(platform: str, model: str, has_voice: bool = False) -> "ModelDispatcher":
        """
        根据平台和模型获取对应的分发器（向后兼容方法）
        
        此方法委托给 DispatcherRegistry.get_dispatcher()
        
        Args:
            platform: 平台名称
            model: 模型名称
            has_voice: 是否包含语音
            
        Returns:
            对应的分发器实例
        """
        return DispatcherRegistry.get_dispatcher(platform, model, has_voice)


# ============== 分发器注册表 ==============

class DispatcherRegistry:
    """
    分发器注册表
    
    管理所有可用分发器的注册和获取。
    使用装饰器模式注册分发器，支持优先级排序。
    """
    
    _dispatchers: List[Type[ModelDispatcher]] = []
    
    @classmethod
    def register(cls, dispatcher_class: Type[ModelDispatcher]) -> Type[ModelDispatcher]:
        """
        注册分发器（可用作装饰器）
        
        Example:
            @DispatcherRegistry.register
            class MyDispatcher(ModelDispatcher):
                ...
        
        Args:
            dispatcher_class: 分发器类
            
        Returns:
            原分发器类（便于装饰器使用）
        """
        if dispatcher_class not in cls._dispatchers:
            cls._dispatchers.append(dispatcher_class)
            # 按优先级降序排序
            cls._dispatchers.sort(key=lambda d: d.priority(), reverse=True)
            logger.info(f"[DispatcherRegistry] 注册分发器: {dispatcher_class.__name__}, priority={dispatcher_class.priority()}")
        return dispatcher_class
    
    @classmethod
    def get_dispatcher(
        cls,
        platform: str,
        model: str,
        has_voice: bool = False
    ) -> ModelDispatcher:
        """
        获取匹配的分发器实例
        
        按优先级顺序遍历所有注册的分发器，返回第一个支持的分发器实例。
        
        Args:
            platform: 平台名称
            model: 模型名称
            has_voice: 是否包含语音
            
        Returns:
            匹配的分发器实例
            
        Raises:
            ValueError: 如果没有找到匹配的分发器
        """
        for dispatcher_class in cls._dispatchers:
            if dispatcher_class.supports(platform, model, has_voice):
                logger.info(f"[DispatcherRegistry] 选择分发器: {dispatcher_class.__name__} for {platform}/{model}")
                return dispatcher_class()
        
        raise ValueError(f"No dispatcher found for platform={platform}, model={model}, has_voice={has_voice}")
    
    @classmethod
    def get_all_dispatchers(cls) -> List[Type[ModelDispatcher]]:
        """
        获取所有注册的分发器类
        
        Returns:
            分发器类列表（按优先级降序排列）
        """
        return cls._dispatchers.copy()
    
    @classmethod
    def clear(cls) -> None:
        """
        清空注册表（主要用于测试）
        """
        cls._dispatchers.clear()
