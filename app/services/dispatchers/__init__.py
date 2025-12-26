"""
模型调用分发器包

将原 model_dispatchers.py 模块化拆分为多个职责清晰的模块：
- base.py: 基类和注册表
- openai_compatible.py: OpenAI 兼容分发器
- gemini.py: Gemini 分发器
- gemini_audio.py: Gemini 音频分发器
- openai_stt.py: OpenAI STT 分发器
- utils/: 工具模块
"""

# 基类和注册表
from .base import (
    ModelDispatcher,
    DispatcherRegistry,
    TextEvent,
    DoneEvent,
    StreamInterruptedEvent,
    TranscriptionEvent,
    ErrorEvent,
    ResponseEvent,
)

# 分发器实现
from .openai_compatible import OpenAICompatibleDispatcher
from .gemini import GeminiDispatcher
from .gemini_audio import GeminiAudioDispatcher
from .openai_stt import OpenAISTTDispatcher

# 工具类
from .utils import (
    AudioUtils,
    MessageConverter,
    StreamHandler,
)


def get_dispatcher(platform: str, model: str, has_voice: bool = False) -> ModelDispatcher:
    """
    便捷函数：获取匹配的分发器实例
    
    Args:
        platform: 平台名称
        model: 模型名称
        has_voice: 是否包含语音
        
    Returns:
        匹配的分发器实例
    """
    return DispatcherRegistry.get_dispatcher(platform, model, has_voice)


__all__ = [
    # 基类和注册表
    "ModelDispatcher",
    "DispatcherRegistry",
    # 事件类型
    "TextEvent",
    "DoneEvent",
    "StreamInterruptedEvent",
    "TranscriptionEvent",
    "ErrorEvent",
    "ResponseEvent",
    # 分发器
    "OpenAICompatibleDispatcher",
    "GeminiDispatcher",
    "GeminiAudioDispatcher",
    "OpenAISTTDispatcher",
    # 工具类
    "AudioUtils",
    "MessageConverter",
    "StreamHandler",
    # 便捷函数
    "get_dispatcher",
]
