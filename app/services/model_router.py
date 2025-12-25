"""
智能模型路由器模块
根据消息类型和用户配置选择合适的 AI 模型

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 9.5
"""

import httpx
import json
import logging
from typing import Optional, Dict, Any, List, AsyncGenerator
from enum import Enum

from ..config import settings, get_http_client_kwargs
from .model_config_service import ModelConfigService
from .ai_service import AIService
from ..utils.error_logger import (
    log_model_error,
    log_config_error,
    log_stream_error,
    set_request_context,
    generate_request_id,
)

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """消息类型枚举"""
    TEXT = "text"
    IMAGE = "image"
    VOICE = "voice"
    MULTIMODAL = "multimodal"  # 文本+图片


class ModelRouter:
    """
    智能模型路由器
    
    根据消息类型和用户配置选择合适的模型：
    - 文本消息 → 文本模型
    - 图片消息 → 视觉/多模态模型
    - 语音消息 → 语音模型（或降级到 ASR + 文本模型）
    - 文本+图片 → 多模态模型
    """
    
    @classmethod
    def detect_message_type(cls, message: Dict[str, Any]) -> MessageType:
        """
        检测消息类型
        
        Args:
            message: 消息字典，可能包含 text, image_url, image_base64, voice_url, voice_text
            
        Returns:
            MessageType 枚举值
        """
        has_text = bool(message.get("text"))
        has_image = bool(message.get("image_url") or message.get("image_base64"))
        has_voice = bool(message.get("voice_url") or message.get("voice_text"))
        
        if has_image and has_text:
            return MessageType.MULTIMODAL
        elif has_image:
            return MessageType.IMAGE
        elif has_voice:
            return MessageType.VOICE
        else:
            return MessageType.TEXT
    
    @classmethod
    async def route_and_call(
        cls,
        openid: str,
        message: Dict[str, Any],
        history: List[Dict] = None,
        context: Optional[Dict] = None,
        stream: bool = True,
        user_memory: Optional[Dict] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        路由并调用合适的模型
        
        Args:
            openid: 用户 openid
            message: 多模态消息
            history: 对话历史
            context: 上下文（如文档伴读的文档内容）
            stream: 是否流式响应
            user_memory: 用户记忆/画像
            
        Yields:
            流式响应事件字典
        """
        history = history or []
        
        # 设置请求上下文用于错误日志
        request_id = generate_request_id()
        set_request_context(request_id=request_id, openid=openid)
        
        # ========== 详细日志：接收到的消息 ==========
        logger.info("=" * 60)
        logger.info(f"[ModelRouter] 🚀 新请求开始")
        logger.info(f"[ModelRouter] request_id: {request_id}")
        logger.info(f"[ModelRouter] openid: {openid[:8]}***")
        logger.info(f"[ModelRouter] stream: {stream}")
        logger.info(f"[ModelRouter] history_count: {len(history)}")
        logger.info(f"[ModelRouter] has_context: {context is not None}")
        logger.info(f"[ModelRouter] has_user_memory: {user_memory is not None}")
        
        # 打印消息内容摘要
        text_content = message.get("text", "")
        logger.info(f"[ModelRouter] 📝 消息内容:")
        logger.info(f"  - text: {text_content[:100]}{'...' if len(text_content) > 100 else ''}" if text_content else "  - text: (无)")
        logger.info(f"  - image_url: {'有' if message.get('image_url') else '无'}")
        logger.info(f"  - image_base64: {'有' if message.get('image_base64') else '无'}")
        logger.info(f"  - voice_url: {'有' if message.get('voice_url') else '无'}")
        logger.info(f"  - voice_text: {'有' if message.get('voice_text') else '无'}")
        
        # 检测消息类型
        msg_type = cls.detect_message_type(message)
        logger.info(f"[ModelRouter] 🔍 检测到消息类型: {msg_type.value}")
        
        # 根据消息类型获取模型配置
        if msg_type == MessageType.TEXT:
            model_type = "text"
        elif msg_type in (MessageType.IMAGE, MessageType.MULTIMODAL):
            model_type = "multimodal"
        elif msg_type == MessageType.VOICE:
            # 语音消息：如果有 voice_text（已转文本），使用文本模型
            # 否则需要语音模型
            if message.get("voice_text"):
                model_type = "text"
                logger.info(f"[ModelRouter] 语音已转文本，使用文本模型")
            else:
                model_type = "voice"
        else:
            model_type = "text"
        
        logger.info(f"[ModelRouter] 📋 需要的模型类型: {model_type}")
        
        # 获取用户配置的模型
        model_config = await ModelConfigService.get_model_for_type(openid, model_type)
        
        # ========== 详细日志：选择的模型 ==========
        logger.info(f"[ModelRouter] ✅ 模型选择结果:")
        logger.info(f"  - platform: {model_config['platform']}")
        logger.info(f"  - model: {model_config['model']}")
        logger.info(f"  - base_url: {model_config['base_url'][:50]}...")
        logger.info(f"  - is_user_config: {model_config.get('is_user_config', False)}")
        logger.info(f"  - api_key: {'已配置' if model_config.get('api_key') else '❌ 未配置'}")
        logger.info("=" * 60)
        
        # 构建消息列表
        messages = cls._build_messages(message, history, context, user_memory, msg_type)
        logger.info(f"[ModelRouter] 📨 构建消息列表完成，共 {len(messages)} 条消息")
        
        # 调用模型（带降级）
        fallback_config = cls._get_fallback_config()
        
        try:
            async for event in cls._call_with_fallback(
                primary_config=model_config,
                fallback_config=fallback_config,
                messages=messages,
                stream=stream,
                msg_type=msg_type,
                openid=openid,
            ):
                yield event
        except Exception as e:
            log_model_error(
                message=f"模型调用最终失败: {type(e).__name__}: {e}",
                platform=model_config.get("platform", "unknown"),
                model=model_config.get("model", "unknown"),
                openid=openid,
                exception=e,
            )
            yield {
                "type": "error",
                "error": str(e),
            }
    
    @classmethod
    async def _call_with_fallback(
        cls,
        primary_config: Dict[str, Any],
        fallback_config: Dict[str, Any],
        messages: List[Dict],
        stream: bool,
        msg_type: MessageType,
        openid: str = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        带降级的模型调用
        
        Args:
            primary_config: 主模型配置
            fallback_config: 降级模型配置
            messages: 消息列表
            stream: 是否流式
            msg_type: 消息类型
            openid: 用户标识（用于错误日志）
            
        Yields:
            流式响应事件
        """
        used_fallback = False
        fallback_reason = None
        
        # 检查主模型配置是否有效
        if not primary_config.get("api_key"):
            logger.warning(f"[ModelRouter] ⚠️ 主模型 API Key 未配置")
            logger.warning(f"  - platform: {primary_config.get('platform')}")
            logger.warning(f"  - model: {primary_config.get('model')}")
            logger.info(f"[ModelRouter] 🔄 切换到降级模型: {fallback_config['platform']}/{fallback_config['model']}")
            
            log_config_error(
                message="主模型 API Key 未配置，使用降级模型",
                openid=openid,
                config_type=msg_type.value,
            )
            used_fallback = True
            fallback_reason = "API Key 未配置"
            primary_config = fallback_config
        
        try:
            # 尝试调用主模型
            async for chunk in cls._call_model(
                config=primary_config,
                messages=messages,
                stream=stream,
                msg_type=msg_type,
                openid=openid,
            ):
                if used_fallback and chunk.get("type") == "text":
                    # 第一个文本块时标记使用了降级
                    chunk["fallback_used"] = True
                    chunk["fallback_reason"] = fallback_reason
                    used_fallback = False  # 只标记一次
                yield chunk
                
        except Exception as e:
            logger.error(f"[ModelRouter] ❌ 主模型调用失败: {type(e).__name__}: {e}")
            
            log_model_error(
                message=f"主模型调用失败: {type(e).__name__}: {e}",
                platform=primary_config.get("platform", "unknown"),
                model=primary_config.get("model", "unknown"),
                openid=openid,
                exception=e,
            )
            
            # 如果主模型就是降级模型，直接抛出错误
            if primary_config.get("platform") == fallback_config.get("platform") and \
               primary_config.get("model") == fallback_config.get("model"):
                logger.error(f"[ModelRouter] ❌ 降级模型也失败，无法继续")
                raise
            
            # 尝试降级模型
            logger.info(f"[ModelRouter] 🔄 尝试降级到: {fallback_config['platform']}/{fallback_config['model']}")
            
            yield {
                "type": "fallback_notice",
                "message": f"您配置的模型暂时不可用，已切换到默认模型",
                "fallback_used": True,
                "fallback_reason": str(e),
            }
            
            async for chunk in cls._call_model(
                config=fallback_config,
                messages=messages,
                stream=stream,
                msg_type=msg_type,
                openid=openid,
            ):
                yield chunk
    
    @classmethod
    async def _call_model(
        cls,
        config: Dict[str, Any],
        messages: List[Dict],
        stream: bool,
        msg_type: MessageType,
        openid: str = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        调用模型 API
        
        Args:
            config: 模型配置
            messages: 消息列表
            stream: 是否流式
            msg_type: 消息类型
            openid: 用户标识（用于错误日志）
            
        Yields:
            流式响应事件
        """
        base_url = config["base_url"]
        api_key = config["api_key"]
        model = config["model"]
        platform = config.get("platform", "unknown")
        
        # ========== 详细日志：API 调用 ==========
        logger.info(f"[ModelRouter] 🌐 开始调用模型 API")
        logger.info(f"  - platform: {platform}")
        logger.info(f"  - model: {model}")
        logger.info(f"  - base_url: {base_url}")
        logger.info(f"  - stream: {stream}")
        logger.info(f"  - messages_count: {len(messages)}")
        
        request_body = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4000,
            "stream": stream,
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        
        # 日志中脱敏显示 API Key
        logger.info(f"[ModelRouter] 📤 发送请求到: {base_url}/chat/completions")
        logger.info(f"  - Authorization: Bearer {api_key[:8]}***" if api_key else "  - Authorization: Bearer (empty)")
        
        if stream:
            async for event in cls._stream_request(
                base_url, headers, request_body, 
                platform=platform, model=model, openid=openid
            ):
                yield event
        else:
            result = await cls._non_stream_request(
                base_url, headers, request_body,
                platform=platform, model=model, openid=openid
            )
            yield result
    
    @classmethod
    async def _stream_request(
        cls,
        base_url: str,
        headers: Dict[str, str],
        request_body: Dict[str, Any],
        platform: str = "unknown",
        model: str = "unknown",
        openid: str = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式请求（带中断处理和部分内容保留）
        
        Requirements: 9.4
        """
        partial_content_length = 0
        chunk_count = 0
        
        try:
            async with httpx.AsyncClient(**get_http_client_kwargs(120.0)) as client:
                logger.info(f"[ModelRouter] 🔗 建立流式连接...")
                
                async with client.stream(
                    "POST",
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=request_body,
                ) as response:
                    logger.info(f"[ModelRouter] 📥 收到响应: status={response.status_code}")
                    
                    if response.status_code != 200:
                        error_text = ""
                        async for chunk in response.aiter_text():
                            error_text += chunk
                            if len(error_text) > 500:
                                break
                        
                        logger.error(f"[ModelRouter] ❌ API 错误: status={response.status_code}")
                        logger.error(f"[ModelRouter] 错误内容: {error_text[:200]}")
                        
                        log_model_error(
                            message=f"模型 API 错误",
                            platform=platform,
                            model=model,
                            openid=openid,
                            status_code=response.status_code,
                            response_body=error_text,
                        )
                        raise ValueError(f"模型 API 错误 ({response.status_code})")
                    
                    logger.info(f"[ModelRouter] ✅ 开始接收流式数据...")
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                logger.info(f"[ModelRouter] 🏁 流式响应完成: 共 {chunk_count} 个数据块, {partial_content_length} 字符")
                                yield {"type": "done"}
                                break
                            
                            try:
                                data = json.loads(data_str)
                                if data.get("choices") and data["choices"][0].get("delta"):
                                    content = data["choices"][0]["delta"].get("content", "")
                                    if content:
                                        chunk_count += 1
                                        partial_content_length += len(content)
                                        
                                        # 每 10 个块打印一次进度
                                        if chunk_count % 10 == 0:
                                            logger.debug(f"[ModelRouter] 📊 进度: {chunk_count} 块, {partial_content_length} 字符")
                                        
                                        yield {"type": "text", "content": content}
                            except json.JSONDecodeError:
                                continue
                                
        except httpx.ReadTimeout as e:
            # 流式读取超时
            logger.error(f"[ModelRouter] ⏰ 流式响应超时: 已接收 {partial_content_length} 字符")
            log_stream_error(
                message=f"流式响应超时: {e}",
                openid=openid,
                partial_content_length=partial_content_length,
                exception=e,
            )
            # 如果已有部分内容，发送中断通知而不是抛出错误
            if partial_content_length > 0:
                yield {
                    "type": "stream_interrupted",
                    "message": "响应超时，已显示部分内容",
                    "partial_content_length": partial_content_length,
                }
                yield {"type": "done"}
            else:
                raise
                
        except httpx.ReadError as e:
            # 流式读取错误（网络中断等）
            logger.error(f"[ModelRouter] 🔌 流式响应中断: 已接收 {partial_content_length} 字符")
            log_stream_error(
                message=f"流式响应中断: {e}",
                openid=openid,
                partial_content_length=partial_content_length,
                exception=e,
            )
            # 如果已有部分内容，发送中断通知
            if partial_content_length > 0:
                yield {
                    "type": "stream_interrupted",
                    "message": "连接中断，已显示部分内容",
                    "partial_content_length": partial_content_length,
                }
                yield {"type": "done"}
            else:
                raise
                
        except Exception as e:
            # 其他异常
            logger.error(f"[ModelRouter] ❌ 流式响应异常: {type(e).__name__}: {e}")
            if partial_content_length > 0:
                log_stream_error(
                    message=f"流式响应异常: {type(e).__name__}: {e}",
                    openid=openid,
                    partial_content_length=partial_content_length,
                    exception=e,
                )
                yield {
                    "type": "stream_interrupted",
                    "message": "响应异常，已显示部分内容",
                    "partial_content_length": partial_content_length,
                }
                yield {"type": "done"}
            else:
                raise
    
    @classmethod
    async def _non_stream_request(
        cls,
        base_url: str,
        headers: Dict[str, str],
        request_body: Dict[str, Any],
        platform: str = "unknown",
        model: str = "unknown",
        openid: str = None,
    ) -> Dict[str, Any]:
        """
        非流式请求
        """
        async with httpx.AsyncClient(**get_http_client_kwargs(120.0)) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=request_body,
            )
            
            if response.status_code != 200:
                error_text = response.text[:500] if response.text else "无响应内容"
                log_model_error(
                    message=f"模型 API 错误",
                    platform=platform,
                    model=model,
                    openid=openid,
                    status_code=response.status_code,
                    response_body=error_text,
                )
                raise ValueError(f"模型 API 错误 ({response.status_code})")
            
            data = response.json()
            
            if data.get("choices") and data["choices"][0].get("message"):
                content = data["choices"][0]["message"]["content"]
                return {"type": "text", "content": content}
            
            raise ValueError("模型返回格式错误")
    
    @classmethod
    def _build_messages(
        cls,
        message: Dict[str, Any],
        history: List[Dict],
        context: Optional[Dict],
        user_memory: Optional[Dict],
        msg_type: MessageType,
    ) -> List[Dict]:
        """
        构建发送给模型的消息列表
        """
        messages = []
        
        # 系统提示词
        system_prompt = AIService.COACH_SYSTEM_PROMPT
        
        # 添加用户记忆
        if user_memory:
            memory_info = AIService._format_user_memory(user_memory)
            if memory_info:
                system_prompt += f"\n\n【用户档案】\n{memory_info}"
        
        # 添加文档上下文
        if context:
            doc_title = context.get("title", "")
            doc_content = context.get("content", "")
            if doc_content:
                system_prompt += f"\n\n【当前文档】\n标题：{doc_title}\n内容：\n{doc_content[:3000]}"
        
        messages.append({"role": "system", "content": system_prompt})
        
        # 添加对话历史
        for msg in history:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })
        
        # 添加当前消息
        current_content = cls._build_current_message_content(message, msg_type)
        messages.append({"role": "user", "content": current_content})
        
        return messages
    
    @classmethod
    def _build_current_message_content(
        cls,
        message: Dict[str, Any],
        msg_type: MessageType,
    ) -> Any:
        """
        构建当前消息内容
        
        对于多模态消息，返回包含文本和图片的列表
        对于纯文本消息，返回字符串
        """
        if msg_type == MessageType.TEXT:
            return message.get("text", "")
        
        elif msg_type == MessageType.VOICE:
            # 语音已转文本
            return message.get("voice_text", message.get("text", ""))
        
        elif msg_type in (MessageType.IMAGE, MessageType.MULTIMODAL):
            # 多模态消息
            content = []
            
            # 添加文本
            text = message.get("text", "")
            if text:
                content.append({"type": "text", "text": text})
            elif msg_type == MessageType.IMAGE:
                # 纯图片消息，添加默认提示
                content.append({"type": "text", "text": "请分析这张图片"})
            
            # 添加图片
            image_url = message.get("image_url")
            image_base64 = message.get("image_base64")
            
            if image_url:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": image_url}
                })
            elif image_base64:
                # Base64 格式
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                })
            
            return content
        
        return message.get("text", "")
    
    @classmethod
    def _get_fallback_config(cls) -> Dict[str, Any]:
        """
        获取降级模型配置（系统默认）
        """
        return {
            "platform": "deepseek",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": settings.DEEPSEEK_API_KEY,
            "is_fallback": True,
        }
