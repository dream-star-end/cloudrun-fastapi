"""
音频处理工具模块

提供音频下载、格式转换、MIME 类型推断等功能
"""

import base64
import logging
from typing import Tuple, Optional

import httpx

from ....config import get_http_client_kwargs

logger = logging.getLogger(__name__)


class AudioUtils:
    """音频处理工具类"""
    
    # MIME 类型映射（URL 扩展名 -> MIME 类型）
    MIME_TYPE_MAP = {
        ".mp3": "audio/mp3",
        ".wav": "audio/wav",
        ".m4a": "audio/m4a",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".webm": "audio/webm",
    }
    
    # 音频文件签名（文件头 -> MIME 类型）
    AUDIO_SIGNATURES = {
        b'ID3': "audio/mp3",       # MP3 with ID3 tag
        b'\xff\xfb': "audio/mp3",  # MP3 without ID3 (MPEG Audio Layer 3)
        b'\xff\xfa': "audio/mp3",  # MP3 variant
        b'RIFF': "audio/wav",      # WAV
        b'fLaC': "audio/flac",     # FLAC
        b'OggS': "audio/ogg",      # OGG
    }
    
    # 文件名扩展名 -> MIME 类型（用于 multipart 上传）
    EXT_MIME_MAP = {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "m4a": "audio/m4a",
        "webm": "audio/webm",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
        "aac": "audio/aac",
    }

    @classmethod
    async def download_audio(
        cls,
        url: str,
        timeout: float = 30.0
    ) -> Tuple[bytes, str]:
        """
        下载音频文件
        
        Args:
            url: 音频文件 URL
            timeout: 超时时间（秒）
            
        Returns:
            (音频数据, MIME类型)
            
        Raises:
            ValueError: 下载失败时抛出描述性错误
        """
        logger.info(f"[AudioUtils] 下载音频: {url[:50]}...")
        
        try:
            async with httpx.AsyncClient(**get_http_client_kwargs(timeout)) as client:
                response = await client.get(url, follow_redirects=True)
                
                if response.status_code != 200:
                    error_msg = f"下载音频失败: HTTP {response.status_code}"
                    logger.error(f"[AudioUtils] {error_msg}")
                    raise ValueError(error_msg)
                
                data = response.content
                content_type = response.headers.get("content-type", "")
                
                # 推断 MIME 类型
                mime_type = cls.get_mime_type(url, data, content_type)
                
                logger.info(f"[AudioUtils] 下载完成: {len(data)} bytes, mime={mime_type}")
                return data, mime_type
                
        except httpx.TimeoutException as e:
            error_msg = f"下载音频超时: {e}"
            logger.error(f"[AudioUtils] {error_msg}")
            raise ValueError(error_msg)
        except httpx.RequestError as e:
            error_msg = f"下载音频网络错误: {e}"
            logger.error(f"[AudioUtils] {error_msg}")
            raise ValueError(error_msg)
        except ValueError:
            raise
        except Exception as e:
            error_msg = f"下载音频失败: {type(e).__name__}: {e}"
            logger.error(f"[AudioUtils] {error_msg}")
            raise ValueError(error_msg)
    
    @classmethod
    def get_mime_type(
        cls,
        url: str,
        data: Optional[bytes] = None,
        content_type: str = ""
    ) -> str:
        """
        推断音频 MIME 类型
        
        优先级：
        1. URL 扩展名
        2. 文件头签名
        3. Content-Type 头
        4. 默认 audio/mp3
        
        Args:
            url: 音频 URL
            data: 音频数据（可选）
            content_type: HTTP Content-Type 头（可选）
            
        Returns:
            MIME 类型字符串
        """
        url_lower = url.lower()
        
        # 1. 从 URL 扩展名推断
        for ext, mime in cls.MIME_TYPE_MAP.items():
            if ext in url_lower:
                return mime
        
        # 2. 从文件头签名推断
        if data:
            for sig, mime in cls.AUDIO_SIGNATURES.items():
                if data.startswith(sig):
                    return mime
        
        # 3. 从 Content-Type 推断
        if content_type:
            content_type_lower = content_type.lower()
            if "mp3" in content_type_lower or "mpeg" in content_type_lower:
                return "audio/mp3"
            elif "wav" in content_type_lower:
                return "audio/wav"
            elif "m4a" in content_type_lower or "mp4" in content_type_lower:
                return "audio/m4a"
            elif "ogg" in content_type_lower:
                return "audio/ogg"
            elif "flac" in content_type_lower:
                return "audio/flac"
            elif "webm" in content_type_lower:
                return "audio/webm"
        
        # 4. 默认
        return "audio/mp3"
    
    @classmethod
    def to_base64(cls, data: bytes) -> str:
        """
        将音频数据转换为 base64 字符串
        
        Args:
            data: 音频二进制数据
            
        Returns:
            base64 编码的字符串
        """
        return base64.b64encode(data).decode('utf-8')
    
    @classmethod
    def validate_audio(cls, data: bytes) -> bool:
        """
        验证音频数据有效性
        
        检查条件：
        1. 数据长度至少 1000 字节
        2. 文件头匹配已知音频格式
        
        Args:
            data: 音频二进制数据
            
        Returns:
            True 如果数据有效，否则 False
        """
        # 检查最小长度
        if len(data) < 1000:
            return False
        
        # 检查文件头签名
        for sig in cls.AUDIO_SIGNATURES:
            if data.startswith(sig):
                return True
        
        return False
    
    @classmethod
    def get_filename_from_url(cls, url: str, content_type: str = "") -> str:
        """
        从 URL 或 Content-Type 推断文件名
        
        Args:
            url: 音频 URL
            content_type: HTTP Content-Type 头
            
        Returns:
            带扩展名的文件名（如 audio.mp3）
        """
        url_lower = url.lower()
        
        # 从 URL 推断
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
        elif ".aac" in url_lower:
            return "audio.aac"
        
        # 从 Content-Type 推断
        if content_type:
            if "mp3" in content_type or "mpeg" in content_type:
                return "audio.mp3"
            elif "wav" in content_type:
                return "audio.wav"
            elif "m4a" in content_type or "mp4" in content_type:
                return "audio.m4a"
            elif "webm" in content_type:
                return "audio.webm"
            elif "ogg" in content_type:
                return "audio.ogg"
            elif "flac" in content_type:
                return "audio.flac"
        
        # 默认
        return "audio.mp3"
    
    @classmethod
    def get_upload_mime_type(cls, filename: str) -> str:
        """
        根据文件名获取用于上传的 MIME 类型
        
        Args:
            filename: 文件名（如 audio.mp3）
            
        Returns:
            MIME 类型字符串
        """
        ext = filename.split(".")[-1].lower()
        return cls.EXT_MIME_MAP.get(ext, "audio/mpeg")
