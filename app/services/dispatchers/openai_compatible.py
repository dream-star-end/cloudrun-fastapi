"""
OpenAI 兼容 API 分发器

支持 DeepSeek、OpenAI、通义千问等 OpenAI 兼容 API
"""

import json
import logging
from typing import Dict, Any, List, AsyncGenerator, Optional

import httpx

from .base import ModelDispatcher, DispatcherRegistry
from .utils import StreamHandler
from ...config import get_http_client_kwargs
from ...utils.error_logger import log_model_error, log_stream_error

logger = logging.getLogger(__name__)


@DispatcherRegistry.register
class OpenAICompatibleDispatcher(ModelDispatcher):
    """
    OpenAI 兼容 API 分发器
    
    支持所有遵循 OpenAI API 规范的模型服务，包括：
    - OpenAI
    - DeepSeek
    - 通义千问
    - 其他兼容服务
    """
    
    @classmethod
    def supports(cls, platform: str, model: str, has_voice: bool = False) -> bool:
        """
        判断是否支持
        
        作为默认分发器，支持所有非 Gemini 的请求
        """
        model_lower = model.lower()
        
        # 不处理 Gemini 模型
        if "gemini" in model_lower:
            return False
        
        # 不处理带语音的 TTS/Whisper 请求
        if has_voice and (model_lower.startswith("tts") or model_lower.startswith("whisper")):
            return False
        
        return True
    
    @classmethod
    def priority(cls) -> int:
        """默认分发器，最低优先级"""
        return 0
    
    async def call(
        self,
        config: Dict[str, Any],
        messages: List[Dict],
        stream: bool,
        openid: Optional[str] = None,
        voice_url: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """调用 OpenAI 兼容 API"""
        base_url = config["base_url"]
        api_key = config["api_key"]
        model = config["model"]
        platform = config.get("platform", "unknown")
        
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
        
        if stream:
            async for event in self._stream_request(
                base_url, headers, request_body,
                platform=platform, model=model, openid=openid
            ):
                yield event
        else:
            result = await self._non_stream_request(
                base_url, headers, request_body,
                platform=platform, model=model, openid=openid
            )
            yield result

    async def _stream_request(
        self,
        base_url: str,
        headers: Dict[str, str],
        request_body: Dict[str, Any],
        platform: str = "unknown",
        model: str = "unknown",
        openid: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式请求"""
        partial_content_length = 0
        chunk_count = 0
        
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
                            message=f"模型 API 错误",
                            platform=platform,
                            model=model,
                            openid=openid,
                            status_code=response.status_code,
                            response_body=error_text,
                        )
                        raise ValueError(f"模型 API 错误 ({response.status_code})")
                    
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
                                        chunk_count += 1
                                        partial_content_length += len(content)
                                        yield {"type": "text", "content": content}
                            except json.JSONDecodeError:
                                continue
                                
        except httpx.ReadTimeout as e:
            log_stream_error(
                message=f"流式响应超时: {e}",
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
    
    async def _non_stream_request(
        self,
        base_url: str,
        headers: Dict[str, str],
        request_body: Dict[str, Any],
        platform: str = "unknown",
        model: str = "unknown",
        openid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """非流式请求"""
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
