"""
模型调用分发器模块
根据不同平台（OpenAI兼容、Gemini等）分发到对应的调用逻辑

采用策略模式，便于扩展新的模型平台
"""

import httpx
import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, AsyncGenerator, Optional

from ..config import get_http_client_kwargs
from ..utils.error_logger import log_model_error, log_stream_error

logger = logging.getLogger(__name__)


class ModelDispatcher(ABC):
    """模型调用分发器基类"""
    
    @abstractmethod
    async def call(
        self,
        config: Dict[str, Any],
        messages: List[Dict],
        stream: bool,
        openid: str = None,
        voice_url: str = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        调用模型
        
        Args:
            config: 模型配置
            messages: 消息列表
            stream: 是否流式
            openid: 用户标识
            voice_url: 语音文件URL（可选，用于音频理解）
            
        Yields:
            流式响应事件
        """
        pass
    
    @staticmethod
    def get_dispatcher(platform: str, model: str, has_voice: bool = False) -> "ModelDispatcher":
        """
        根据平台和模型获取对应的分发器
        
        Args:
            platform: 平台名称
            model: 模型名称
            has_voice: 是否包含语音
            
        Returns:
            对应的分发器实例
        """
        model_lower = model.lower()
        
        # Gemini 模型且有语音输入，使用 Gemini 音频分发器
        if model_lower.startswith("gemini") and has_voice:
            logger.info(f"[Dispatcher] 使用 GeminiAudioDispatcher: model={model}")
            return GeminiAudioDispatcher()
        
        # Gemini 模型（无语音），使用 Gemini 通用分发器
        if model_lower.startswith("gemini"):
            logger.info(f"[Dispatcher] 使用 GeminiDispatcher: model={model}")
            return GeminiDispatcher()
        
        # OpenAI TTS/Whisper 模型且有语音输入，使用 STT 分发器
        # tts-1, tts-1-hd, whisper-1 等
        if has_voice and (model_lower.startswith("tts") or model_lower.startswith("whisper")):
            logger.info(f"[Dispatcher] 使用 OpenAISTTDispatcher: model={model}")
            return OpenAISTTDispatcher()
        
        # 默认使用 OpenAI 兼容分发器
        logger.info(f"[Dispatcher] 使用 OpenAICompatibleDispatcher: platform={platform}, model={model}")
        return OpenAICompatibleDispatcher()


class OpenAICompatibleDispatcher(ModelDispatcher):
    """OpenAI 兼容 API 分发器（DeepSeek、OpenAI、通义千问等）"""
    
    async def call(
        self,
        config: Dict[str, Any],
        messages: List[Dict],
        stream: bool,
        openid: str = None,
        voice_url: str = None,
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
        openid: str = None,
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
        openid: str = None,
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


class GeminiDispatcher(ModelDispatcher):
    """Gemini API 分发器（文本/图片）"""
    
    async def call(
        self,
        config: Dict[str, Any],
        messages: List[Dict],
        stream: bool,
        openid: str = None,
        voice_url: str = None,
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
        contents = self._convert_messages_to_gemini_format(messages)
        
        # Gemini API 端点
        # 支持两种格式：
        # 1. Google AI Studio: https://generativelanguage.googleapis.com/v1beta
        # 2. OpenAI 兼容代理: 直接使用 /chat/completions
        
        if "generativelanguage.googleapis.com" in base_url:
            # 原生 Gemini API
            async for event in self._call_native_gemini(
                base_url, api_key, model, contents, stream, openid
            ):
                yield event
        else:
            # OpenAI 兼容代理，使用父类逻辑
            dispatcher = OpenAICompatibleDispatcher()
            async for event in dispatcher.call(config, messages, stream, openid, voice_url):
                yield event
    
    def _convert_messages_to_gemini_format(self, messages: List[Dict]) -> List[Dict]:
        """
        将 OpenAI 格式消息转换为 Gemini 格式
        
        OpenAI: [{"role": "user", "content": "..."}]
        Gemini: [{"role": "user", "parts": [{"text": "..."}]}]
        """
        contents = []
        system_instruction = None
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            # 系统消息单独处理
            if role == "system":
                system_instruction = content
                continue
            
            # 转换角色名
            gemini_role = "user" if role == "user" else "model"
            
            # 处理内容
            if isinstance(content, str):
                parts = [{"text": content}]
            elif isinstance(content, list):
                # 多模态内容
                parts = []
                for item in content:
                    if item.get("type") == "text":
                        parts.append({"text": item.get("text", "")})
                    elif item.get("type") == "image_url":
                        image_url = item.get("image_url", {}).get("url", "")
                        if image_url.startswith("data:"):
                            # Base64 图片
                            mime_type, base64_data = self._parse_data_url(image_url)
                            parts.append({
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": base64_data,
                                }
                            })
                        else:
                            # URL 图片
                            parts.append({
                                "file_data": {
                                    "file_uri": image_url,
                                    "mime_type": "image/jpeg",
                                }
                            })
            else:
                parts = [{"text": str(content)}]
            
            contents.append({
                "role": gemini_role,
                "parts": parts,
            })
        
        return contents
    
    def _parse_data_url(self, data_url: str) -> tuple:
        """解析 data URL，返回 (mime_type, base64_data)"""
        if data_url.startswith("data:"):
            # data:image/jpeg;base64,xxxxx
            header, data = data_url.split(",", 1)
            mime_type = header.split(";")[0].replace("data:", "")
            return mime_type, data
        return "image/jpeg", data_url
    
    async def _call_native_gemini(
        self,
        base_url: str,
        api_key: str,
        model: str,
        contents: List[Dict],
        stream: bool,
        openid: str = None,
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
        openid: str = None,
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
        openid: str = None,
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


class GeminiAudioDispatcher(GeminiDispatcher):
    """
    Gemini 音频理解分发器
    
    根据 Google Gemini API 文档，支持通过 inline_data 或 file_data 传递音频
    参考: https://ai.google.dev/gemini-api/docs/audio
    """
    
    async def call(
        self,
        config: Dict[str, Any],
        messages: List[Dict],
        stream: bool,
        openid: str = None,
        voice_url: str = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        调用 Gemini API 进行音频理解
        
        Args:
            config: 模型配置
            messages: 消息列表
            stream: 是否流式
            openid: 用户标识
            voice_url: 语音文件URL
        """
        base_url = config["base_url"]
        api_key = config["api_key"]
        model = config["model"]
        
        logger.info(f"[GeminiAudioDispatcher] 开始处理音频: voice_url={voice_url[:50] if voice_url else 'None'}...")
        
        # 构建包含音频的 Gemini 请求
        contents = await self._build_audio_contents(messages, voice_url)
        
        if "generativelanguage.googleapis.com" in base_url:
            # 原生 Gemini API
            async for event in self._call_native_gemini(
                base_url, api_key, model, contents, stream, openid
            ):
                yield event
        else:
            # OpenAI 兼容代理不支持音频，降级到文本处理
            logger.warning(f"[GeminiAudioDispatcher] OpenAI 兼容代理不支持音频，降级到文本处理")
            dispatcher = OpenAICompatibleDispatcher()
            async for event in dispatcher.call(config, messages, stream, openid, voice_url):
                yield event
    
    async def _build_audio_contents(
        self,
        messages: List[Dict],
        voice_url: str,
    ) -> List[Dict]:
        """
        构建包含音频的 Gemini 请求内容
        
        根据 Gemini API 文档，音频可以通过以下方式传递：
        1. inline_data: Base64 编码的音频数据
        2. file_data: 文件 URI（需要先上传到 Gemini Files API）
        
        由于我们的音频是云存储 URL，这里使用 file_data 方式
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
            # 判断音频格式
            mime_type = self._get_audio_mime_type(voice_url)
            
            # 使用 file_data 方式传递音频 URL
            # 注意：Gemini API 支持直接使用 HTTP URL
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
    
    def _get_audio_mime_type(self, url: str) -> str:
        """根据 URL 推断音频 MIME 类型"""
        url_lower = url.lower()
        
        if ".mp3" in url_lower:
            return "audio/mp3"
        elif ".wav" in url_lower:
            return "audio/wav"
        elif ".m4a" in url_lower:
            return "audio/m4a"
        elif ".aac" in url_lower:
            return "audio/aac"
        elif ".ogg" in url_lower:
            return "audio/ogg"
        elif ".flac" in url_lower:
            return "audio/flac"
        else:
            # 默认 MP3
            return "audio/mp3"


class OpenAISTTDispatcher(ModelDispatcher):
    """
    OpenAI 语音转文本分发器
    
    流程：
    1. 调用 /audio/transcriptions 接口将语音转为文本
    2. 再调用文本模型处理转换后的文本
    
    支持的模型：tts-1, tts-1-hd, whisper-1 等
    参考: https://platform.openai.com/docs/api-reference/audio/createTranscription
    """
    
    async def call(
        self,
        config: Dict[str, Any],
        messages: List[Dict],
        stream: bool,
        openid: str = None,
        voice_url: str = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        调用 OpenAI STT API 进行语音转文本，然后调用文本模型
        
        Args:
            config: 模型配置（语音模型配置）
            messages: 消息列表
            stream: 是否流式
            openid: 用户标识
            voice_url: 语音文件URL
        """
        base_url = config["base_url"]
        api_key = config["api_key"]
        stt_model = config["model"]  # tts-1, whisper-1 等
        
        logger.info(f"[OpenAISTTDispatcher] 开始处理语音: voice_url={voice_url[:50] if voice_url else 'None'}...")
        logger.info(f"[OpenAISTTDispatcher] STT 模型: {stt_model}")
        
        if not voice_url:
            logger.warning(f"[OpenAISTTDispatcher] 没有语音URL，降级到文本处理")
            dispatcher = OpenAICompatibleDispatcher()
            async for event in dispatcher.call(config, messages, stream, openid, voice_url):
                yield event
            return
        
        # Step 1: 语音转文本
        try:
            transcribed_text = await self._transcribe_audio(
                base_url=base_url,
                api_key=api_key,
                model=stt_model,
                voice_url=voice_url,
                openid=openid,
            )
            logger.info(f"[OpenAISTTDispatcher] 语音转文本成功: {transcribed_text[:100]}...")
            
            # 发送转录通知
            yield {
                "type": "transcription",
                "text": transcribed_text,
            }
            
        except Exception as e:
            logger.error(f"[OpenAISTTDispatcher] 语音转文本失败: {e}")
            yield {
                "type": "error",
                "error": f"语音转文本失败: {str(e)}",
            }
            return
        
        # Step 2: 用转录文本替换消息中的语音内容，调用文本模型
        text_messages = self._build_text_messages(messages, transcribed_text)
        
        # 获取文本模型配置（使用默认的 DeepSeek）
        from ..config import settings
        text_config = {
            "platform": "deepseek",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": settings.DEEPSEEK_API_KEY,
        }
        
        logger.info(f"[OpenAISTTDispatcher] 调用文本模型: {text_config['model']}")
        
        # 调用文本模型
        dispatcher = OpenAICompatibleDispatcher()
        async for event in dispatcher.call(text_config, text_messages, stream, openid, None):
            yield event
    
    async def _transcribe_audio(
        self,
        base_url: str,
        api_key: str,
        model: str,
        voice_url: str,
        openid: str = None,
    ) -> str:
        """
        调用 OpenAI 语音转文本 API
        
        Args:
            base_url: API 基础 URL
            api_key: API Key
            model: STT 模型名称
            voice_url: 语音文件 URL
            openid: 用户标识
            
        Returns:
            转录的文本
        """
        # 先下载音频文件
        logger.info(f"[OpenAISTTDispatcher] 下载音频文件: {voice_url[:80]}...")
        
        async with httpx.AsyncClient(**get_http_client_kwargs(60.0)) as client:
            # 下载音频
            audio_response = await client.get(voice_url)
            if audio_response.status_code != 200:
                raise ValueError(f"下载音频失败: HTTP {audio_response.status_code}")
            
            audio_data = audio_response.content
            logger.info(f"[OpenAISTTDispatcher] 音频下载完成: {len(audio_data)} bytes")
            
            # 推断文件格式
            content_type = audio_response.headers.get("content-type", "")
            filename = self._get_filename_from_url(voice_url, content_type)
            
            # 调用 STT API
            # 使用 multipart/form-data 格式
            transcription_url = f"{base_url}/audio/transcriptions"
            
            headers = {
                "Authorization": f"Bearer {api_key}",
            }
            
            # 构建 multipart 表单
            files = {
                "file": (filename, audio_data, self._get_mime_type(filename)),
            }
            data = {
                "model": model if model.startswith("whisper") else "whisper-1",  # STT 只支持 whisper 模型
            }
            
            logger.info(f"[OpenAISTTDispatcher] 调用 STT API: {transcription_url}")
            logger.info(f"[OpenAISTTDispatcher] 文件名: {filename}, 模型: {data['model']}")
            
            response = await client.post(
                transcription_url,
                headers=headers,
                files=files,
                data=data,
            )
            
            if response.status_code != 200:
                error_text = response.text[:500] if response.text else "无响应内容"
                logger.error(f"[OpenAISTTDispatcher] STT API 错误: {response.status_code}, {error_text}")
                log_model_error(
                    message=f"STT API 错误",
                    platform="openai",
                    model=model,
                    openid=openid,
                    status_code=response.status_code,
                    response_body=error_text,
                )
                raise ValueError(f"STT API 错误 ({response.status_code}): {error_text[:100]}")
            
            result = response.json()
            return result.get("text", "")
    
    def _get_filename_from_url(self, url: str, content_type: str = "") -> str:
        """从 URL 或 Content-Type 推断文件名"""
        url_lower = url.lower()
        
        if ".mp3" in url_lower:
            return "audio.mp3"
        elif ".wav" in url_lower:
            return "audio.wav"
        elif ".m4a" in url_lower:
            return "audio.m4a"
        elif ".webm" in url_lower:
            return "audio.webm"
        elif ".ogg" in url_lower:
            return "audio.ogg"
        elif ".flac" in url_lower:
            return "audio.flac"
        elif "mp3" in content_type:
            return "audio.mp3"
        elif "wav" in content_type:
            return "audio.wav"
        elif "m4a" in content_type or "mp4" in content_type:
            return "audio.m4a"
        else:
            # 默认 mp3
            return "audio.mp3"
    
    def _get_mime_type(self, filename: str) -> str:
        """根据文件名获取 MIME 类型"""
        ext = filename.split(".")[-1].lower()
        mime_map = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "m4a": "audio/m4a",
            "webm": "audio/webm",
            "ogg": "audio/ogg",
            "flac": "audio/flac",
        }
        return mime_map.get(ext, "audio/mpeg")
    
    def _build_text_messages(
        self,
        messages: List[Dict],
        transcribed_text: str,
    ) -> List[Dict]:
        """
        用转录文本构建新的消息列表
        
        将原消息中的语音相关内容替换为转录文本
        """
        new_messages = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "user":
                # 用户消息：用转录文本替换
                if isinstance(content, str):
                    # 如果原内容为空或是占位符，使用转录文本
                    if not content or content in ["请听取并回复这段语音内容", ""]:
                        new_messages.append({"role": "user", "content": transcribed_text})
                    else:
                        # 保留原文本，追加转录内容
                        new_messages.append({"role": "user", "content": f"{content}\n\n[语音内容]: {transcribed_text}"})
                elif isinstance(content, list):
                    # 多模态内容，提取文本部分
                    text_parts = []
                    for item in content:
                        if item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                    
                    combined_text = " ".join(text_parts).strip()
                    if combined_text:
                        new_messages.append({"role": "user", "content": f"{combined_text}\n\n[语音内容]: {transcribed_text}"})
                    else:
                        new_messages.append({"role": "user", "content": transcribed_text})
                else:
                    new_messages.append({"role": "user", "content": transcribed_text})
            else:
                # 非用户消息，保持原样
                new_messages.append({"role": role, "content": content})
        
        return new_messages
