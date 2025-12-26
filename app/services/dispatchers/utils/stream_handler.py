"""
流式响应处理模块

提供 SSE 流式响应的解析和错误恢复逻辑
支持 OpenAI 和 Gemini 两种 SSE 格式
"""

import json
import logging
from typing import Dict, Any, AsyncGenerator, Optional

import httpx

from ....utils.error_logger import log_model_error, log_stream_error

logger = logging.getLogger(__name__)


class StreamHandler:
    """SSE 流式响应处理器"""
    
    @staticmethod
    async def handle_openai_stream(
        response: httpx.Response,
        openid: Optional[str] = None,
        platform: str = "unknown",
        model: str = "unknown",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理 OpenAI 格式的 SSE 流
        
        OpenAI SSE 格式:
        data: {"choices":[{"delta":{"content":"..."}}]}
        data: [DONE]
        
        Args:
            response: httpx 响应对象
            openid: 用户标识
            platform: 平台名称
            model: 模型名称
            
        Yields:
            响应事件字典
        """
        partial_content_length = 0
        chunk_count = 0
        
        try:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    
                    if data_str == "[DONE]":
                        yield {"type": "done"}
                        break
                    
                    try:
                        data = json.loads(data_str)
                        
                        # 提取内容
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
            yield StreamHandler.handle_stream_error(
                e, partial_content_length, "响应超时"
            )
            
        except Exception as e:
            log_stream_error(
                message=f"流式响应异常: {type(e).__name__}: {e}",
                openid=openid,
                partial_content_length=partial_content_length,
                exception=e,
            )
            yield StreamHandler.handle_stream_error(
                e, partial_content_length, f"响应异常: {type(e).__name__}"
            )

    @staticmethod
    async def handle_gemini_stream(
        response: httpx.Response,
        openid: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理 Gemini 格式的 SSE 流
        
        Gemini SSE 格式:
        data: {"candidates":[{"content":{"parts":[{"text":"..."}]}}]}
        
        Args:
            response: httpx 响应对象
            openid: 用户标识
            
        Yields:
            响应事件字典
        """
        partial_content_length = 0
        
        try:
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
            
        except httpx.ReadTimeout as e:
            logger.error(f"[StreamHandler] Gemini 流式响应超时: {e}")
            yield StreamHandler.handle_stream_error(
                e, partial_content_length, "响应超时"
            )
            
        except Exception as e:
            logger.error(f"[StreamHandler] Gemini 流式响应异常: {e}")
            yield StreamHandler.handle_stream_error(
                e, partial_content_length, f"响应异常: {type(e).__name__}"
            )
    
    @staticmethod
    def handle_stream_error(
        error: Exception,
        partial_content_length: int,
        message: str = "响应异常"
    ) -> Dict[str, Any]:
        """
        处理流式错误，返回中断事件或重新抛出异常
        
        如果已接收到部分内容，返回 stream_interrupted 事件
        否则重新抛出异常
        
        Args:
            error: 异常对象
            partial_content_length: 已接收的内容长度
            message: 错误消息
            
        Returns:
            stream_interrupted 事件字典
            
        Raises:
            Exception: 如果没有部分内容，重新抛出原异常
        """
        if partial_content_length > 0:
            return {
                "type": "stream_interrupted",
                "message": f"{message}，已显示部分内容",
                "partial_content_length": partial_content_length,
            }
        raise error
    
    @staticmethod
    async def check_response_error(
        response: httpx.Response,
        platform: str = "unknown",
        model: str = "unknown",
        openid: Optional[str] = None,
    ) -> None:
        """
        检查响应状态码，如果是错误则抛出异常
        
        Args:
            response: httpx 响应对象
            platform: 平台名称
            model: 模型名称
            openid: 用户标识
            
        Raises:
            ValueError: 如果响应状态码不是 200
        """
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
    
    @staticmethod
    def parse_openai_sse_line(line: str) -> Optional[Dict[str, Any]]:
        """
        解析单行 OpenAI SSE 数据
        
        Args:
            line: SSE 数据行
            
        Returns:
            解析后的数据字典，或 None（如果是 [DONE] 或解析失败）
        """
        if not line.startswith("data: "):
            return None
        
        data_str = line[6:]
        
        if data_str == "[DONE]":
            return None
        
        try:
            return json.loads(data_str)
        except json.JSONDecodeError:
            return None
    
    @staticmethod
    def parse_gemini_sse_line(line: str) -> Optional[Dict[str, Any]]:
        """
        解析单行 Gemini SSE 数据
        
        Args:
            line: SSE 数据行
            
        Returns:
            解析后的数据字典，或 None（如果解析失败）
        """
        if not line.startswith("data: "):
            return None
        
        data_str = line[6:]
        
        try:
            return json.loads(data_str)
        except json.JSONDecodeError:
            return None
    
    @staticmethod
    def extract_openai_content(data: Dict[str, Any]) -> Optional[str]:
        """
        从 OpenAI 响应数据中提取内容
        
        Args:
            data: 解析后的 JSON 数据
            
        Returns:
            内容字符串，或 None
        """
        if data.get("choices") and data["choices"][0].get("delta"):
            return data["choices"][0]["delta"].get("content")
        return None
    
    @staticmethod
    def extract_gemini_content(data: Dict[str, Any]) -> Optional[str]:
        """
        从 Gemini 响应数据中提取内容
        
        Args:
            data: 解析后的 JSON 数据
            
        Returns:
            内容字符串，或 None
        """
        candidates = data.get("candidates", [])
        if candidates:
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            texts = [part.get("text", "") for part in parts if part.get("text")]
            return "".join(texts) if texts else None
        return None
