"""
自定义 Gemini Chat 模型
支持自定义 base_url（中转 API）和音频输入

特点：
- 继承 LangChain BaseChatModel，可与 LangGraph Agent 无缝集成
- 支持自定义 base_url，兼容第三方中转 API
- 支持音频输入（通过 Gemini 原生 inline_data 格式）
- 支持流式输出
- 支持工具调用（function calling）
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


class ChatGeminiCustom(BaseChatModel):
    """
    自定义 Gemini Chat 模型
    
    支持自定义 base_url，可用于第三方中转 API
    支持音频输入，通过 Gemini 原生 inline_data 格式
    
    使用示例：
    ```python
    llm = ChatGeminiCustom(
        model="gemini-2.5-pro",
        api_key="your-api-key",
        base_url="http://your-proxy.com",  # 自定义中转 API
        temperature=0.7,
    )
    
    # 纯文本对话
    response = llm.invoke([HumanMessage(content="Hello")])
    
    # 带音频的对话（通过 additional_kwargs 传递）
    response = llm.invoke([
        HumanMessage(
            content="请转录这段音频",
            additional_kwargs={
                "audio_data": base64_audio,
                "audio_mime_type": "audio/mp3",
            }
        )
    ])
    ```
    """
    
    model: str = Field(default="gemini-2.5-pro", description="模型名称")
    api_key: str = Field(default="", description="API Key")
    base_url: str = Field(
        default="https://generativelanguage.googleapis.com",
        description="API Base URL（支持自定义中转）"
    )
    temperature: float = Field(default=0.7, description="温度参数")
    max_tokens: Optional[int] = Field(default=None, description="最大输出 token 数")
    timeout: float = Field(default=120.0, description="请求超时时间（秒）")
    streaming: bool = Field(default=True, description="是否启用流式输出")
    
    # 内部状态
    _http_client: Optional[httpx.AsyncClient] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    @property
    def _llm_type(self) -> str:
        return "gemini-custom"
    
    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
        }

    def _get_api_url(self, stream: bool = False) -> str:
        """构建 API URL"""
        base = self.base_url.rstrip('/')
        # 移除可能存在的 /v1 后缀
        if base.endswith('/v1'):
            base = base[:-3]
        
        action = "streamGenerateContent" if stream else "generateContent"
        url = f"{base}/v1beta/models/{self.model}:{action}?key={self.api_key}"
        
        # 流式请求需要添加 alt=sse 参数，返回 SSE 格式
        if stream:
            url += "&alt=sse"
        
        return url
    
    def _convert_messages_to_gemini_format(
        self,
        messages: List[BaseMessage],
    ) -> tuple[Optional[str], List[Dict[str, Any]]]:
        """
        将 LangChain 消息转换为 Gemini API 格式
        
        Returns:
            (system_instruction, contents) 元组
        """
        system_instruction = None
        contents = []
        
        for msg in messages:
            if isinstance(msg, SystemMessage):
                # Gemini 使用 system_instruction 而不是 system role
                system_instruction = msg.content
            elif isinstance(msg, HumanMessage):
                parts = []
                
                # 处理文本内容
                if isinstance(msg.content, str):
                    if msg.content:
                        parts.append({"text": msg.content})
                elif isinstance(msg.content, list):
                    # 多模态内容列表
                    for item in msg.content:
                        if isinstance(item, str):
                            parts.append({"text": item})
                        elif isinstance(item, dict):
                            if item.get("type") == "text":
                                parts.append({"text": item.get("text", "")})
                            elif item.get("type") == "image_url":
                                # 图片 URL 或 base64
                                image_url = item.get("image_url", {})
                                url = image_url.get("url", "") if isinstance(image_url, dict) else image_url
                                if url.startswith("data:"):
                                    # Base64 格式: data:image/jpeg;base64,xxxxx
                                    try:
                                        header, data = url.split(",", 1)
                                        mime_type = header.split(":")[1].split(";")[0]
                                        parts.append({
                                            "inline_data": {
                                                "mime_type": mime_type,
                                                "data": data,
                                            }
                                        })
                                    except Exception as e:
                                        logger.warning(f"解析 base64 图片失败: {e}")
                                else:
                                    # URL 格式 - Gemini 不直接支持 URL，需要下载
                                    logger.warning("Gemini 不支持直接使用图片 URL，请使用 base64 格式")
                            elif item.get("type") == "input_audio":
                                # 音频输入
                                audio_data = item.get("input_audio", {})
                                parts.append({
                                    "inline_data": {
                                        "mime_type": f"audio/{audio_data.get('format', 'mp3')}",
                                        "data": audio_data.get("data", ""),
                                    }
                                })
                
                # 检查 additional_kwargs 中的音频数据
                if hasattr(msg, 'additional_kwargs') and msg.additional_kwargs:
                    audio_data = msg.additional_kwargs.get("audio_data")
                    audio_mime_type = msg.additional_kwargs.get("audio_mime_type", "audio/mp3")
                    if audio_data:
                        parts.append({
                            "inline_data": {
                                "mime_type": audio_mime_type,
                                "data": audio_data,
                            }
                        })
                
                if parts:
                    contents.append({"role": "user", "parts": parts})
                    
            elif isinstance(msg, AIMessage):
                parts = []
                if msg.content:
                    parts.append({"text": msg.content})
                
                # 处理工具调用
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        parts.append({
                            "functionCall": {
                                "name": tool_call.get("name", ""),
                                "args": tool_call.get("args", {}),
                            }
                        })
                
                if parts:
                    contents.append({"role": "model", "parts": parts})
                    
            elif isinstance(msg, ToolMessage):
                # 工具响应
                contents.append({
                    "role": "user",
                    "parts": [{
                        "functionResponse": {
                            "name": msg.name or "unknown",
                            "response": {"result": msg.content},
                        }
                    }]
                })
        
        return system_instruction, contents

    def _convert_tools_to_gemini_format(
        self,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """将 LangChain 工具转换为 Gemini function declarations 格式"""
        if not tools:
            return None
        
        function_declarations = []
        for tool in tools:
            # LangChain 工具格式
            if "function" in tool:
                func = tool["function"]
                function_declarations.append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {}),
                })
            # 直接的函数声明格式
            elif "name" in tool:
                function_declarations.append({
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {}),
                })
        
        if function_declarations:
            return [{"functionDeclarations": function_declarations}]
        return None
    
    def _build_request_body(
        self,
        messages: List[BaseMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """构建请求体"""
        system_instruction, contents = self._convert_messages_to_gemini_format(messages)
        
        body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
            },
        }
        
        if self.max_tokens:
            body["generationConfig"]["maxOutputTokens"] = self.max_tokens
        
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        
        # 添加工具
        gemini_tools = self._convert_tools_to_gemini_format(tools)
        if gemini_tools:
            body["tools"] = gemini_tools
        
        return body
    
    def _parse_response(self, response_data: Dict[str, Any]) -> AIMessage:
        """解析 Gemini 响应"""
        candidates = response_data.get("candidates", [])
        if not candidates:
            return AIMessage(content="")
        
        candidate = candidates[0]
        content_parts = candidate.get("content", {}).get("parts", [])
        
        text_parts = []
        tool_calls = []
        
        for part in content_parts:
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                func_call = part["functionCall"]
                tool_calls.append({
                    "id": f"call_{len(tool_calls)}",
                    "name": func_call.get("name", ""),
                    "args": func_call.get("args", {}),
                })
        
        content = "".join(text_parts)
        
        if tool_calls:
            return AIMessage(
                content=content,
                tool_calls=tool_calls,
            )
        
        return AIMessage(content=content)
    
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """同步生成（非流式）"""
        # 使用 httpx 同步客户端
        with httpx.Client(timeout=self.timeout, verify=False) as client:
            url = self._get_api_url(stream=False)
            body = self._build_request_body(messages, kwargs.get("tools"))
            
            response = client.post(
                url,
                json=body,
                headers={"Content-Type": "application/json"},
            )
            
            if response.status_code != 200:
                raise ValueError(f"Gemini API 错误: {response.status_code} - {response.text[:500]}")
            
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
            url = self._get_api_url(stream=False)
            body = self._build_request_body(messages, kwargs.get("tools"))
            
            response = await client.post(
                url,
                json=body,
                headers={"Content-Type": "application/json"},
            )
            
            if response.status_code != 200:
                raise ValueError(f"Gemini API 错误: {response.status_code} - {response.text[:500]}")
            
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
        """同步流式生成（使用 SSE 格式）"""
        with httpx.Client(timeout=self.timeout, verify=False) as client:
            url = self._get_api_url(stream=True)
            body = self._build_request_body(messages, kwargs.get("tools"))
            
            with client.stream(
                "POST",
                url,
                json=body,
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status_code != 200:
                    error_text = response.read().decode()
                    raise ValueError(f"Gemini API 错误: {response.status_code} - {error_text[:500]}")
                
                # SSE 格式：每行以 "data: " 开头
                for line in response.iter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    
                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            obj = json.loads(data_str)
                            text = self._extract_text_from_stream_chunk(obj)
                            tool_calls = self._extract_tool_calls_from_stream_chunk(obj)
                            
                            if text or tool_calls:
                                # 注意: tool_calls 必须是列表或不传，不能是 None
                                # Pydantic 验证要求 tool_calls 为 list 类型
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
        """
        异步流式生成
        
        使用 SSE 格式（alt=sse 参数）接收流式响应
        每行格式: data: {...json...}
        
        重要：必须通过 run_manager.on_llm_new_token() 通知 LangGraph 新的 token
        否则 astream_events 无法捕获流式输出
        """
        async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
            url = self._get_api_url(stream=True)
            body = self._build_request_body(messages, kwargs.get("tools"))
            
            logger.info(f"[ChatGeminiCustom] 流式请求 (SSE): {url[:80]}...")
            
            async with client.stream(
                "POST",
                url,
                json=body,
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise ValueError(f"Gemini API 错误: {response.status_code} - {error_text.decode()[:500]}")
                
                chunk_count = 0
                
                # SSE 格式：每行以 "data: " 开头
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    
                    # 处理 SSE 数据行
                    if line.startswith("data: "):
                        data_str = line[6:]  # 移除 "data: " 前缀
                        try:
                            obj = json.loads(data_str)
                            text = self._extract_text_from_stream_chunk(obj)
                            tool_calls = self._extract_tool_calls_from_stream_chunk(obj)
                            
                            if text or tool_calls:
                                chunk_count += 1
                                # 注意: tool_calls 必须是列表或不传，不能是 None
                                # Pydantic 验证要求 tool_calls 为 list 类型
                                chunk_kwargs = {"content": text or ""}
                                if tool_calls:
                                    chunk_kwargs["tool_calls"] = tool_calls
                                
                                chunk_msg = AIMessageChunk(**chunk_kwargs)
                                gen_chunk = ChatGenerationChunk(message=chunk_msg)
                                
                                # 关键：通知 run_manager 新的 token
                                # 这样 LangGraph 的 astream_events 才能捕获
                                if run_manager and text:
                                    await run_manager.on_llm_new_token(text, chunk=gen_chunk)
                                
                                if chunk_count <= 3:
                                    logger.debug(f"[ChatGeminiCustom] SSE 块 #{chunk_count}: text={text[:50] if text else 'None'}...")
                                
                                yield gen_chunk
                        except json.JSONDecodeError as e:
                            logger.debug(f"[ChatGeminiCustom] JSON 解析失败: {e}, line={line[:100]}")
                            continue
                
                logger.info(f"[ChatGeminiCustom] 流式完成，共 {chunk_count} 个块")
    
    def _extract_text_from_stream_chunk(self, chunk: Dict[str, Any]) -> str:
        """从流式响应块中提取文本"""
        candidates = chunk.get("candidates", [])
        if not candidates:
            return ""
        
        parts = candidates[0].get("content", {}).get("parts", [])
        text_parts = []
        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
        
        return "".join(text_parts)
    
    def _extract_tool_calls_from_stream_chunk(
        self,
        chunk: Dict[str, Any],
    ) -> Optional[List[Dict[str, Any]]]:
        """从流式响应块中提取工具调用"""
        candidates = chunk.get("candidates", [])
        if not candidates:
            return None
        
        parts = candidates[0].get("content", {}).get("parts", [])
        tool_calls = []
        
        for part in parts:
            if "functionCall" in part:
                func_call = part["functionCall"]
                tool_calls.append({
                    "id": f"call_{len(tool_calls)}",
                    "name": func_call.get("name", ""),
                    "args": func_call.get("args", {}),
                })
        
        return tool_calls if tool_calls else None
    
    def bind_tools(
        self,
        tools: List[Any],
        **kwargs: Any,
    ) -> "ChatGeminiCustom":
        """绑定工具，返回新的模型实例"""
        # 转换工具格式
        formatted_tools = []
        for tool in tools:
            if hasattr(tool, "name") and hasattr(tool, "description"):
                # LangChain Tool 对象
                formatted_tools.append({
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": getattr(tool, "args_schema", {}).schema() if hasattr(tool, "args_schema") and tool.args_schema else {},
                })
            elif isinstance(tool, dict):
                formatted_tools.append(tool)
        
        # 创建新实例并存储工具
        new_instance = ChatGeminiCustom(
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
