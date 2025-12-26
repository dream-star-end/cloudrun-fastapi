"""
OpenAI 语音转文本分发器

流程：
1. 调用 /audio/transcriptions 接口将语音转为文本
2. 再调用文本模型处理转换后的文本
"""

import logging
from typing import Dict, Any, List, AsyncGenerator, Optional

import httpx

from .base import ModelDispatcher, DispatcherRegistry
from .utils import AudioUtils, MessageConverter
from ...config import get_http_client_kwargs, settings
from ...utils.error_logger import log_model_error

logger = logging.getLogger(__name__)


@DispatcherRegistry.register
class OpenAISTTDispatcher(ModelDispatcher):
    """
    OpenAI 语音转文本分发器
    
    支持的模型：tts-1, tts-1-hd, whisper-1 等
    """
    
    @classmethod
    def supports(cls, platform: str, model: str, has_voice: bool = False) -> bool:
        """
        判断是否支持
        
        支持带语音的 TTS/Whisper 请求
        """
        model_lower = model.lower()
        return has_voice and (model_lower.startswith("tts") or model_lower.startswith("whisper"))
    
    @classmethod
    def priority(cls) -> int:
        """STT 分发器优先级"""
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
        调用 OpenAI STT API 进行语音转文本，然后调用文本模型
        """
        base_url = config["base_url"]
        api_key = config["api_key"]
        stt_model = config["model"]
        
        logger.info(f"[OpenAISTTDispatcher] 开始处理语音: voice_url={voice_url[:50] if voice_url else 'None'}...")
        logger.info(f"[OpenAISTTDispatcher] STT 模型: {stt_model}")
        
        if not voice_url:
            logger.warning(f"[OpenAISTTDispatcher] 没有语音URL，降级到文本处理")
            from .openai_compatible import OpenAICompatibleDispatcher
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
            logger.info(f"[OpenAISTTDispatcher] 语音转文本成功: {transcribed_text[:100] if transcribed_text else '(空)'}...")
            
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
        text_messages = MessageConverter.build_text_messages_from_transcription(messages, transcribed_text)
        
        # 获取文本模型配置
        # 注意：这里需要从用户配置获取，但 STT 分发器没有 openid 上下文
        # 暂时使用系统默认配置（无 API Key），调用方需要确保传入有效配置
        from ..model_config_service import ModelConfigService
        
        # 尝试从用户配置获取文本模型
        if openid:
            try:
                text_config = await ModelConfigService.get_model_for_type(openid, "text")
                logger.info(f"[OpenAISTTDispatcher] 使用用户配置的文本模型: {text_config.get('model')}")
            except Exception as e:
                logger.warning(f"[OpenAISTTDispatcher] 获取用户配置失败，使用默认配置: {e}")
                text_config = {
                    "platform": "deepseek",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key": "",  # 需要用户配置
                }
        else:
            text_config = {
                "platform": "deepseek",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "",  # 需要用户配置
            }
        
        logger.info(f"[OpenAISTTDispatcher] 调用文本模型: {text_config['model']}")
        
        # 调用文本模型
        from .openai_compatible import OpenAICompatibleDispatcher
        dispatcher = OpenAICompatibleDispatcher()
        async for event in dispatcher.call(text_config, text_messages, stream, openid, None):
            yield event

    async def _transcribe_audio(
        self,
        base_url: str,
        api_key: str,
        model: str,
        voice_url: str,
        openid: Optional[str] = None,
    ) -> str:
        """
        调用 OpenAI 语音转文本 API
        """
        logger.info(f"[OpenAISTTDispatcher] 下载音频文件: {voice_url}")
        
        async with httpx.AsyncClient(**get_http_client_kwargs(60.0)) as client:
            # 下载音频
            try:
                audio_response = await client.get(voice_url, follow_redirects=True)
            except Exception as e:
                logger.error(f"[OpenAISTTDispatcher] 下载音频异常: {e}")
                raise ValueError(f"下载音频失败: {str(e)}")
            
            if audio_response.status_code != 200:
                logger.error(f"[OpenAISTTDispatcher] 下载音频失败: HTTP {audio_response.status_code}")
                raise ValueError(f"下载音频失败: HTTP {audio_response.status_code}")
            
            audio_data = audio_response.content
            content_type = audio_response.headers.get("content-type", "")
            
            logger.info(f"[OpenAISTTDispatcher] 音频下载完成:")
            logger.info(f"  - 大小: {len(audio_data)} bytes")
            logger.info(f"  - Content-Type: {content_type}")
            
            # 验证音频数据
            if not AudioUtils.validate_audio(audio_data):
                if len(audio_data) < 1000:
                    logger.error(f"[OpenAISTTDispatcher] 音频文件太小: {len(audio_data)} bytes")
                    raise ValueError(f"音频文件太小或无效: {len(audio_data)} bytes")
                else:
                    logger.warning(f"[OpenAISTTDispatcher] 音频文件头不匹配常见格式: {audio_data[:10].hex()}")
            
            # 推断文件格式
            filename = AudioUtils.get_filename_from_url(voice_url, content_type)
            mime_type = AudioUtils.get_upload_mime_type(filename)
            
            # 调用 STT API
            transcription_url = f"{base_url}/audio/transcriptions"
            
            headers = {
                "Authorization": f"Bearer {api_key}",
            }
            
            # 使用正确的 whisper 模型名称
            stt_model_name = "whisper-1"
            
            files = {
                "file": (filename, audio_data, mime_type),
            }
            data = {
                "model": stt_model_name,
            }
            
            logger.info(f"[OpenAISTTDispatcher] 调用 STT API:")
            logger.info(f"  - URL: {transcription_url}")
            logger.info(f"  - 文件名: {filename}")
            logger.info(f"  - MIME: {mime_type}")
            logger.info(f"  - 模型: {stt_model_name}")
            
            try:
                response = await client.post(
                    transcription_url,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=60.0,
                )
            except Exception as e:
                logger.error(f"[OpenAISTTDispatcher] STT API 请求异常: {e}")
                raise ValueError(f"STT API 请求失败: {str(e)}")
            
            logger.info(f"[OpenAISTTDispatcher] STT API 响应: status={response.status_code}")
            
            if response.status_code != 200:
                error_text = response.text[:500] if response.text else "无响应内容"
                logger.error(f"[OpenAISTTDispatcher] STT API 错误: {response.status_code}")
                logger.error(f"[OpenAISTTDispatcher] 错误详情: {error_text}")
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
            text = result.get("text", "")
            
            if not text:
                logger.warning(f"[OpenAISTTDispatcher] STT 返回空文本，响应: {result}")
            else:
                logger.info(f"[OpenAISTTDispatcher] 转录成功: {text[:50]}...")
            
            return text
