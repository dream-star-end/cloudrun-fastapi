"""
消息格式转换模块

在不同 API 格式之间转换消息：
- OpenAI 格式 <-> Gemini 格式
- OpenAI 格式 -> OpenRouter 音频格式
"""

import logging
from typing import Dict, List, Tuple, Optional, Any

logger = logging.getLogger(__name__)


class MessageConverter:
    """消息格式转换器"""
    
    @classmethod
    def to_gemini_format(
        cls,
        messages: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        将 OpenAI 格式消息转换为 Gemini 格式
        
        OpenAI 格式:
        [{"role": "user", "content": "..."}]
        
        Gemini 格式:
        [{"role": "user", "parts": [{"text": "..."}]}]
        
        Args:
            messages: OpenAI 格式的消息列表
            
        Returns:
            (Gemini 格式的 contents 列表, 系统指令字符串或 None)
        """
        contents = []
        system_instruction = None
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            # 系统消息单独提取
            if role == "system":
                system_instruction = cls._extract_text_content(content)
                continue
            
            # 转换角色名
            gemini_role = "user" if role == "user" else "model"
            
            # 转换内容为 parts 格式
            parts = cls._convert_content_to_parts(content)
            
            contents.append({
                "role": gemini_role,
                "parts": parts,
            })
        
        return contents, system_instruction
    
    @classmethod
    def _convert_content_to_parts(cls, content: Any) -> List[Dict[str, Any]]:
        """
        将内容转换为 Gemini parts 格式
        
        Args:
            content: 消息内容（字符串或多模态列表）
            
        Returns:
            Gemini parts 列表
        """
        if isinstance(content, str):
            return [{"text": content}]
        
        if isinstance(content, list):
            parts = []
            for item in content:
                item_type = item.get("type", "")
                
                if item_type == "text":
                    parts.append({"text": item.get("text", "")})
                    
                elif item_type == "image_url":
                    image_part = cls._convert_image_item(item)
                    if image_part:
                        parts.append(image_part)
                        
                elif item_type == "input_audio":
                    audio_part = cls._convert_audio_item(item)
                    if audio_part:
                        parts.append(audio_part)
            
            return parts if parts else [{"text": ""}]
        
        # 其他类型转为字符串
        return [{"text": str(content)}]

    @classmethod
    def _convert_image_item(cls, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        转换图片项为 Gemini 格式
        
        Args:
            item: OpenAI 格式的图片项
            
        Returns:
            Gemini 格式的图片 part，或 None
        """
        image_url = item.get("image_url", {})
        if isinstance(image_url, str):
            url = image_url
        else:
            url = image_url.get("url", "")
        
        if not url:
            return None
        
        if url.startswith("data:"):
            # Base64 图片
            mime_type, base64_data = cls._parse_data_url(url)
            return {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64_data,
                }
            }
        else:
            # URL 图片
            return {
                "file_data": {
                    "file_uri": url,
                    "mime_type": "image/jpeg",
                }
            }
    
    @classmethod
    def _convert_audio_item(cls, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        转换音频项为 Gemini 格式
        
        Args:
            item: OpenAI 格式的音频项
            
        Returns:
            Gemini 格式的音频 part，或 None
        """
        input_audio = item.get("input_audio", {})
        
        # URL 格式
        url = input_audio.get("url", "")
        if url:
            mime_type = cls._get_audio_mime_type(url)
            return {
                "file_data": {
                    "file_uri": url,
                    "mime_type": mime_type,
                }
            }
        
        # Base64 格式
        data = input_audio.get("data", "")
        format_type = input_audio.get("format", "mp3")
        if data:
            return {
                "inline_data": {
                    "mime_type": f"audio/{format_type}",
                    "data": data,
                }
            }
        
        return None
    
    @classmethod
    def _parse_data_url(cls, data_url: str) -> Tuple[str, str]:
        """
        解析 data URL
        
        Args:
            data_url: data:image/jpeg;base64,xxxxx 格式的 URL
            
        Returns:
            (mime_type, base64_data)
        """
        if data_url.startswith("data:"):
            try:
                header, data = data_url.split(",", 1)
                mime_type = header.split(";")[0].replace("data:", "")
                return mime_type, data
            except ValueError:
                pass
        
        return "image/jpeg", data_url
    
    @classmethod
    def _get_audio_mime_type(cls, url: str) -> str:
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
            return "audio/mp3"
    
    @classmethod
    def to_openrouter_audio_format(
        cls,
        messages: List[Dict[str, Any]],
        voice_url: str
    ) -> List[Dict[str, Any]]:
        """
        构建 OpenRouter 音频格式消息
        
        OpenRouter 音频格式：
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "请听取并回复这段语音"},
                {"type": "input_audio", "input_audio": {"url": "https://..."}}
            ]
        }
        
        Args:
            messages: 原始消息列表
            voice_url: 语音文件 URL
            
        Returns:
            OpenRouter 格式的消息列表
        """
        result = []
        user_text = ""
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                # 系统消息保持不变
                result.append({"role": "system", "content": content})
            elif role == "user":
                # 提取用户文本
                user_text = cls._extract_text_content(content)
            else:
                # assistant 等其他角色消息保持不变
                result.append({"role": role, "content": content})
        
        # 构建包含音频的用户消息
        prompt = user_text or "请听取并回复这段语音内容"
        user_content = [
            {"type": "text", "text": prompt},
        ]
        
        if voice_url:
            user_content.append({
                "type": "input_audio",
                "input_audio": {"url": voice_url}
            })
        
        result.append({"role": "user", "content": user_content})
        
        return result
    
    @classmethod
    def extract_system_instruction(
        cls,
        messages: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        从消息列表中提取系统指令
        
        Args:
            messages: 消息列表
            
        Returns:
            系统指令字符串，如果没有则返回 None
        """
        for msg in messages:
            if msg.get("role") == "system":
                return cls._extract_text_content(msg.get("content", ""))
        return None
    
    @classmethod
    def _extract_text_content(cls, content: Any) -> str:
        """
        从内容中提取文本
        
        Args:
            content: 消息内容（字符串或多模态列表）
            
        Returns:
            提取的文本字符串
        """
        if isinstance(content, str):
            return content
        
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            return " ".join(text_parts).strip()
        
        return str(content) if content else ""
    
    @classmethod
    def build_text_messages_from_transcription(
        cls,
        messages: List[Dict[str, Any]],
        transcribed_text: str
    ) -> List[Dict[str, Any]]:
        """
        用转录文本构建新的消息列表
        
        将原消息中的语音相关内容替换为转录文本
        
        Args:
            messages: 原始消息列表
            transcribed_text: 语音转录文本
            
        Returns:
            新的消息列表
        """
        new_messages = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "user":
                # 用户消息：用转录文本替换
                original_text = cls._extract_text_content(content)
                
                if not original_text or original_text in ["请听取并回复这段语音内容", ""]:
                    # 原内容为空或是占位符，使用转录文本
                    new_messages.append({"role": "user", "content": transcribed_text})
                else:
                    # 保留原文本，追加转录内容
                    new_messages.append({
                        "role": "user",
                        "content": f"{original_text}\n\n[语音内容]: {transcribed_text}"
                    })
            else:
                # 非用户消息，保持原样
                new_messages.append({"role": role, "content": content})
        
        return new_messages
