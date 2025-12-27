"""
自定义 Qwen-Omni Chat 模型
支持音频输入的多模态对话

特点：
- 继承 LangChain BaseChatModel，可与 LangGraph Agent 无缝集成
- 支持音频输入（通过 input_audio 内容类型）
- 支持流式输出（必须使用流式模式）
- 兼容 DashScope OpenAI 兼容 API
"""

import json
import logging
import base64
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

import httpx
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

logger = logging.getLogger(__name__)


class ChatQwenOmni(BaseChatModel):
    """
    自定义 Qwen-Omni Chat 模型
    
    支持音频输入，通过 DashScope OpenAI 兼容 API
    
    使用示例：
    ```python
    llm = ChatQwenOmni(
        model="qwen3-omni-flash",
        api_key="your-api-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=0.7,
    )
    
    # 纯文本对话
    response = llm.invoke([HumanMessage(content="Hello")])
    
    # 带音频的对话（通过多模态内容传递）
    response = llm.invoke([
        HumanMessage(content=[
            {"type": "text", "text": "这段音频在说什么"},
            {"type": "input_audio", "input_audio": {"data": base64_audio, "format": "mp3"}}
        ])
    ])
    ```
    """
    
    model: str = Field(default="qwen3-omni-flash", description="模型名称")
    api_key: str = Field(default="", description="API Key")
    base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="API Base URL"
    )
    temperature: float = Field(default=0.7, description="温度参数")
    max_tokens: Optional[int] = Field(default=None, description="最大输出 token 数")
    timeout: float = Field(default=120.0, description="请求超时时间（秒）")
    streaming: bool = Field(default=True, description="是否启用流式输出")
    
    class Config:
        arbitrary_types_allowed = True
    
    @property
    def _llm_type(self) -> str:
        return "qwen-omni"
    
    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
        }

    def _get_api_url(self) -> str:
        """构建 API URL"""
        base = self.base_url.rstrip('/')
        return f"{base}/chat/completions"
    
    def _convert_messages_to_qwen_format(
        self,
        messages: List[BaseMessage],
    ) -> List[Dict[str, Any]]:
        """
        将 LangChain 消息转换为 Qwen OpenAI 兼容格式
        
        特别处理音频数据：需要添加 data:;base64, 前缀
        """
        result = []
        
        logger.info(f"[ChatQwenOmni] 转换消息: 共 {len(messages)} 条消息")
        
        for msg in messages:
            if isinstance(msg, SystemMessage):
                result.append({
                    "role": "system",
                    "content": msg.content,
                })
            elif isinstance(msg, HumanMessage):
                # 处理内容
                logger.info(f"[ChatQwenOmni] HumanMessage 内容类型: {type(msg.content).__name__}")
                if isinstance(msg.content, str):
                    result.append({
                        "role": "user",
                        "content": msg.content,
                    })
                elif isinstance(msg.content, list):
                    # 多模态内容列表
                    logger.info(f"[ChatQwenOmni] HumanMessage 列表内容: {len(msg.content)} 项")
                    for idx, item in enumerate(msg.content):
                        item_type = type(item).__name__
                        item_content_type = item.get("type") if isinstance(item, dict) else "N/A"
                        logger.info(f"[ChatQwenOmni] - 项 {idx}: 类型={item_type}, content_type={item_content_type}")
                    
                    content_parts = []
                    for item in msg.content:
                        if isinstance(item, str):
                            content_parts.append({"type": "text", "text": item})
                        elif isinstance(item, dict):
                            if item.get("type") == "text":
                                content_parts.append({"type": "text", "text": item.get("text", "")})
                            elif item.get("type") in ("input_audio", "audio"):
                                # 处理音频输入 - 支持多种格式
                                item_type = item.get("type")
                                item_keys = list(item.keys())
                                logger.info(f"[ChatQwenOmni] 音频 item 键: {item_keys}")
                                
                                # 尝试从多种可能的字段获取数据
                                # 格式1: {"type": "input_audio", "input_audio": {"data": "...", "format": "..."}}
                                # 格式2: {"type": "audio", "audio": {"data": "...", "format": "..."}}
                                # 格式3: {"type": "audio", "base64": "...", "mime_type": "..."}
                                # 格式4: {"type": "audio", "data": "...", "format": "..."}
                                
                                audio_data = item.get("input_audio") or item.get("audio")
                                
                                if audio_data and isinstance(audio_data, dict):
                                    # 嵌套结构
                                    raw_data = audio_data.get("data", "")
                                    audio_format = audio_data.get("format", "mp3")
                                    logger.info(f"[ChatQwenOmni] 使用嵌套结构")
                                elif item.get("base64"):
                                    # 扁平结构 - base64 字段
                                    raw_data = item.get("base64", "")
                                    # 从 mime_type 提取格式 (如 "audio/mpeg" -> "mp3")
                                    mime_type = item.get("mime_type", "audio/mp3")
                                    if "mpeg" in mime_type or "mp3" in mime_type:
                                        audio_format = "mp3"
                                    elif "wav" in mime_type:
                                        audio_format = "wav"
                                    elif "ogg" in mime_type:
                                        audio_format = "ogg"
                                    else:
                                        audio_format = "mp3"
                                    logger.info(f"[ChatQwenOmni] 使用 base64 字段: mime_type={mime_type}")
                                else:
                                    # 扁平结构 - data 字段
                                    raw_data = item.get("data", "")
                                    audio_format = item.get("format", "mp3")
                                    logger.info(f"[ChatQwenOmni] 使用 data 字段")
                                
                                # 检测音频的真实格式（通过 Base64 前缀）
                                detected_format = self._detect_audio_format(raw_data)
                                if detected_format:
                                    logger.info(f"[ChatQwenOmni] 检测到真实音频格式: {detected_format} (原标记: {audio_format})")
                                    audio_format = detected_format
                                
                                logger.info(f"[ChatQwenOmni] 检测到音频: format={audio_format}, data_size={len(raw_data)} chars")
                                
                                # 构建 MIME 类型
                                mime_type_map = {
                                    "mp3": "audio/mpeg",
                                    "mpeg": "audio/mpeg", 
                                    "wav": "audio/wav",
                                    "m4a": "audio/mp4",
                                    "ogg": "audio/ogg",
                                    "webm": "audio/webm",
                                    "opus": "audio/opus",
                                }
                                mime_type = mime_type_map.get(audio_format.lower(), f"audio/{audio_format}")
                                
                                # 确保 data 字段是完整的 data URL 格式
                                if raw_data.startswith("data:"):
                                    audio_data_url = raw_data
                                else:
                                    audio_data_url = f"data:{mime_type};base64,{raw_data}"
                                
                                # Qwen-Omni 格式：使用 input_audio 结构，data 是完整的 data URL
                                content_parts.append({
                                    "type": "input_audio",
                                    "input_audio": {
                                        "data": audio_data_url,
                                        "format": audio_format,
                                    }
                                })
                                logger.info(f"[ChatQwenOmni] 添加音频到请求: mime_type={mime_type}, data_url_prefix={audio_data_url[:50]}...")
                            elif item.get("type") == "image_url":
                                # 图片也支持
                                content_parts.append(item)
                    
                    result.append({
                        "role": "user",
                        "content": content_parts,
                    })
                    
            elif isinstance(msg, AIMessage):
                content = msg.content if msg.content else ""
                msg_dict = {
                    "role": "assistant",
                    "content": content,
                }
                
                # 处理工具调用
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    msg_dict["tool_calls"] = [
                        {
                            "id": tc.get("id", f"call_{i}"),
                            "type": "function",
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": json.dumps(tc.get("args", {}), ensure_ascii=False),
                            }
                        }
                        for i, tc in enumerate(msg.tool_calls)
                    ]
                
                result.append(msg_dict)
                    
            elif isinstance(msg, ToolMessage):
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id if hasattr(msg, 'tool_call_id') else "",
                    "content": msg.content,
                })
        
        return result

    def _convert_tools_to_openai_format(
        self,
        tools: Optional[List[Any]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """将工具转换为 OpenAI 格式"""
        if not tools:
            return None
        
        formatted_tools = []
        for tool in tools:
            if hasattr(tool, "name") and hasattr(tool, "description"):
                # LangChain Tool 对象
                formatted_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": getattr(tool, "args_schema", {}).schema() if hasattr(tool, "args_schema") and tool.args_schema else {},
                    }
                })
            elif isinstance(tool, dict):
                if "function" in tool:
                    formatted_tools.append(tool)
                else:
                    formatted_tools.append({
                        "type": "function",
                        "function": tool,
                    })
        
        return formatted_tools if formatted_tools else None
    
    def _build_request_body(
        self,
        messages: List[BaseMessage],
        stream: bool = True,
        tools: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """构建请求体"""
        qwen_messages = self._convert_messages_to_qwen_format(messages)
        
        body: Dict[str, Any] = {
            "model": self.model,
            "messages": qwen_messages,
            "temperature": self.temperature,
            "stream": stream,  # Qwen-Omni 音频输入必须使用流式
        }
        
        if self.max_tokens:
            body["max_tokens"] = self.max_tokens
        
        # 检测消息中是否包含音频输入，如果有则添加 modalities 参数
        has_audio_input = self._check_has_audio_input(qwen_messages)
        if has_audio_input:
            # Qwen-Omni 需要 modalities 参数来指定输出模态
            # 这里只输出文本，不需要输出音频
            body["modalities"] = ["text"]
            logger.info(f"[ChatQwenOmni] 检测到音频输入，添加 modalities=[\"text\"]")
        
        # 添加工具
        openai_tools = self._convert_tools_to_openai_format(tools)
        if openai_tools:
            body["tools"] = openai_tools
        
        # 流式选项
        if stream:
            body["stream_options"] = {"include_usage": True}
        
        return body
    
    def _check_has_audio_input(self, messages: List[Dict[str, Any]]) -> bool:
        """检查消息中是否包含音频输入"""
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") in ("input_audio", "audio"):
                        return True
        return False
    
    def _detect_audio_format(self, base64_data: str) -> Optional[str]:
        """
        通过 Base64 数据前缀检测音频的真实格式
        
        常见音频格式的 Base64 前缀：
        - WebM: GkXfo (EBML header: 1A 45 DF A3)
        - MP3 with ID3: SUQz (ID3 tag)
        - MP3 without ID3: //uQ or //uY (MPEG frame sync)
        - WAV: UklGR (RIFF header)
        - OGG: T2dn (OggS header)
        - FLAC: ZkxhQ (fLaC header)
        - AAC: //vQ or AAAA (AAC frame)
        """
        if not base64_data or len(base64_data) < 8:
            return None
        
        prefix = base64_data[:8]
        
        # WebM/Matroska (EBML header)
        if prefix.startswith("GkXfo"):
            return "webm"
        
        # MP3 with ID3 tag
        if prefix.startswith("SUQz"):
            return "mp3"
        
        # MP3 MPEG frame sync (无 ID3)
        if prefix.startswith("//uQ") or prefix.startswith("//uY"):
            return "mp3"
        
        # WAV (RIFF header)
        if prefix.startswith("UklGR"):
            return "wav"
        
        # OGG (OggS header)
        if prefix.startswith("T2dn"):
            return "ogg"
        
        # FLAC (fLaC header)
        if prefix.startswith("ZkxhQ"):
            return "flac"
        
        # AAC
        if prefix.startswith("//vQ") or prefix.startswith("AAAA"):
            return "aac"
        
        return None
    
    def _parse_response(self, response_data: Dict[str, Any]) -> AIMessage:
        """解析非流式响应"""
        choices = response_data.get("choices", [])
        if not choices:
            return AIMessage(content="")
        
        message = choices[0].get("message", {})
        content = message.get("content", "")
        
        # 处理工具调用
        tool_calls_data = message.get("tool_calls", [])
        tool_calls = []
        for tc in tool_calls_data:
            func = tc.get("function", {})
            try:
                args = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({
                "id": tc.get("id", ""),
                "name": func.get("name", ""),
                "args": args,
            })
        
        if tool_calls:
            return AIMessage(content=content, tool_calls=tool_calls)
        
        return AIMessage(content=content)
    
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """同步生成（非流式）- 注意：音频输入可能不支持非流式"""
        with httpx.Client(timeout=self.timeout, verify=False) as client:
            url = self._get_api_url()
            body = self._build_request_body(messages, stream=False, tools=kwargs.get("tools"))
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            
            response = client.post(url, json=body, headers=headers)
            
            if response.status_code != 200:
                raise ValueError(f"Qwen API 错误: {response.status_code} - {response.text[:500]}")
            
            result = response.json()
            message = self._parse_response(result)
            
            return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """异步生成（非流式）"""
        async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
            url = self._get_api_url()
            body = self._build_request_body(messages, stream=False, tools=kwargs.get("tools"))
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            
            response = await client.post(url, json=body, headers=headers)
            
            if response.status_code != 200:
                raise ValueError(f"Qwen API 错误: {response.status_code} - {response.text[:500]}")
            
            result = response.json()
            message = self._parse_response(result)
            
            return ChatResult(generations=[ChatGeneration(message=message)])
    
    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """同步流式生成"""
        with httpx.Client(timeout=self.timeout, verify=False) as client:
            url = self._get_api_url()
            body = self._build_request_body(messages, stream=True, tools=kwargs.get("tools"))
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            
            with client.stream("POST", url, json=body, headers=headers) as response:
                if response.status_code != 200:
                    error_text = response.read().decode()
                    raise ValueError(f"Qwen API 错误: {response.status_code} - {error_text[:500]}")
                
                for line in response.iter_lines():
                    line = line.strip()
                    if not line or line == "data: [DONE]":
                        continue
                    
                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            obj = json.loads(data_str)
                            text, tool_calls = self._extract_from_stream_chunk(obj)
                            
                            if text or tool_calls:
                                chunk_kwargs = {"content": text or ""}
                                if tool_calls:
                                    chunk_kwargs["tool_calls"] = tool_calls
                                
                                chunk_msg = AIMessageChunk(**chunk_kwargs)
                                gen_chunk = ChatGenerationChunk(message=chunk_msg)
                                
                                if run_manager and text:
                                    run_manager.on_llm_new_token(text, chunk=gen_chunk)
                                
                                yield gen_chunk
                        except json.JSONDecodeError:
                            continue

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """异步流式生成"""
        async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
            url = self._get_api_url()
            body = self._build_request_body(messages, stream=True, tools=kwargs.get("tools"))
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            
            # 调试：打印请求体的关键信息
            logger.info(f"[ChatQwenOmni] 流式请求: {url}")
            logger.info(f"[ChatQwenOmni] 请求体: model={body.get('model')}, messages_count={len(body.get('messages', []))}, modalities={body.get('modalities')}")
            
            async with client.stream("POST", url, json=body, headers=headers) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise ValueError(f"Qwen API 错误: {response.status_code} - {error_text.decode()[:500]}")
                
                chunk_count = 0
                
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or line == "data: [DONE]":
                        continue
                    
                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            obj = json.loads(data_str)
                            text, tool_calls = self._extract_from_stream_chunk(obj)
                            
                            if text or tool_calls:
                                chunk_count += 1
                                chunk_kwargs = {"content": text or ""}
                                if tool_calls:
                                    chunk_kwargs["tool_calls"] = tool_calls
                                
                                chunk_msg = AIMessageChunk(**chunk_kwargs)
                                gen_chunk = ChatGenerationChunk(message=chunk_msg)
                                
                                if run_manager and text:
                                    await run_manager.on_llm_new_token(text, chunk=gen_chunk)
                                
                                if chunk_count <= 3:
                                    logger.debug(f"[ChatQwenOmni] 块 #{chunk_count}: text={text[:50] if text else 'None'}...")
                                
                                yield gen_chunk
                        except json.JSONDecodeError as e:
                            logger.debug(f"[ChatQwenOmni] JSON 解析失败: {e}")
                            continue
                
                logger.info(f"[ChatQwenOmni] 流式完成，共 {chunk_count} 个块")
    
    def _extract_from_stream_chunk(
        self,
        chunk: Dict[str, Any],
    ) -> tuple[str, Optional[List[Dict[str, Any]]]]:
        """从流式响应块中提取文本和工具调用"""
        choices = chunk.get("choices", [])
        if not choices:
            return "", None
        
        delta = choices[0].get("delta", {})
        text = delta.get("content", "") or ""
        
        # 提取工具调用
        tool_calls_data = delta.get("tool_calls", [])
        tool_calls = []
        for tc in tool_calls_data:
            func = tc.get("function", {})
            tc_id = tc.get("id", "")
            tc_name = func.get("name", "")
            tc_args_str = func.get("arguments", "")
            
            if tc_id or tc_name or tc_args_str:
                try:
                    args = json.loads(tc_args_str) if tc_args_str else {}
                except json.JSONDecodeError:
                    args = {}
                
                tool_calls.append({
                    "id": tc_id,
                    "name": tc_name,
                    "args": args,
                })
        
        return text, tool_calls if tool_calls else None
    
    def bind_tools(
        self,
        tools: List[Any],
        **kwargs: Any,
    ) -> "ChatQwenOmni":
        """绑定工具，返回新的模型实例"""
        formatted_tools = self._convert_tools_to_openai_format(tools)
        
        new_instance = ChatQwenOmni(
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            streaming=self.streaming,
        )
        new_instance._bound_tools = formatted_tools
        return new_instance
    
    @property
    def _bound_tools(self) -> Optional[List[Dict[str, Any]]]:
        return getattr(self, "__bound_tools", None)
    
    @_bound_tools.setter
    def _bound_tools(self, value: Optional[List[Dict[str, Any]]]):
        self.__bound_tools = value

