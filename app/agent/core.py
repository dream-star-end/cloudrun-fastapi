"""
AI Agent 核心模块
基于 LangChain 1.0 + LangGraph 的智能代理

特点：
- 自主决策：根据用户意图选择合适的工具
- 多轮对话：保持上下文连贯性
- 自我反思：评估执行结果并优化策略
- 流式输出：支持实时响应
- 多模态支持：支持图片、语音输入
- 智能模型路由：根据用户配置和消息类型动态选择模型
"""

import json
import logging
from typing import AsyncIterator, Optional, Dict, Any, List, Union, TYPE_CHECKING
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

if TYPE_CHECKING:
    from .gemini_chat import ChatGeminiCustom

from .tools import get_all_tools
from .memory import AgentMemory
from ..config import settings, IS_CLOUDRUN, DISABLE_SSL_VERIFY
from ..services.model_config_service import ModelConfigService

logger = logging.getLogger(__name__)


# AI 学习教练系统提示词
LEARNING_COACH_PROMPT = """你是一位专业的 AI 学习教练，名叫"小智"。你的职责是帮助用户高效学习、解决学习中的问题。

## 你的能力
你拥有以下工具，可以根据需要调用：

### 📚 学习计划
- **create_learning_plan**: 为用户创建个性化学习计划
- **generate_daily_tasks**: 生成每日学习任务

### 🔍 搜索
- **search_resources**: 联网搜索学习资源和资料
- **search_learning_materials**: 搜索特定学习材料

### 📝 任务管理
- **get_today_tasks**: 获取今日学习任务列表
- **complete_task**: 标记任务为已完成
- **get_task_progress**: 查看任务完成进度
- **suggest_task_adjustment**: 建议调整任务安排

### ✅ 打卡系统
- **do_checkin**: 执行学习打卡
- **get_checkin_status**: 获取打卡状态和统计
- **get_badges**: 获取成就徽章列表

### 🍅 番茄专注
- **get_focus_stats**: 获取专注时间统计
- **suggest_focus_plan**: 建议专注计划安排

### 📕 错题本
- **get_mistakes**: 获取错题列表
- **add_mistake**: 添加新错题
- **analyze_mistake**: AI分析错题原因
- **generate_review_questions**: 生成复习题
- **mark_mistake_mastered**: 标记错题已掌握

### 📊 统计分析
- **get_learning_stats**: 获取学习统计数据
- **get_ranking**: 获取学习排行榜
- **get_achievement_rate**: 获取目标达成率
- **analyze_learning_pattern**: 分析学习模式
- **get_calendar_data**: 获取日历学习详情
- **analyze_learning_status**: 分析整体学习状态

### 👤 用户画像
- **update_user_profile**: 更新用户学习画像
- **get_user_stats**: 获取用户统计信息

### 📚 文档伴读
- **get_documents**: 获取用户上传的学习文档列表
- **search_documents**: 搜索用户的文档
- **get_document_stats**: 获取文档统计信息
- **get_recent_documents**: 获取最近阅读的文档

## 用户画像
{user_profile}

## 对话记忆
{conversation_summary}

## 行为准则
1. **主动关怀**: 关注用户的学习状态和情绪，适时给予鼓励
2. **因材施教**: 根据用户画像调整教学风格和难度
3. **循序渐进**: 将复杂任务分解为可执行的小步骤
4. **持续优化**: 根据用户反馈不断改进建议
5. **简洁高效**: 回复简洁明了，避免冗长
6. **善用工具**: 根据用户需求主动调用合适的工具

## 教练式对话（非常重要）
1. **追问式澄清**：当用户说“听不懂/不会/卡住了”，不要直接长篇解释。
   - 先用 1-3 个问题定位卡点属于哪类：概念/步骤/例子/术语/题意/代码报错
   - 再给“对症解释”：先最小可用解释，再补例子/类比/练习
2. **苏格拉底式引导**：刷题/编程/推理类问题，优先引导用户说出思路。
   - 先问：你现在的已知/目标是什么？你打算怎么做？哪一步不确定？
   - 用户给出思路后，再指出关键缺口并给下一步提示
   - 若用户明确要求直接答案/时间紧，再给答案但仍说明关键步骤

## 可信度与风险边界
1. **关键结论要给依据与信心提示**：
   - 用「依据」列出：来自题目/用户提供信息/常识/工具结果/搜索结果
   - 用「信心」标注：高/中/低；信息不足时先澄清，不要编
2. **敏感内容边界**（医疗/法律/财务/人身安全等）：
   - 明确提示你不是专业人士
   - 给出一般性信息与下一步建议（如寻求专业意见/紧急求助渠道）

## 回复风格
- 友好亲切，像朋友一样交流
- 使用简洁的中文
- 适当使用 emoji 增加亲和力
- 给出具体可执行的建议
- 引导用户使用小程序的各项功能

当前时间: {current_time}
"""

# AI 伴读助手系统提示词
READING_COMPANION_PROMPT = """你是一位智能伴读助手，名叫"小智"。你的职责是帮助用户阅读和理解各种学习材料。

## 你的能力
你拥有以下工具，可以根据需要调用：

### 🔍 搜索
- **search_resources**: 搜索相关的补充资料
- **search_learning_materials**: 搜索学习材料

### 📝 学习辅助
- **analyze_mistake**: 分析错题，找出问题所在
- **add_mistake**: 将题目添加到错题本
- **generate_review_questions**: 生成练习题检验理解

### 📊 进度追踪
- **get_today_tasks**: 查看今日任务
- **complete_task**: 完成学习任务
- **get_learning_stats**: 获取学习统计

## 用户画像
{user_profile}

## 阅读上下文
{reading_context}

## 行为准则
1. **深入浅出**: 用通俗易懂的语言解释复杂概念
2. **举一反三**: 通过例子和类比帮助理解
3. **互动学习**: 适时提问，检验用户理解程度
4. **知识关联**: 将新知识与已学内容建立联系
5. **鼓励思考**: 引导用户主动思考而非被动接受
6. **善用工具**: 遇到问题时主动调用工具辅助

## 可信度与边界
- 关键结论给「依据」与「信心」提示；不确定就先问澄清问题
- 涉及医疗/法律等敏感建议时，给出边界提示并建议寻求专业意见

当前时间: {current_time}
"""


class LearningAgent:
    """
    AI 学习教练/伴读 Agent
    
    基于 LangChain 1.0 + LangGraph 实现
    - 使用 create_react_agent 创建 ReAct 风格的智能体
    - 支持工具调用和多轮对话
    - 内置记忆管理和用户画像
    - 智能模型路由：根据用户配置和消息类型动态选择模型
    """
    
    def __init__(
        self,
        user_id: str,
        mode: str = "coach",  # "coach" 或 "reader"
        memory: Optional[AgentMemory] = None,
    ):
        self.user_id = user_id
        self.mode = mode
        self.memory = memory or AgentMemory(user_id)
        
        # LLM 实例缓存（按模型类型）
        self._llm_cache: Dict[str, ChatOpenAI] = {}
        self._current_llm: Optional[ChatOpenAI] = None
        self._current_model_info: Optional[Dict[str, Any]] = None
        
        # 获取工具
        self.tools = get_all_tools(user_id=user_id, memory=self.memory)
        
        # LangGraph 检查点（用于对话状态持久化）
        self.checkpointer = MemorySaver()
        
        # Agent 实例（延迟创建，等待模型配置加载）
        self.agent = None
    
    def _create_llm(
        self,
        model_config: Dict[str, Any],
    ) -> Union[ChatOpenAI, "ChatGeminiCustom"]:
        """
        根据模型配置创建 LLM 实例
        
        支持两种 LLM 类型：
        - ChatOpenAI: 用于 OpenAI 兼容 API（DeepSeek、OpenRouter 等）
        - ChatGeminiCustom: 用于原生 Gemini API 格式（支持自定义 base_url）
        
        Args:
            model_config: 模型配置，包含 platform, model, base_url, api_key, api_format
            
        Returns:
            ChatOpenAI 或 ChatGeminiCustom 实例
        """
        import httpx
        from .gemini_chat import ChatGeminiCustom
        
        platform = model_config.get("platform", "deepseek")
        model = model_config.get("model", "deepseek-chat")
        base_url = model_config.get("base_url", settings.DEEPSEEK_API_BASE)
        api_key = model_config.get("api_key", "")  # API Key 必须从用户配置获取
        api_format = model_config.get("api_format", "openai")  # 默认 OpenAI 兼容格式
        
        if not api_key:
            logger.warning(f"[LearningAgent] API Key 未配置: platform={platform}, model={model}")
        
        logger.info(f"[LearningAgent] 创建 LLM: platform={platform}, model={model}, api_format={api_format}")
        
        # 根据 api_format 选择 LLM 类型
        if api_format == "gemini":
            # 使用自定义 Gemini LLM（支持原生 Gemini API 格式和音频输入）
            logger.info(f"[LearningAgent] 使用 ChatGeminiCustom: base_url={base_url[:30]}...")
            return ChatGeminiCustom(
                model=model,
                api_key=api_key,
                base_url=base_url,
                temperature=0.7,
                streaming=True,
                timeout=120.0,
            )
        else:
            # 使用 ChatOpenAI（OpenAI 兼容格式）
            # 云托管环境中可能存在 SSL 证书问题，配置 HTTP 客户端
            http_client = None
            if IS_CLOUDRUN or DISABLE_SSL_VERIFY:
                http_client = httpx.Client(verify=False, http2=False, timeout=120.0)
            
            return ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url=base_url,
                temperature=0.7,
                streaming=True,
                http_client=http_client,
            )
    
    async def _get_llm_for_message(
        self,
        multimodal: Optional[Dict[str, Any]] = None,
    ) -> Union[ChatOpenAI, Any]:
        """
        根据消息类型获取合适的 LLM
        
        智能路由逻辑：
        - 纯文本消息 → 用户配置的文本模型
        - 图片消息 → 用户配置的多模态/视觉模型
        - 语音消息 → 用户配置的语音模型（或降级到文本模型）
        
        根据 api_format 返回不同的 LLM 类型：
        - api_format="openai" → ChatOpenAI
        - api_format="gemini" → ChatGeminiCustom
        
        Args:
            multimodal: 多模态消息字典
            
        Returns:
            ChatOpenAI 或 ChatGeminiCustom 实例
        """
        # 检测消息类型
        model_type = "text"  # 默认文本
        
        if multimodal:
            has_image = bool(multimodal.get("image_url") or multimodal.get("image_base64"))
            has_voice = bool(multimodal.get("voice_url"))
            
            if has_image:
                model_type = "multimodal"
            elif has_voice:
                model_type = "voice"
        
        # 检查缓存
        cache_key = f"{self.user_id}:{model_type}"
        if cache_key in self._llm_cache:
            logger.debug(f"[LearningAgent] 使用缓存的 LLM: type={model_type}")
            return self._llm_cache[cache_key]
        
        # 从 ModelConfigService 获取用户配置的模型
        try:
            model_config = await ModelConfigService.get_model_for_type(
                openid=self.user_id,
                model_type=model_type,
            )
            
            is_user_config = model_config.get("is_user_config", False)
            platform = model_config.get("platform", "unknown")
            model = model_config.get("model", "unknown")
            
            if is_user_config:
                logger.info(f"[LearningAgent] 使用用户配置的模型: type={model_type}, platform={platform}, model={model}")
            else:
                logger.info(f"[LearningAgent] 使用系统默认模型: type={model_type}, platform={platform}, model={model}")
            
            # 保存当前模型信息（用于日志和调试）
            self._current_model_info = {
                "type": model_type,
                "platform": platform,
                "model": model,
                "is_user_config": is_user_config,
            }
            
        except Exception as e:
            logger.error(f"[LearningAgent] 获取模型配置失败: {e}")
            # 降级到系统默认配置（无 API Key，会在调用时失败）
            model_config = {
                "platform": "deepseek",
                "model": settings.DEEPSEEK_MODEL,
                "base_url": settings.DEEPSEEK_API_BASE,
                "api_key": "",  # 无法获取用户配置时，API Key 为空
                "is_user_config": False,
            }
            self._current_model_info = {
                "type": model_type,
                "platform": "deepseek",
                "model": settings.DEEPSEEK_MODEL,
                "is_user_config": False,
                "fallback_reason": str(e),
            }
        
        # 创建 LLM 实例
        llm = self._create_llm(model_config)
        
        # 缓存 LLM 实例
        self._llm_cache[cache_key] = llm
        self._current_llm = llm
        
        return llm
    
    def _create_agent(self, llm: Union[ChatOpenAI, Any]):
        """
        创建 LangGraph ReAct Agent
        
        LangChain 1.0 推荐使用 LangGraph 的 create_react_agent
        这是一个更灵活、可控的 Agent 实现方式
        
        注意：LangGraph 0.2.x+ 中 state_modifier 参数已被移除
        系统提示现在通过 SystemMessage 在 chat() 和 chat_stream() 中动态添加
        这样可以支持动态的用户画像和对话摘要注入
        
        Args:
            llm: ChatOpenAI 或 ChatGeminiCustom 实例（根据消息类型动态选择）
        """
        # 使用 LangGraph 创建 ReAct Agent
        # create_react_agent 返回一个 CompiledGraph
        # 系统提示通过 _build_system_message() 动态构建并作为 SystemMessage 添加
        self.agent = create_react_agent(
            model=llm,
            tools=self.tools,
            checkpointer=self.checkpointer,  # 启用对话状态持久化
        )
    
    def _build_multimodal_content(
        self,
        multimodal: Dict[str, Any],
        is_multimodal_model: bool = False,
        voice_base64: Optional[str] = None,
        voice_format: str = "mp3",
    ) -> Union[str, List[Dict[str, Any]]]:
        """
        构建多模态消息内容
        
        根据模型能力选择不同的构建方式：
        - 多模态模型（如 GPT-4o、Gemini）：直接构建包含图片/音频的消息列表
        - 纯文本模型（如 DeepSeek）：转换为文本提示，让 Agent 调用工具处理
        
        Args:
            multimodal: 多模态消息字典，包含 text, image_url, image_base64, voice_url, voice_text
            is_multimodal_model: 当前模型是否支持多模态输入
            voice_base64: 语音的 base64 编码（用于直接发送给支持音频的模型）
            voice_format: 语音格式（mp3, wav 等）
            
        Returns:
            - 多模态模型：返回消息内容列表 [{"type": "text", ...}, {"type": "image_url", ...}, {"type": "input_audio", ...}]
            - 纯文本模型：返回纯文本字符串
        """
        text = multimodal.get("text", "")
        image_url = multimodal.get("image_url")
        image_base64 = multimodal.get("image_base64")
        voice_text = multimodal.get("voice_text")
        
        # 合并文本内容
        text_parts = []
        if text:
            text_parts.append(text)
        if voice_text:
            if not text:
                text_parts.append(voice_text)
            else:
                text_parts.append(f"\n[语音内容]: {voice_text}")
        
        combined_text = "".join(text_parts).strip()
        
        # 检查是否有图片或音频需要处理
        has_image = image_url or image_base64
        has_audio = voice_base64 is not None
        
        # 如果是多模态模型且有图片或音频，直接构建多模态消息
        if is_multimodal_model and (has_image or has_audio):
            content_parts = []
            
            # 添加文本部分
            if combined_text:
                content_parts.append({"type": "text", "text": combined_text})
            elif has_audio:
                # 如果只有音频没有文本，添加默认提示
                # 明确要求用中文回复，并告诉模型这是语音输入
                content_parts.append({
                    "type": "text", 
                    "text": "这是用户发送的语音消息，请先听懂语音内容，然后用中文回复用户的问题或请求。"
                })
            else:
                # 如果只有图片没有文本，添加默认提示
                content_parts.append({"type": "text", "text": "请用中文分析这张图片的内容。"})
            
            # 添加图片部分
            if image_url:
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": image_url}
                })
            elif image_base64:
                # Base64 格式图片
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                })
            
            # 添加音频部分（直接发送给支持音频输入的模型）
            if has_audio:
                content_parts.append({
                    "type": "input_audio",
                    "input_audio": {
                        "data": voice_base64,
                        "format": voice_format,
                    }
                })
                logger.info(f"[LearningAgent] 添加音频内容: format={voice_format}, size={len(voice_base64)} chars")
            
            logger.info(f"[LearningAgent] 构建多模态消息: {len(content_parts)} 部分")
            return content_parts
        
        # 纯文本模型：转换为文本提示
        parts = []
        if combined_text:
            parts.append(combined_text)
        
        # 图片部分 - 转换为文本提示，让 Agent 调用 recognize_image 工具
        if image_url:
            parts.append(f"\n\n[用户上传了一张图片，请使用 recognize_image 工具识别图片内容]\n图片URL: {image_url}")
        elif image_base64:
            parts.append("\n\n[用户上传了一张图片（Base64格式），但当前无法直接处理。请告知用户重新上传图片。]")
        
        result = "".join(parts).strip()
        return result if result else ""
    
    async def _transcribe_voice(self, voice_url: str) -> str:
        """
        转录语音为文本
        
        使用用户配置的语音模型进行语音转文本（STT）
        支持两种模式：
        1. 传统 STT API（OpenAI Whisper、通义千问 Paraformer）
        2. 多模态 Chat API（OpenRouter、Gemini 等，通过 base64 音频）
        
        Args:
            voice_url: 语音文件 URL
            
        Returns:
            转录后的文本
        """
        import httpx
        import base64
        from ..config import get_http_client_kwargs
        
        logger.info(f"[LearningAgent] 开始转录语音: {voice_url[:50]}...")
        
        try:
            # 获取用户配置的语音模型
            voice_config = await ModelConfigService.get_model_for_type(
                openid=self.user_id,
                model_type="voice",
            )
            
            api_key = voice_config.get("api_key", "")
            platform = voice_config.get("platform", "")
            base_url = voice_config.get("base_url", "")
            model = voice_config.get("model", "")
            
            if not api_key:
                raise ValueError("请先在「个人中心 → 模型配置」中配置语音模型的 API Key")
            
            logger.info(f"[LearningAgent] 使用语音模型: platform={platform}, model={model}, base_url={base_url[:30]}...")
            
            async with httpx.AsyncClient(**get_http_client_kwargs(90.0)) as client:
                # 下载音频
                audio_response = await client.get(voice_url, follow_redirects=True)
                if audio_response.status_code != 200:
                    raise ValueError(f"下载音频失败: HTTP {audio_response.status_code}")
                
                audio_data = audio_response.content
                content_type = audio_response.headers.get("content-type", "")
                
                # 推断文件格式和 MIME 类型
                if "mp3" in content_type or voice_url.endswith(".mp3"):
                    audio_format = "mp3"
                    mime_type = "audio/mpeg"
                elif "wav" in content_type or voice_url.endswith(".wav"):
                    audio_format = "wav"
                    mime_type = "audio/wav"
                elif "silk" in voice_url or "amr" in content_type:
                    # 微信语音格式 - 尝试作为 mp3 处理
                    audio_format = "mp3"
                    mime_type = "audio/mpeg"
                else:
                    audio_format = "mp3"
                    mime_type = "audio/mpeg"
                
                # 判断使用哪种 API 模式
                # qwen-omni 模型虽然支持音频输入，但用于转录时应使用 STT API（paraformer）
                # Chat API 适用于需要对话能力的场景，纯转录用 STT 更高效
                model_lower = model.lower()
                is_qwen_omni = any(pattern in model_lower for pattern in ["qwen-omni", "qwen2.5-omni", "qwen3-omni", "qwen-audio"])
                is_qwen_platform = platform == "qwen" or platform.startswith("qwen")
                
                logger.info(f"[LearningAgent] 语音转录路由判断: model={model}, platform={platform}, is_qwen_omni={is_qwen_omni}, is_qwen_platform={is_qwen_platform}")
                
                # 获取用户配置的 API 格式
                api_format = voice_config.get("api_format", "openai")
                
                # qwen 平台（包括 omni 模型）使用 STT API
                # 其他多模态模型使用 Chat API
                use_chat_api = (
                    not is_qwen_omni and  # qwen-omni 用 STT API
                    not is_qwen_platform and  # qwen 平台用 STT API
                    (
                        platform.startswith("custom_") or
                        "openrouter" in base_url.lower() or
                        "gemini" in model_lower or
                        "claude" in model_lower or
                        "gpt-4" in model_lower
                    )
                )
                
                # 检测是否使用原生 Gemini API 格式
                # 优先使用用户配置的 api_format，其次根据 URL 和模型名推断
                is_gemini_native = (
                    api_format == "gemini" or  # 用户明确配置为 Gemini 格式
                    (
                        "gemini" in model_lower and
                        (
                            "generativelanguage.googleapis.com" in base_url.lower() or
                            # 自定义中转 API 通常不包含 openrouter，且模型名包含 gemini
                            (platform.startswith("custom_") and "openrouter" not in base_url.lower() and api_format != "openai")
                        )
                    )
                )
                
                logger.info(f"[LearningAgent] 语音转录路由结果: use_chat_api={use_chat_api}, is_gemini_native={is_gemini_native}, api_format={api_format}")
                
                if is_gemini_native:
                    # 使用原生 Gemini API 格式（inline_data）
                    return await self._transcribe_via_gemini_native_api(
                        client, audio_data, audio_format, mime_type,
                        base_url, api_key, model
                    )
                elif use_chat_api:
                    # 使用 Chat Completions API（OpenRouter 等 OpenAI 兼容格式）
                    return await self._transcribe_via_chat_api(
                        client, audio_data, audio_format, mime_type,
                        base_url, api_key, model
                    )
                else:
                    # 使用传统 STT API
                    return await self._transcribe_via_stt_api(
                        client, audio_data, audio_format, mime_type,
                        base_url, api_key, platform
                    )
                
        except Exception as e:
            logger.error(f"[LearningAgent] 语音转录失败: {e}")
            raise
    
    async def _download_and_encode_audio(self, voice_url: str) -> tuple:
        """
        下载音频并编码为 base64
        
        Args:
            voice_url: 语音文件 URL
            
        Returns:
            (audio_base64, audio_format) 元组
        """
        import httpx
        import base64
        from ..config import get_http_client_kwargs
        
        logger.info(f"[LearningAgent] 下载音频: {voice_url[:50]}...")
        
        async with httpx.AsyncClient(**get_http_client_kwargs(60.0)) as client:
            audio_response = await client.get(voice_url, follow_redirects=True)
            if audio_response.status_code != 200:
                raise ValueError(f"下载音频失败: HTTP {audio_response.status_code}")
            
            audio_data = audio_response.content
            content_type = audio_response.headers.get("content-type", "")
            
            # 推断文件格式
            if "mp3" in content_type or voice_url.endswith(".mp3"):
                audio_format = "mp3"
            elif "wav" in content_type or voice_url.endswith(".wav"):
                audio_format = "wav"
            elif "silk" in voice_url or "amr" in content_type:
                audio_format = "mp3"
            else:
                audio_format = "mp3"
            
            # Base64 编码
            audio_base64 = base64.b64encode(audio_data).decode("utf-8")
            
            logger.info(f"[LearningAgent] 音频下载完成: format={audio_format}, size={len(audio_data)} bytes")
            
            return audio_base64, audio_format
    
    async def _transcribe_via_gemini_native_api(
        self,
        client,
        audio_data: bytes,
        audio_format: str,
        mime_type: str,
        base_url: str,
        api_key: str,
        model: str,
    ) -> str:
        """
        通过原生 Gemini API 格式转录语音
        
        使用 /v1beta/models/{model}:generateContent 端点
        音频以 base64 编码通过 inline_data 传递
        
        请求格式：
        {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": "请转录这段音频"},
                    {"inline_data": {"mime_type": "audio/mp3", "data": "base64..."}}
                ]
            }]
        }
        """
        import base64
        
        # Base64 编码音频
        audio_base64 = base64.b64encode(audio_data).decode("utf-8")
        
        logger.info(f"[LearningAgent] 使用原生 Gemini API 转录，音频大小: {len(audio_data)} bytes, 格式: {audio_format}")
        
        # 构建请求 URL
        # 原生 Gemini API: /v1beta/models/{model}:generateContent?key={api_key}
        # 中转 API 可能是: {base_url}/v1beta/models/{model}:generateContent?key={api_key}
        base_url_clean = base_url.rstrip('/')
        
        # 移除可能存在的 /v1 后缀（用户可能配置了 OpenAI 兼容格式的 base_url）
        if base_url_clean.endswith('/v1'):
            base_url_clean = base_url_clean[:-3]
        
        gemini_url = f"{base_url_clean}/v1beta/models/{model}:generateContent?key={api_key}"
        
        headers = {
            "Content-Type": "application/json",
        }
        
        # 构建原生 Gemini 格式的请求体
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": "请将这段音频转录为文字，只输出转录的文字内容，不要添加任何解释或额外内容。"
                        },
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": audio_base64
                            }
                        }
                    ]
                }
            ]
        }
        
        logger.info(f"[LearningAgent] Gemini Native API URL: {gemini_url[:80]}...")
        
        response = await client.post(
            gemini_url,
            headers=headers,
            json=payload,
            timeout=90.0,
        )
        
        if response.status_code != 200:
            error_text = response.text[:300] if response.text else "未知错误"
            logger.error(f"[LearningAgent] Gemini Native API 转录失败: {response.status_code} - {error_text}")
            raise ValueError(f"语音转文本失败: {error_text}")
        
        result = response.json()
        
        # 提取转录文本（原生 Gemini 响应格式）
        # 响应格式: {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}
        candidates = result.get("candidates", [])
        if candidates:
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if parts:
                text = parts[0].get("text", "")
                logger.info(f"[LearningAgent] Gemini Native API 转录成功: {text[:50]}...")
                return text.strip()
        
        raise ValueError("语音转文本失败: Gemini 响应中没有内容")

    async def _transcribe_via_chat_api(
        self,
        client,
        audio_data: bytes,
        audio_format: str,
        mime_type: str,
        base_url: str,
        api_key: str,
        model: str,
    ) -> str:
        """
        通过 Chat Completions API 转录语音（适用于 OpenRouter、Gemini 等多模态模型）
        
        音频以 base64 编码通过 input_audio 内容类型发送
        """
        import base64
        
        # Base64 编码音频
        audio_base64 = base64.b64encode(audio_data).decode("utf-8")
        
        logger.info(f"[LearningAgent] 使用 Chat API 转录，音频大小: {len(audio_data)} bytes, 格式: {audio_format}")
        
        # 构建请求
        chat_url = f"{base_url.rstrip('/')}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        # 构建多模态消息（包含音频）
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "请将这段音频转录为文字，只输出转录的文字内容，不要添加任何解释或额外内容。"
                        },
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_base64,
                                "format": audio_format,
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 2000,
        }
        
        response = await client.post(
            chat_url,
            headers=headers,
            json=payload,
            timeout=90.0,
        )
        
        if response.status_code != 200:
            error_text = response.text[:300] if response.text else "未知错误"
            logger.error(f"[LearningAgent] Chat API 转录失败: {response.status_code} - {error_text}")
            raise ValueError(f"语音转文本失败: {error_text}")
        
        result = response.json()
        
        # 提取转录文本
        choices = result.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            text = message.get("content", "")
            logger.info(f"[LearningAgent] Chat API 转录成功: {text[:50]}...")
            return text.strip()
        
        raise ValueError("语音转文本失败: 响应中没有内容")
    
    async def _transcribe_via_stt_api(
        self,
        client,
        audio_data: bytes,
        audio_format: str,
        mime_type: str,
        base_url: str,
        api_key: str,
        platform: str,
    ) -> str:
        """
        通过传统 STT API 转录语音（适用于 OpenAI Whisper、通义千问等）
        """
        logger.info(f"[LearningAgent] 使用 STT API 转录，平台: {platform}")
        
        # 根据平台选择 STT API
        if platform == "qwen":
            transcription_url = f"{base_url}/audio/transcriptions"
            stt_model = "paraformer-v2"
        elif platform == "openai":
            transcription_url = f"{base_url}/audio/transcriptions"
            stt_model = "whisper-1"
        else:
            transcription_url = f"{base_url}/audio/transcriptions"
            stt_model = "whisper-1"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
        }
        
        filename = f"audio.{audio_format}"
        files = {
            "file": (filename, audio_data, mime_type),
        }
        data = {
            "model": stt_model,
        }
        
        response = await client.post(
            transcription_url,
            headers=headers,
            files=files,
            data=data,
            timeout=60.0,
        )
        
        if response.status_code != 200:
            error_text = response.text[:200] if response.text else "未知错误"
            raise ValueError(f"语音转文本失败: {error_text}")
        
        result = response.json()
        text = result.get("text", "")
        
        logger.info(f"[LearningAgent] STT API 转录成功: {text[:50]}...")
        return text
    
    async def chat(
        self,
        message: str = None,
        multimodal: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        与 Agent 对话（非流式）- 支持多模态
        
        Args:
            message: 纯文本消息（向后兼容）
            multimodal: 多模态消息 {text, image_url, image_base64, voice_url, voice_text}
            context: 额外上下文（如当前阅读的内容）
            
        Returns:
            Agent 回复
        """
        # 智能模型路由：根据消息类型获取合适的 LLM（需要先获取，才能知道是否支持多模态）
        llm = await self._get_llm_for_message(multimodal)
        
        # 判断当前模型是否支持多模态（用户配置了多模态模型）
        is_multimodal_model = (
            self._current_model_info and 
            self._current_model_info.get("is_user_config", False)
        )
        
        # 检查是否有图片
        has_image = multimodal and (multimodal.get("image_url") or multimodal.get("image_base64"))
        
        logger.info(f"[LearningAgent] 多模态判断: is_multimodal_model={is_multimodal_model}, has_image={has_image}, model_info={self._current_model_info}")
        
        # 用于直接发送给模型的音频数据
        voice_base64 = None
        voice_format = "mp3"
        
        # 标记是否进行了语音转录（转录后需要重新选择文本模型）
        did_voice_transcription = False
        
        # 检查当前 LLM 是否是 ChatGeminiCustom（可以直接处理音频）
        from .gemini_chat import ChatGeminiCustom
        is_gemini_llm = isinstance(llm, ChatGeminiCustom)
        
        # 构建消息内容
        if multimodal:
            # 如果有语音 URL，检查是否需要转录
            if multimodal.get("voice_url") and not multimodal.get("voice_text"):
                # 获取语音模型配置，检查是否支持直接音频输入
                voice_config = await ModelConfigService.get_model_for_type(
                    openid=self.user_id,
                    model_type="voice",
                )
                model_types = voice_config.get("model_types", [])
                api_format = voice_config.get("api_format", "openai")
                
                # 检查模型是否同时支持 text 和 voice（可以直接处理音频）
                supports_direct_audio = "text" in model_types and "voice" in model_types
                
                logger.info(f"[LearningAgent] 语音模型能力检查: model_types={model_types}, supports_direct_audio={supports_direct_audio}, api_format={api_format}, is_gemini_llm={is_gemini_llm}")
                
                # ChatGeminiCustom 支持直接处理音频，不需要转录
                if is_gemini_llm and supports_direct_audio:
                    # 下载音频并编码为 base64，直接发送给 Gemini
                    logger.info("[LearningAgent] 使用 ChatGeminiCustom 直接处理音频")
                    voice_base64, voice_format = await self._download_and_encode_audio(multimodal["voice_url"])
                else:
                    # ChatOpenAI 不支持 input_audio 内容类型，需要先转录
                    # 即使模型支持直接音频输入（如 qwen-omni），也需要先转录为文本
                    logger.info("[LearningAgent] 使用转录模式处理语音")
                    try:
                        transcribed = await self._transcribe_voice(multimodal["voice_url"])
                        multimodal["voice_text"] = transcribed
                        did_voice_transcription = True
                    except Exception as e:
                        logger.error(f"[LearningAgent] 语音转录失败，降级到文本: {e}")
            
            content = self._build_multimodal_content(
                multimodal, 
                is_multimodal_model or is_gemini_llm,  # Gemini 也支持多模态
                voice_base64=voice_base64,
                voice_format=voice_format,
            )
            # 用于记录的文本消息
            text_for_log = multimodal.get("text") or multimodal.get("voice_text") or "[多模态消息]"
        else:
            content = message
            text_for_log = message
        
        # 语音转录后，如果使用的是 ChatOpenAI，需要重新获取文本模型进行对话
        # 因为语音模型可能使用非 OpenAI 兼容的 API 格式
        # 但如果是 ChatGeminiCustom，则不需要切换（它本身就支持对话）
        if did_voice_transcription and not is_gemini_llm:
            logger.info("[LearningAgent] 语音转录完成，重新获取文本模型进行对话")
            # 清除缓存的语音模型 LLM，强制重新获取文本模型
            cache_key = f"{self.user_id}:voice"
            if cache_key in self._llm_cache:
                del self._llm_cache[cache_key]
            # 获取文本模型（传入 None 表示纯文本消息）
            llm = await self._get_llm_for_message(None)
            logger.info(f"[LearningAgent] 切换到文本模型: {self._current_model_info}")
        
        # 创建/更新 Agent（使用选定的 LLM）
        self._create_agent(llm)
        
        # 准备输入
        input_data = self._prepare_input(text_for_log, context)
        
        # 配置线程 ID（用于多轮对话）
        config = {"configurable": {"thread_id": self.user_id}}
        
        # 构建消息列表
        messages = [HumanMessage(content=content)]
        
        # 如果有系统提示，添加上下文
        if input_data.get("user_profile"):
            system_content = self._build_system_message(input_data)
            messages.insert(0, SystemMessage(content=system_content))
        
        # 执行 Agent
        result = await self.agent.ainvoke(
            {"messages": messages},
            config=config,
        )
        
        # 提取最终回复
        output = ""
        if result.get("messages"):
            last_message = result["messages"][-1]
            if hasattr(last_message, 'content'):
                output = last_message.content
        
        # 保存对话记录
        await self.memory.add_message("user", text_for_log)
        await self.memory.add_message("assistant", output)
        
        # 分析并更新用户画像
        await self._analyze_and_evolve(text_for_log, {"output": output})
        
        return output
    
    async def chat_stream(
        self,
        message: str = None,
        multimodal: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        与 Agent 对话（流式）- 支持多模态
        
        使用 LangGraph 的 astream_events API 实现流式输出
        返回结构化的事件对象，便于前端解析展示
        
        Args:
            message: 纯文本消息（向后兼容）
            multimodal: 多模态消息 {text, image_url, image_base64, voice_url, voice_text}
            context: 额外上下文
            
        Yields:
            结构化的事件对象:
            - type: "text" | "tool_start" | "tool_end" | "tool_error" | "thinking" | "transcription" | "model_info"
            - content: 文本内容
            - tool_name: 工具名称（工具事件时）
            - tool_input: 工具输入参数（tool_start 时）
            - tool_output: 工具输出结果（tool_end 时）
            - text: 语音转录文本（transcription 事件时）
            - model_info: 当前使用的模型信息（model_info 事件时）
        """
        # 智能模型路由：根据消息类型获取合适的 LLM（需要先获取，才能知道是否支持多模态）
        llm = await self._get_llm_for_message(multimodal)
        
        # 判断当前模型是否支持多模态（用户配置了多模态模型）
        is_multimodal_model = (
            self._current_model_info and 
            self._current_model_info.get("is_user_config", False)
        )
        
        # 检查是否有图片
        has_image = multimodal and (multimodal.get("image_url") or multimodal.get("image_base64"))
        
        logger.info(f"[LearningAgent] 流式多模态判断: is_multimodal_model={is_multimodal_model}, has_image={has_image}, model_info={self._current_model_info}")
        
        # 用于直接发送给模型的音频数据
        voice_base64 = None
        voice_format = "mp3"
        
        # 标记是否进行了语音转录（转录后需要重新选择文本模型）
        did_voice_transcription = False
        
        # 检查当前 LLM 是否是 ChatGeminiCustom（可以直接处理音频）
        from .gemini_chat import ChatGeminiCustom
        is_gemini_llm = isinstance(llm, ChatGeminiCustom)
        
        # 构建消息内容
        if multimodal:
            # 如果有语音 URL，检查是否需要转录
            if multimodal.get("voice_url") and not multimodal.get("voice_text"):
                # 获取语音模型配置，检查是否支持直接音频输入
                voice_config = await ModelConfigService.get_model_for_type(
                    openid=self.user_id,
                    model_type="voice",
                )
                model_types = voice_config.get("model_types", [])
                api_format = voice_config.get("api_format", "openai")
                
                # 检查模型是否同时支持 text 和 voice（可以直接处理音频）
                supports_direct_audio = "text" in model_types and "voice" in model_types
                
                logger.info(f"[LearningAgent] 语音模型能力检查: model_types={model_types}, supports_direct_audio={supports_direct_audio}, api_format={api_format}, is_gemini_llm={is_gemini_llm}")
                
                # ChatGeminiCustom 支持直接处理音频，不需要转录
                if is_gemini_llm and supports_direct_audio:
                    # 下载音频并编码为 base64，直接发送给 Gemini
                    logger.info("[LearningAgent] 使用 ChatGeminiCustom 直接处理音频")
                    voice_base64, voice_format = await self._download_and_encode_audio(multimodal["voice_url"])
                    # 发送提示事件（告知用户正在处理音频）
                    yield {"type": "thinking", "content": "正在处理语音..."}
                else:
                    # ChatOpenAI 不支持 input_audio 内容类型，需要先转录
                    logger.info("[LearningAgent] 使用转录模式处理语音")
                    try:
                        transcribed = await self._transcribe_voice(multimodal["voice_url"])
                        multimodal["voice_text"] = transcribed
                        did_voice_transcription = True
                        # 发送转录事件
                        yield {"type": "transcription", "text": transcribed}
                    except Exception as e:
                        logger.error(f"[LearningAgent] 语音转录失败: {e}")
                        yield {"type": "error", "error": f"语音转录失败: {str(e)}"}
                        return
            
            content = self._build_multimodal_content(
                multimodal, 
                is_multimodal_model or is_gemini_llm,  # Gemini 也支持多模态
                voice_base64=voice_base64,
                voice_format=voice_format,
            )
            # 用于记录的文本消息
            text_for_log = multimodal.get("text") or multimodal.get("voice_text") or "[多模态消息]"
        else:
            content = message
            text_for_log = message
        
        # 语音转录后，如果使用的是 ChatOpenAI，需要重新获取文本模型进行对话
        # 因为语音模型可能使用非 OpenAI 兼容的 API 格式
        # 但如果是 ChatGeminiCustom，则不需要切换（它本身就支持对话）
        if did_voice_transcription and not is_gemini_llm:
            logger.info("[LearningAgent] 语音转录完成，重新获取文本模型进行对话")
            # 清除缓存的语音模型 LLM，强制重新获取文本模型
            cache_key = f"{self.user_id}:voice"
            if cache_key in self._llm_cache:
                del self._llm_cache[cache_key]
            # 获取文本模型（传入 None 表示纯文本消息）
            llm = await self._get_llm_for_message(None)
            logger.info(f"[LearningAgent] 切换到文本模型: {self._current_model_info}")
        
        # 创建/更新 Agent（使用选定的 LLM）
        self._create_agent(llm)
        
        # 发送模型信息事件（让前端知道使用了哪个模型）
        if self._current_model_info:
            yield {
                "type": "model_info",
                "model_info": self._current_model_info,
            }
        
        # 准备输入
        input_data = self._prepare_input(text_for_log, context)
        
        # 配置
        config = {"configurable": {"thread_id": self.user_id}}
        
        # 构建消息
        messages = [HumanMessage(content=content)]
        if input_data.get("user_profile"):
            system_content = self._build_system_message(input_data)
            messages.insert(0, SystemMessage(content=system_content))
        
        full_response = ""
        current_tool_calls = {}  # 追踪当前工具调用
        
        # 使用 astream_events 进行流式处理
        async for event in self.agent.astream_events(
            {"messages": messages},
            config=config,
            version="v2",
        ):
            kind = event["event"]
            
            # 处理 LLM 流式输出
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, 'content') and chunk.content:
                    content_chunk = chunk.content
                    full_response += content_chunk
                    yield {"type": "text", "content": content_chunk}
            
            # 处理工具调用开始
            elif kind == "on_tool_start":
                tool_name = event.get("name", "unknown")
                tool_input = event.get("data", {}).get("input", {})
                run_id = event.get("run_id", "")
                
                # 获取工具的中文名称和描述
                tool_info = self._get_tool_display_info(tool_name)
                
                current_tool_calls[run_id] = {
                    "name": tool_name,
                    "display_name": tool_info["display_name"],
                    "description": tool_info["description"],
                    "icon": tool_info["icon"],
                    "input": tool_input,
                }
                
                yield {
                    "type": "tool_start",
                    "tool_name": tool_name,
                    "display_name": tool_info["display_name"],
                    "description": tool_info["description"],
                    "icon": tool_info["icon"],
                    "tool_input": tool_input,
                    "run_id": run_id,
                }
            
            # 处理工具调用结束
            elif kind == "on_tool_end":
                run_id = event.get("run_id", "")
                tool_output = event.get("data", {}).get("output", "")
                
                tool_call_info = current_tool_calls.get(run_id, {})
                tool_name = tool_call_info.get("name", "unknown")
                
                # 解析工具输出
                parsed_output = self._parse_tool_output(tool_output)
                
                yield {
                    "type": "tool_end",
                    "tool_name": tool_name,
                    "display_name": tool_call_info.get("display_name", tool_name),
                    "icon": tool_call_info.get("icon", "🔧"),
                    "tool_output": parsed_output,
                    "success": parsed_output.get("success", True),
                    "run_id": run_id,
                }
                
                # 清理已完成的工具调用
                if run_id in current_tool_calls:
                    del current_tool_calls[run_id]
            
            # 处理工具调用错误
            elif kind == "on_tool_error":
                run_id = event.get("run_id", "")
                error = event.get("data", {}).get("error", "未知错误")
                
                tool_call_info = current_tool_calls.get(run_id, {})
                
                yield {
                    "type": "tool_error",
                    "tool_name": tool_call_info.get("name", "unknown"),
                    "display_name": tool_call_info.get("display_name", "工具"),
                    "icon": tool_call_info.get("icon", "🔧"),
                    "error": str(error),
                    "run_id": run_id,
                }
        
        # 保存对话记录
        await self.memory.add_message("user", text_for_log)
        await self.memory.add_message("assistant", full_response)
        
        # 异步分析并进化
        await self._analyze_and_evolve(text_for_log, {"output": full_response})
    
    def _get_tool_display_info(self, tool_name: str) -> Dict[str, str]:
        """获取工具的显示信息（中文名称、描述、图标）"""
        tool_info_map = {
            # 学习计划相关
            "create_learning_plan": {"display_name": "创建学习计划", "description": "为你制定个性化学习计划", "icon": "📋"},
            "generate_daily_tasks": {"display_name": "生成今日任务", "description": "生成每日学习任务", "icon": "📝"},
            
            # 搜索相关
            "search_resources": {"display_name": "联网搜索", "description": "在网上搜索相关资料", "icon": "🔍"},
            "search_learning_materials": {"display_name": "搜索学习资料", "description": "搜索学习相关材料", "icon": "📚"},
            
            # 任务管理
            "get_today_tasks": {"display_name": "获取今日任务", "description": "查看今天的学习任务", "icon": "📋"},
            "complete_task": {"display_name": "完成任务", "description": "标记任务为已完成", "icon": "✅"},
            "get_task_progress": {"display_name": "任务进度", "description": "查看任务完成进度", "icon": "📊"},
            "suggest_task_adjustment": {"display_name": "调整建议", "description": "建议调整任务安排", "icon": "💡"},
            
            # 打卡系统
            "do_checkin": {"display_name": "学习打卡", "description": "执行学习打卡签到", "icon": "✨"},
            "get_checkin_status": {"display_name": "打卡状态", "description": "查看打卡统计", "icon": "📈"},
            "get_badges": {"display_name": "成就徽章", "description": "查看获得的徽章", "icon": "🏅"},
            
            # 番茄专注
            "get_focus_stats": {"display_name": "专注统计", "description": "查看专注时间统计", "icon": "🍅"},
            "suggest_focus_plan": {"display_name": "专注计划", "description": "建议专注计划安排", "icon": "⏱️"},
            
            # 错题本
            "get_mistakes": {"display_name": "错题列表", "description": "查看错题本", "icon": "📕"},
            "add_mistake": {"display_name": "添加错题", "description": "添加新错题", "icon": "➕"},
            "analyze_mistake": {"display_name": "错题分析", "description": "AI分析错题原因", "icon": "🔬"},
            "generate_review_questions": {"display_name": "生成练习题", "description": "生成复习题目", "icon": "📝"},
            "mark_mistake_mastered": {"display_name": "标记已掌握", "description": "标记错题为已掌握", "icon": "🎯"},
            
            # 统计分析
            "get_learning_stats": {"display_name": "学习统计", "description": "获取学习数据统计", "icon": "📊"},
            "get_ranking": {"display_name": "排行榜", "description": "查看学习排行榜", "icon": "🏆"},
            "get_achievement_rate": {"display_name": "达成率", "description": "查看目标达成率", "icon": "🎯"},
            "analyze_learning_pattern": {"display_name": "学习分析", "description": "分析学习模式", "icon": "📈"},
            "get_calendar_data": {"display_name": "日历数据", "description": "查看日历学习详情", "icon": "📅"},
            "analyze_learning_status": {"display_name": "状态分析", "description": "分析整体学习状态", "icon": "💡"},
            
            # 用户画像
            "update_user_profile": {"display_name": "更新画像", "description": "更新用户学习画像", "icon": "👤"},
            "get_user_stats": {"display_name": "用户统计", "description": "获取用户统计信息", "icon": "📋"},
            
            # 文档伴读
            "get_documents": {"display_name": "文档列表", "description": "获取学习文档列表", "icon": "📚"},
            "search_documents": {"display_name": "搜索文档", "description": "搜索学习文档", "icon": "🔎"},
            "get_document_stats": {"display_name": "文档统计", "description": "获取文档统计信息", "icon": "📊"},
            "get_recent_documents": {"display_name": "最近文档", "description": "获取最近阅读的文档", "icon": "📖"},
        }
        
        return tool_info_map.get(tool_name, {
            "display_name": tool_name,
            "description": "执行操作",
            "icon": "🔧"
        })
    
    def _parse_tool_output(self, output: Any) -> Dict[str, Any]:
        """
        解析工具输出，转换为结构化数据
        
        LangChain 工具可能返回多种格式：
        1. 字符串
        2. dict
        3. ToolMessage 对象（有 content 属性）
        4. ToolMessage 的字符串表示 "content='...' name='...' tool_call_id='...'"
        """
        # 如果是 LangChain 的消息对象，提取 content
        if hasattr(output, 'content'):
            content = output.content
            return {"success": True, "message": content}
        
        if isinstance(output, str):
            # 检查是否是 ToolMessage 的字符串表示
            # 格式类似: content='...' name='...' tool_call_id='...'
            if output.startswith("content='") or "content='" in output:
                try:
                    # 提取 content 字段的值
                    import re
                    # 匹配 content='...' 或 content="..."
                    match = re.search(r"content=['\"](.+?)['\"](?:\s+name=|\s*$)", output, re.DOTALL)
                    if match:
                        content = match.group(1)
                        # 处理转义字符
                        content = content.replace('\\n', '\n').replace("\\'", "'").replace('\\"', '"')
                        return {"success": True, "message": content}
                except Exception:
                    pass
            
            # 尝试解析为 JSON
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                return {"success": True, "message": output}
        
        elif isinstance(output, dict):
            # 如果 dict 包含 content 字段，提取出来
            if 'content' in output:
                return {"success": True, "message": output['content']}
            return output
        
        else:
            return {"success": True, "data": str(output)}
    
    def _build_system_message(self, input_data: Dict[str, Any]) -> str:
        """构建系统消息内容"""
        template = (
            LEARNING_COACH_PROMPT if self.mode == "coach"
            else READING_COMPANION_PROMPT
        )
        
        return template.format(
            user_profile=input_data.get("user_profile", "新用户"),
            conversation_summary=input_data.get("conversation_summary", "新对话"),
            current_time=input_data.get("current_time", ""),
            reading_context=input_data.get("reading_context", "无"),
        )
    
    def _prepare_input(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """准备 Agent 输入"""
        from datetime import datetime
        
        # 获取用户画像
        user_profile = self.memory.get_user_profile_summary()
        
        # 获取对话摘要
        conversation_summary = self.memory.get_conversation_summary()
        
        # 获取聊天历史
        chat_history = self.memory.get_chat_history(limit=10)
        
        # 构建输入
        input_data = {
            "input": message,
            "chat_history": chat_history,
            "user_profile": user_profile,
            "conversation_summary": conversation_summary,
            "current_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        
        # 添加模式特定的上下文
        if self.mode == "reader" and context:
            input_data["reading_context"] = json.dumps(
                context, ensure_ascii=False, indent=2
            )
        else:
            input_data["reading_context"] = "无"
        
        return input_data
    
    async def _analyze_and_evolve(
        self,
        user_message: str,
        result: Dict[str, Any],
    ):
        """
        分析对话并更新用户画像（进化机制）
        
        这是 Agent 自我进化的核心：
        1. 分析用户的学习偏好
        2. 识别用户的知识水平
        3. 记录用户的兴趣领域
        4. 优化交互策略
        """
        try:
            # 提取关键信息
            insights = await self._extract_insights(user_message, result)
            
            if insights:
                # 更新用户画像
                await self.memory.update_user_profile(insights)
                
        except Exception as e:
            # 进化失败不影响主流程
            print(f"进化分析失败: {e}")
    
    async def _extract_insights(
        self,
        user_message: str,
        result: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """从对话中提取用户洞察"""
        # 使用当前 LLM 分析对话（如果没有则使用默认）
        llm = self._current_llm
        if not llm:
            # 获取默认文本模型
            llm = await self._get_llm_for_message(None)
        
        analysis_prompt = f"""分析以下对话，提取用户学习相关的洞察：

用户消息: {user_message}
助手回复: {result.get('output', '')[:500]}

请以 JSON 格式返回洞察（如果没有有价值的洞察返回 null）：
{{
    "learning_style": "用户的学习风格偏好（如有）",
    "knowledge_level": "用户在某领域的知识水平（如有）",
    "interests": ["用户感兴趣的主题（如有）"],
    "pain_points": ["用户遇到的困难（如有）"],
    "preferences": "用户的交互偏好（如有）"
}}

只返回 JSON，不要其他内容。如果没有有价值的洞察，返回 null。
"""
        
        try:
            response = await llm.ainvoke([HumanMessage(content=analysis_prompt)])
            content = response.content.strip()
            
            if content and content != "null":
                # 尝试解析 JSON
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                
                return json.loads(content)
        except Exception:
            pass
        
        return None
    
    async def get_suggestions(self) -> List[str]:
        """
        根据用户画像生成个性化建议
        
        这是进化机制的体现之一：根据积累的用户数据提供更好的建议
        """
        profile = self.memory.get_user_profile()
        
        if not profile:
            return [
                "开始制定你的学习计划吧！",
                "告诉我你想学什么",
                "上传一张题目图片，我来帮你解答",
            ]
        
        # 使用当前 LLM 或获取默认文本模型
        llm = self._current_llm
        if not llm:
            llm = await self._get_llm_for_message(None)
        
        # 根据用户画像生成个性化建议
        suggestions_prompt = f"""根据以下用户画像，生成3条个性化的学习建议：

用户画像:
{json.dumps(profile, ensure_ascii=False, indent=2)}

要求：
1. 建议要具体可执行
2. 与用户的学习目标相关
3. 考虑用户的学习风格

以 JSON 数组格式返回，每条建议不超过20个字：
["建议1", "建议2", "建议3"]
"""
        
        try:
            response = await llm.ainvoke([HumanMessage(content=suggestions_prompt)])
            return json.loads(response.content.strip())
        except Exception:
            return ["继续加油学习！", "保持学习节奏", "有问题随时问我"]
