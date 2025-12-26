"""
Gemini API 分发器

支持 Google Gemini API（文本/图片）
"""

import json
import logging
from typing import Dict, Any, List, AsyncGenerator, Optional, Tuple

import httpx

from .base import ModelDispatcher, DispatcherRegistry
from .utils import MessageConverter, StreamHandler
from ...config import get_http_client_kwargs

logger = logging.getLogger(__name__)


@DispatcherRegistry.register
class GeminiDispatcher(ModelDispatcher):
    """
    Gemini API 分发器（文本/图片）
    
    支持两种调用方式：
    1. 原生 Gemini API: https://generativelanguage.googleapis.com/v1beta
    2. OpenAI 兼容代理: 直接使用 /chat/completions
    """
    
    @classmethod
    def supports(cls, platform: str, model: str, has_voice: bool = False) -> bool:
        """
        判断是否支持
        
        支持 Gemini 模型（无语音）
        """
        model_lower = model.lower()
        return "gemini" in model_lower and not has_voice
    
    @classmethod
    def priority(cls) -> int:
        """Gemini 分发器优先级"""
        return 10
    
    async def call(
        self,
        config: Dict[str, Any],
        messages: List[Dict],
        stream: bool,
        openid: Optional[str] = None,
        voice_url: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        调用 Gemini API
        
        Gemini API 使用不同的请求格式，需要转换 OpenAI 格式的消息
        """
        base_url = config["base_url"]
        api_key = config["api_key"]
        model = config["model"]
        platform = config.get("platform", "gemini")
        
        # 转换消息格式为 Gemini 格式
        contents, system_instruction = MessageConverter.to_gemini_format(messages)
        
        if "generativelanguage.googleapis.com" in base_url:
            # 原生 Gemini API
            async for event in self._call_native_gemini(
                base_url, api_key, model, contents, system_instruction, stream, openid
            ):
                yield event
        else:
            # OpenAI 兼容代理，使用 OpenAI 分发器逻辑
            from .openai_compatible import OpenAICompatibleDispatcher
            dispatcher = OpenAICompatibleDispatcher()
            async for event in dispatcher.call(config, messages, stream, openid, voice_url):
                yield event

    async def _call_native_gemini(
        self,
        base_url: str,
        api_key: str,
        model: str,
        contents: List[Dict],
        system_instruction: Optional[str],
        stream: bool,
        openid: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """调用原生 Gemini API"""
        # Gemini API 端点
        endpoint = f"{base_url}/models/{model}:{'streamGenerateContent' if stream else 'generateContent'}"
        
        request_body = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 4000,
            },
        }
        
        # 添加系统指令（如果有）
        if system_instruction:
            request_body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
        
        headers = {
            "Content-Type": "application/json",
        }
        
        # Gemini 使用 URL 参数传递 API Key
        url = f"{endpoint}?key={api_key}"
        if stream:
            url += "&alt=sse"
        
        logger.info(f"[GeminiDispatcher] 调用 Gemini API: model={model}, stream={stream}")
        
        if stream:
            async for event in self._stream_gemini_request(url, headers, request_body, openid):
                yield event
        else:
            result = await self._non_stream_gemini_request(url, headers, request_body, openid)
            yield result
    
    async def _stream_gemini_request(
        self,
        url: str,
        headers: Dict[str, str],
        request_body: Dict[str, Any],
        openid: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Gemini 流式请求"""
        partial_content_length = 0
        
        try:
            async with httpx.AsyncClient(**get_http_client_kwargs(120.0)) as client:
                async with client.stream("POST", url, headers=headers, json=request_body) as response:
                    if response.status_code != 200:
                        error_text = ""
                        async for chunk in response.aiter_text():
                            error_text += chunk
                            if len(error_text) > 500:
                                break
                        logger.error(f"[GeminiDispatcher] API 错误: {response.status_code}, {error_text[:200]}")
                        raise ValueError(f"Gemini API 错误 ({response.status_code})")
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            try:
                                data = json.loads(data_str)
                                # Gemini 响应格式
                                candidates = data.get("candidates", [])
                                if candidates:
                                    content = candidates[0].get("content", {})
                                    parts = content.get("parts", [])
                                    for part in parts:
                                        text = part.get("text", "")
                                        if text:
                                            partial_content_length += len(text)
                                            yield {"type": "text", "content": text}
                            except json.JSONDecodeError:
                                continue
                    
                    yield {"type": "done"}
                    
        except Exception as e:
            logger.error(f"[GeminiDispatcher] 流式请求异常: {e}")
            if partial_content_length > 0:
                yield {
                    "type": "stream_interrupted",
                    "message": "响应异常，已显示部分内容",
                    "partial_content_length": partial_content_length,
                }
                yield {"type": "done"}
            else:
                raise
    
    async def _non_stream_gemini_request(
        self,
        url: str,
        headers: Dict[str, str],
        request_body: Dict[str, Any],
        openid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Gemini 非流式请求"""
        async with httpx.AsyncClient(**get_http_client_kwargs(120.0)) as client:
            response = await client.post(url, headers=headers, json=request_body)
            
            if response.status_code != 200:
                logger.error(f"[GeminiDispatcher] API 错误: {response.status_code}, {response.text[:200]}")
                raise ValueError(f"Gemini API 错误 ({response.status_code})")
            
            data = response.json()
            candidates = data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                text_parts = [part.get("text", "") for part in parts if part.get("text")]
                return {"type": "text", "content": "".join(text_parts)}
            
            raise ValueError("Gemini 返回格式错误")
