"""
模型调用分发器模块（向后兼容层）

此文件保留以维持向后兼容性。
所有类和函数已迁移到 dispatchers/ 包中。

新代码应直接从 dispatchers 包导入：
    from app.services.dispatchers import ModelDispatcher, get_dispatcher
"""

# 从新包重新导出所有公共接口
from .dispatchers import (
    # 基类和注册表
    ModelDispatcher,
    DispatcherRegistry,
    # 事件类型
    TextEvent,
    DoneEvent,
    StreamInterruptedEvent,
    TranscriptionEvent,
    ErrorEvent,
    ResponseEvent,
    # 分发器
    OpenAICompatibleDispatcher,
    GeminiDispatcher,
    GeminiAudioDispatcher,
    OpenAISTTDispatcher,
    # 工具类
    AudioUtils,
    MessageConverter,
    StreamHandler,
    # 便捷函数
    get_dispatcher,
)


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
