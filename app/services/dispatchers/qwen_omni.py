"""
通义千问全模态分发器

支持 qwen-omni 系列模型的音频/视觉理解能力。
根据阿里云百炼文档，qwen-omni 模型使用 OpenAI 兼容格式，
但音频输入需要通过 input_audio 字段传递 base64 编码的音频数据。

参考文档：https://help.aliyun.com/zh/model-studio/user-guide/omni

支持的模型：
- qwen-omni-turbo
- qwen-omni-turbo-latest
- qwen-omni-turbo-2025-01-19
- qwen2.5-omni-7b
- qwen3-omni-flash-2025-12-01
- 其他 qwen*omni* 模型
"""

import json
import logging
from typing import Dict, Any, List, AsyncGenerator, Optional

import httpx

from .base import ModelDispatcher, DispatcherRegistry
from .utils import AudioUtils, MessageConverter
from ...config import get_http_client_kwargs
from ...utils.error_logger import log_model_error, log_stream_error

logger = logging.getLogger(__name__)


@DispatcherRegistry.register
class QwenOmniDispatcher(ModelDispatcher):
    """
    通义千问全模态分发器
    
    专门处理 qwen-omni 系列模型的音频/视觉输入。
    使用 OpenAI 兼容格式，音频通过 input_audio 字段传递。
    """
    
    # 支持的模型名称模式
    SUPPORTED_MODEL_PATTERNS = [
        "qwen-omni",
        "qwen2.5-omni",
        "qwen3-omni",
        "qwen-audio",
    ]
    
    @classmethod
    def supports(cls, platform: str, model: str, has_voice: bool = False) -> bool:
        """
        判断是否支持
        
        支持通义千问平台的 omni/audio 系列模型
        """
        model_lower = model.lower()
        
        # 检查是否是 qwen 平台或自定义平台使用 qwen omni 模型
        is_qwen_platform = platform.lower() in ["qwen", "dashscope", "aliyun"]
        is_custom_with_qwen = platform.lower().startswith("custom_")
        
        # 检查模型名称是否匹配
        is_omni_model = any(pattern in model_lower for pattern in cls.SUPPORTED_MODEL_PATTERNS)
        
        # qwen 平台的 omni 模型，或者自定义平台使用 omni 模型且有语音
        if is_omni_model:
            if is_qwen_platform:
                return True
            if is_custom_with_qwen and has_voice:
                return True
            # 通过 base_url 判断（在 call 时会检查）
            if has_voice:
                return True
        
        return False
    
    @classmethod
    def priority(cls) -> int:
        """
        优先级高于默认 OpenAI 兼容分发器
        
        当检测到 qwen-omni 模型时，优先使用此分发器
        """
        return 15
    
    async def call(
        self,
        config: Dict[str, Any],
        messages: List[Dict],
        stream: bool,
        openid: Optional[str] = None,
        voice_url: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        调用通义千问全模态 API
        
        根据阿里云百炼文档，音频输入格式：
        {
            "type": "input_audio",
            "input_audio": {
                "data": "<base64_audio_data>",
                "format": "mp3"  # 或 wav, pcm 等
            }
        }
        """
        base_url = config["base_url"]
        api_key = config["api_key"]
        model = config["model"]
        platform = config.get("platform", "qwen")
        
        logger.info(f"[QwenOmniDispatcher] 开始处理: model={model}, has_voice={voice_url is not None}")
        
        # 下载音频并转为 base64
        audio_base64 = None
        audio_format = "mp3"
        
        if voice_url:
            try:
                audio_data, mime_type = await AudioUtils.download_audio(voice_url, timeout=30.0)
                audio_base64 = AudioUtils.to_base64(audio_data)
                audio_format = self._get_audio_format(mime_type, voice_url)
                logger.info(f"[QwenOmniDispatcher] 音频下载成功: {len(audio_data)} bytes, format={audio_format}")
            except Exception as e:
                logger.error(f"[QwenOmniDispatcher] 音频下载失败: {e}")
                yield {"type": "error", "error": f"语音文件下载失败: {e}"}
                return
        
        # 构建包含音频的消息
        audio_messages = self._build_audio_messages(messages, audio_base64, audio_format)
        
        # 构建请求
        request_body = {
            "model": model,
            "messages": audio_messages,
            "stream": stream,
            # qwen-omni 特定参数
            "stream_options": {"include_usage": True} if stream else None,
        }
        
        # 移除 None 值
        request_body = {k: v for k, v in request_body.items() if v is not None}
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        
        logger.info(f"[QwenOmniDispatcher] 发送请求: model={model}, stream={stream}, has_audio={audio_base64 is not None}")
        
        if stream:
            async for event in self._stream_request(
                base_url, headers, request_body, platform, model, openid
            ):
                yield event
        else:
            result = await self._non_stream_request(
                base_url, headers, request_body, platform, model, openid
            )
            yield result
    
    def _get_audio_format(self, mime_type: str, voice_url: str) -> str:
        """
        获取音频格式
        
        通义千问支持的格式：mp3, wav, pcm, opus, flac
        """
        # 从 MIME 类型推断
        mime_to_format = {
            "audio/mpeg": "mp3",
            "audio/mp3": "mp3",
            "audio/wav": "wav",
            "audio/x-wav": "wav",
            "audio/pcm": "pcm",
            "audio/opus": "opus",
            "audio/flac": "flac",
            "audio/ogg": "opus",
        }
        
        if mime_type in mime_to_format:
            return mime_to_format[mime_type]
        
        # 从 URL 后缀推断
        url_lower = voice_url.lower()
        if ".mp3" in url_lower:
            return "mp3"
        elif ".wav" in url_lower:
            return "wav"
        elif ".pcm" in url_lower:
            return "pcm"
        elif ".opus" in url_lower:
            return "opus"
        elif ".flac" in url_lower:
            return "flac"
        
        # 默认 mp3
        return "mp3"
    
    def _build_audio_messages(
        self,
        messages: List[Dict],
        audio_base64: Optional[str],
        audio_format: str,
    ) -> List[Dict]:
        """
        构建包含音频的消息列表
        
        根据阿里云百炼文档格式：
        - 音频通过 input_audio 类型传递
        - 保留完整对话历史
        """
        result_messages = []
        last_user_index = -1
        last_user_text = ""
        
        # 找到最后一条用户消息
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
        
        # 遍历所有消息
        for i, msg in enumerate(messages):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "user" and i == last_user_index and audio_base64:
                # 最后一条用户消息：添加音频
                prompt = last_user_text or "请听取并回复这段语音内容"
                
                user_content = [
                    {"type": "text", "text": prompt},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio_base64,
                            "format": audio_format,
                        }
                    }
                ]
                result_messages.append({"role": "user", "content": user_content})
                logger.info(f"[QwenOmniDispatcher] 添加音频消息: format={audio_format}, text={prompt[:50]}...")
            else:
                # 其他消息：提取纯文本
                text_content = self._extract_text_content(content)
                result_messages.append({"role": role, "content": text_content})
        
        return result_messages
    
    def _extract_text_content(self, content: Any) -> str:
        """提取文本内容"""
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
                elif isinstance(item, str):
                    texts.append(item)
            return " ".join(texts)
        return str(content)
    
    async def _stream_request(
        self,
        base_url: str,
        headers: Dict[str, str],
        request_body: Dict[str, Any],
        platform: str,
        model: str,
        openid: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式请求"""
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
                            message=f"通义千问全模态 API 错误",
                            platform=platform,
                            model=model,
                            openid=openid,
                            status_code=response.status_code,
                            response_body=error_text,
                        )
                        logger.error(f"[QwenOmniDispatcher] API 错误: {response.status_code}, {error_text[:200]}")
                        raise ValueError(f"通义千问 API 错误 ({response.status_code}): {error_text[:100]}")
                    
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
                message=f"通义千问全模态流式响应超时: {e}",
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
            logger.error(f"[QwenOmniDispatcher] 流式请求异常: {type(e).__name__}: {e}")
            if partial_content_length > 0:
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
        platform: str,
        model: str,
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
                    message=f"通义千问全模态 API 错误",
                    platform=platform,
                    model=model,
                    openid=openid,
                    status_code=response.status_code,
                    response_body=error_text,
                )
                raise ValueError(f"通义千问 API 错误 ({response.status_code})")
            
            data = response.json()
            
            if data.get("choices") and data["choices"][0].get("message"):
                content = data["choices"][0]["message"]["content"]
                return {"type": "text", "content": content}
            
            raise ValueError("通义千问返回格式错误")
