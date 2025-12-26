"""
Gemini 音频理解分发器

支持两种调用方式：
1. 原生 Gemini API: 使用 inline_data 或 file_data 传递音频
2. OpenRouter 代理: 使用 OpenAI 兼容格式，通过 input_audio 传递音频
"""

import json
import logging
from typing import Dict, Any, List, AsyncGenerator, Optional

import httpx

from .base import DispatcherRegistry
from .gemini import GeminiDispatcher
from .utils import AudioUtils, MessageConverter
from ...config import get_http_client_kwargs
from ...utils.error_logger import log_model_error, log_stream_error

logger = logging.getLogger(__name__)


@DispatcherRegistry.register
class GeminiAudioDispatcher(GeminiDispatcher):
    """
    Gemini 音频理解分发器
    
    继承自 GeminiDispatcher，添加音频处理能力。
    优先级高于 GeminiDispatcher，当有语音输入时优先使用。
    """
    
    @classmethod
    def supports(cls, platform: str, model: str, has_voice: bool = False) -> bool:
        """
        判断是否支持
        
        支持 Gemini 模型且有语音输入
        """
        model_lower = model.lower()
        return "gemini" in model_lower and has_voice
    
    @classmethod
    def priority(cls) -> int:
        """音频分发器优先级高于普通 Gemini 分发器"""
        return 20
    
    async def call(
        self,
        config: Dict[str, Any],
        messages: List[Dict],
        stream: bool,
        openid: Optional[str] = None,
        voice_url: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        调用 Gemini API 进行音频理解
        """
        base_url = config["base_url"]
        api_key = config["api_key"]
        model = config["model"]
        platform = config.get("platform", "gemini")
        
        logger.info(f"[GeminiAudioDispatcher] 开始处理音频: voice_url={voice_url[:50] if voice_url else 'None'}...")
        
        if "generativelanguage.googleapis.com" in base_url:
            # 原生 Gemini API
            contents = await self._build_audio_contents(messages, voice_url)
            async for event in self._call_native_gemini(
                base_url, api_key, model, contents, None, stream, openid
            ):
                yield event
        elif "openrouter.ai" in base_url:
            # OpenRouter 代理
            logger.info(f"[GeminiAudioDispatcher] 使用 OpenRouter 音频格式")
            async for event in self._call_openrouter_with_audio(
                config, messages, stream, openid, voice_url
            ):
                yield event
        else:
            # 其他 OpenAI 兼容代理
            logger.info(f"[GeminiAudioDispatcher] 尝试使用 base64 音频格式")
            async for event in self._call_openai_compatible_with_audio(
                config, messages, stream, openid, voice_url
            ):
                yield event

    async def _call_openrouter_with_audio(
        self,
        config: Dict[str, Any],
        messages: List[Dict],
        stream: bool,
        openid: Optional[str] = None,
        voice_url: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        通过 OpenRouter 调用支持音频的模型
        """
        base_url = config["base_url"]
        api_key = config["api_key"]
        model = config["model"]
        platform = config.get("platform", "openrouter")
        
        # 构建包含音频的消息
        audio_messages = MessageConverter.to_openrouter_audio_format(messages, voice_url)
        
        # 调试日志：打印转换后的消息结构
        logger.info(f"[GeminiAudioDispatcher] 原始消息数量: {len(messages)}")
        logger.info(f"[GeminiAudioDispatcher] 转换后消息数量: {len(audio_messages)}")
        for i, msg in enumerate(audio_messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content_types = [item.get("type", "unknown") for item in content]
                logger.info(f"[GeminiAudioDispatcher] 消息[{i}] role={role}, content_types={content_types}")
            else:
                content_preview = content[:100] if isinstance(content, str) else str(content)[:100]
                logger.info(f"[GeminiAudioDispatcher] 消息[{i}] role={role}, content={content_preview}...")
        
        request_body = {
            "model": model,
            "messages": audio_messages,
            "temperature": 0.7,
            "max_tokens": 4000,
            "stream": stream,
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        
        logger.info(f"[GeminiAudioDispatcher] OpenRouter 请求: model={model}, stream={stream}")
        
        if stream:
            async for event in self._stream_openrouter_request(
                base_url, headers, request_body, platform, model, openid
            ):
                yield event
        else:
            result = await self._non_stream_openrouter_request(
                base_url, headers, request_body, platform, model, openid
            )
            yield result
    
    async def _stream_openrouter_request(
        self,
        base_url: str,
        headers: Dict[str, str],
        request_body: Dict[str, Any],
        platform: str,
        model: str,
        openid: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """OpenRouter 流式请求"""
        partial_content_length = 0
        
        try:
            async with httpx.AsyncClient(**get_http_client_kwargs(120.0)) as client:
                async with client.stream(
                    "POST",
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=request_body,
                ) as response:
                    if response.status_code != 200:
                        error_text = ""
                        async for chunk in response.aiter_text():
                            error_text += chunk
                            if len(error_text) > 500:
                                break
                        
                        log_model_error(
                            message=f"OpenRouter 音频 API 错误",
                            platform=platform,
                            model=model,
                            openid=openid,
                            status_code=response.status_code,
                            response_body=error_text,
                        )
                        logger.error(f"[GeminiAudioDispatcher] OpenRouter 错误: {response.status_code}, {error_text[:200]}")
                        raise ValueError(f"OpenRouter API 错误 ({response.status_code})")
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                yield {"type": "done"}
                                break
                            
                            try:
                                data = json.loads(data_str)
                                if data.get("choices") and data["choices"][0].get("delta"):
                                    content = data["choices"][0]["delta"].get("content", "")
                                    if content:
                                        partial_content_length += len(content)
                                        yield {"type": "text", "content": content}
                            except json.JSONDecodeError:
                                continue
                                
        except httpx.ReadTimeout as e:
            log_stream_error(
                message=f"OpenRouter 音频流式响应超时: {e}",
                openid=openid,
                partial_content_length=partial_content_length,
                exception=e,
            )
            if partial_content_length > 0:
                yield {
                    "type": "stream_interrupted",
                    "message": "响应超时，已显示部分内容",
                    "partial_content_length": partial_content_length,
                }
                yield {"type": "done"}
            else:
                raise
                
        except Exception as e:
            logger.error(f"[GeminiAudioDispatcher] OpenRouter 流式请求异常: {e}")
            if partial_content_length > 0:
                yield {
                    "type": "stream_interrupted",
                    "message": "响应异常，已显示部分内容",
                    "partial_content_length": partial_content_length,
                }
                yield {"type": "done"}
            else:
                raise
    
    async def _non_stream_openrouter_request(
        self,
        base_url: str,
        headers: Dict[str, str],
        request_body: Dict[str, Any],
        platform: str,
        model: str,
        openid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """OpenRouter 非流式请求"""
        async with httpx.AsyncClient(**get_http_client_kwargs(120.0)) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=request_body,
            )
            
            if response.status_code != 200:
                error_text = response.text[:500] if response.text else "无响应内容"
                log_model_error(
                    message=f"OpenRouter 音频 API 错误",
                    platform=platform,
                    model=model,
                    openid=openid,
                    status_code=response.status_code,
                    response_body=error_text,
                )
                raise ValueError(f"OpenRouter API 错误 ({response.status_code})")
            
            data = response.json()
            
            if data.get("choices") and data["choices"][0].get("message"):
                content = data["choices"][0]["message"]["content"]
                return {"type": "text", "content": content}
            
            raise ValueError("OpenRouter 返回格式错误")

    async def _call_openai_compatible_with_audio(
        self,
        config: Dict[str, Any],
        messages: List[Dict],
        stream: bool,
        openid: Optional[str] = None,
        voice_url: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        通过其他 OpenAI 兼容代理调用，使用 base64 音频格式
        """
        base_url = config["base_url"]
        api_key = config["api_key"]
        model = config["model"]
        platform = config.get("platform", "unknown")
        
        # 尝试下载音频并转为 base64
        audio_base64 = None
        mime_type = "audio/mp3"
        
        if voice_url:
            try:
                audio_data, mime_type = await AudioUtils.download_audio(voice_url, timeout=30.0)
                audio_base64 = AudioUtils.to_base64(audio_data)
                logger.info(f"[GeminiAudioDispatcher] 音频下载成功: {len(audio_data)} bytes")
            except Exception as e:
                logger.warning(f"[GeminiAudioDispatcher] 音频下载失败: {e}")
        
        # 构建消息，保留完整对话历史
        result_messages = []
        last_user_index = -1
        last_user_text = ""
        
        # 先找到最后一条用户消息
        for i, msg in enumerate(messages):
            if msg.get("role") == "user":
                last_user_index = i
                content = msg.get("content", "")
                if isinstance(content, str):
                    last_user_text = content
                elif isinstance(content, list):
                    for item in content:
                        if item.get("type") == "text":
                            last_user_text = item.get("text", "")
                            break
        
        # 遍历所有消息，保留历史
        for i, msg in enumerate(messages):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "user":
                if i == last_user_index:
                    # 最后一条用户消息：添加音频
                    prompt = last_user_text or "请听取并回复这段语音内容"
                    
                    if audio_base64:
                        user_content = [
                            {"type": "text", "text": prompt},
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": audio_base64,
                                    "format": mime_type.split("/")[-1]
                                }
                            }
                        ]
                        result_messages.append({"role": "user", "content": user_content})
                    else:
                        # 无法获取音频，降级到纯文本
                        logger.warning(f"[GeminiAudioDispatcher] 无法获取音频，降级到文本处理")
                        result_messages.append({"role": "user", "content": f"{prompt}\n\n[注意：语音文件无法访问]"})
                else:
                    # 历史用户消息：保持纯文本
                    text_content = MessageConverter._extract_text_content(content)
                    result_messages.append({"role": "user", "content": text_content})
            else:
                # 非用户消息，保持原样（提取文本）
                text_content = MessageConverter._extract_text_content(content) if isinstance(content, list) else content
                result_messages.append({"role": role, "content": text_content})
        
        # 调用 API
        from .openai_compatible import OpenAICompatibleDispatcher
        dispatcher = OpenAICompatibleDispatcher()
        
        new_config = {**config, "messages": result_messages}
        async for event in dispatcher._stream_request(
            base_url,
            {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            {"model": model, "messages": result_messages, "temperature": 0.7, "max_tokens": 4000, "stream": stream},
            platform, model, openid
        ) if stream else [await dispatcher._non_stream_request(
            base_url,
            {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            {"model": model, "messages": result_messages, "temperature": 0.7, "max_tokens": 4000, "stream": stream},
            platform, model, openid
        )]:
            yield event
    
    async def _build_audio_contents(
        self,
        messages: List[Dict],
        voice_url: str,
    ) -> List[Dict]:
        """
        构建包含音频的 Gemini 请求内容
        """
        contents = []
        system_instruction = None
        user_text = ""
        
        # 提取系统消息和用户文本
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                system_instruction = content
            elif role == "user":
                if isinstance(content, str):
                    user_text = content
                elif isinstance(content, list):
                    for item in content:
                        if item.get("type") == "text":
                            user_text = item.get("text", "")
                            break
        
        # 构建用户消息，包含音频和文本
        parts = []
        
        # 添加音频
        if voice_url:
            mime_type = AudioUtils.get_mime_type(voice_url)
            parts.append({
                "file_data": {
                    "file_uri": voice_url,
                    "mime_type": mime_type,
                }
            })
            logger.info(f"[GeminiAudioDispatcher] 添加音频: mime_type={mime_type}")
        
        # 添加文本提示
        prompt = user_text or "请听取并回复这段语音内容"
        if system_instruction:
            prompt = f"{system_instruction}\n\n用户问题：{prompt}"
        
        parts.append({"text": prompt})
        
        contents.append({
            "role": "user",
            "parts": parts,
        })
        
        return contents
