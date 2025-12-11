"""
AI Agent 核心模块
基于 LangChain 1.0 + LangGraph 的智能代理

特点：
- 自主决策：根据用户意图选择合适的工具
- 多轮对话：保持上下文连贯性
- 自我反思：评估执行结果并优化策略
- 流式输出：支持实时响应
"""

import json
from typing import AsyncIterator, Optional, Dict, Any, List
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from .tools import get_all_tools
from .memory import AgentMemory
from ..config import settings


# AI 学习教练系统提示词
LEARNING_COACH_PROMPT = """你是一位专业的 AI 学习教练，名叫"小智"。你的职责是帮助用户高效学习、解决学习中的问题。

## 你的能力
你拥有以下工具，可以根据需要调用：

### 📚 学习计划
- **create_learning_plan**: 为用户创建个性化学习计划
- **generate_daily_tasks**: 生成每日学习任务

### 🔍 搜索与识别
- **search_resources**: 联网搜索学习资源和资料
- **search_learning_materials**: 搜索特定学习材料
- **recognize_image**: 识别图片内容（OCR、公式、解释等）

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

### 🔍 识别与搜索
- **recognize_image**: 识别图片中的文字、公式、图表
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

当前时间: {current_time}
"""


class LearningAgent:
    """
    AI 学习教练/伴读 Agent
    
    基于 LangChain 1.0 + LangGraph 实现
    - 使用 create_react_agent 创建 ReAct 风格的智能体
    - 支持工具调用和多轮对话
    - 内置记忆管理和用户画像
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
        
        # 初始化 LLM
        self.llm = ChatOpenAI(
            model=settings.DEEPSEEK_MODEL,
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_API_BASE,
            temperature=0.7,
            streaming=True,
        )
        
        # 获取工具
        self.tools = get_all_tools(user_id=user_id, memory=self.memory)
        
        # LangGraph 检查点（用于对话状态持久化）
        self.checkpointer = MemorySaver()
        
        # 创建 Agent
        self._create_agent()
    
    def _create_agent(self):
        """
        创建 LangGraph ReAct Agent
        
        LangChain 1.0 推荐使用 LangGraph 的 create_react_agent
        这是一个更灵活、可控的 Agent 实现方式
        
        注意：LangGraph 0.2.x+ 中 state_modifier 参数已被移除
        系统提示现在通过 SystemMessage 在 chat() 和 chat_stream() 中动态添加
        这样可以支持动态的用户画像和对话摘要注入
        """
        # 使用 LangGraph 创建 ReAct Agent
        # create_react_agent 返回一个 CompiledGraph
        # 系统提示通过 _build_system_message() 动态构建并作为 SystemMessage 添加
        self.agent = create_react_agent(
            model=self.llm,
            tools=self.tools,
            checkpointer=self.checkpointer,  # 启用对话状态持久化
        )
    
    async def chat(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        与 Agent 对话（非流式）
        
        Args:
            message: 用户消息
            context: 额外上下文（如当前阅读的内容）
            
        Returns:
            Agent 回复
        """
        # 准备输入
        input_data = self._prepare_input(message, context)
        
        # 配置线程 ID（用于多轮对话）
        config = {"configurable": {"thread_id": self.user_id}}
        
        # 构建消息列表
        messages = [HumanMessage(content=message)]
        
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
        await self.memory.add_message("user", message)
        await self.memory.add_message("assistant", output)
        
        # 分析并更新用户画像
        await self._analyze_and_evolve(message, {"output": output})
        
        return output
    
    async def chat_stream(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[str]:
        """
        与 Agent 对话（流式）
        
        使用 LangGraph 的 astream_events API 实现流式输出
        
        Args:
            message: 用户消息
            context: 额外上下文
            
        Yields:
            Agent 回复的文本块
        """
        # 准备输入
        input_data = self._prepare_input(message, context)
        
        # 配置
        config = {"configurable": {"thread_id": self.user_id}}
        
        # 构建消息
        messages = [HumanMessage(content=message)]
        if input_data.get("user_profile"):
            system_content = self._build_system_message(input_data)
            messages.insert(0, SystemMessage(content=system_content))
        
        full_response = ""
        
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
                    content = chunk.content
                    full_response += content
                    yield content
            
            # 处理工具调用开始
            elif kind == "on_tool_start":
                tool_name = event.get("name", "unknown")
                yield f"\n🔧 正在调用 {tool_name}...\n"
            
            # 处理工具调用结束
            elif kind == "on_tool_end":
                yield "\n✅ 工具调用完成\n"
        
        # 保存对话记录
        await self.memory.add_message("user", message)
        await self.memory.add_message("assistant", full_response)
        
        # 异步分析并进化
        await self._analyze_and_evolve(message, {"output": full_response})
    
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
        # 使用 LLM 分析对话
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
            response = await self.llm.ainvoke([HumanMessage(content=analysis_prompt)])
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
            response = await self.llm.ainvoke([HumanMessage(content=suggestions_prompt)])
            return json.loads(response.content.strip())
        except Exception:
            return ["继续加油学习！", "保持学习节奏", "有问题随时问我"]
