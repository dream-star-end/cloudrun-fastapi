"""
AI Agent 核心模块
基于 LangChain 1.0 的智能代理

特点：
- 自主决策：根据用户意图选择合适的工具
- 多轮对话：保持上下文连贯性
- 自我反思：评估执行结果并优化策略
"""

import json
from typing import AsyncIterator, Optional, Dict, Any, List
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage
from langchain.agents import AgentExecutor, create_openai_tools_agent

from .tools import get_all_tools
from .memory import AgentMemory
from ..config import settings


# AI 学习教练系统提示词
LEARNING_COACH_PROMPT = """你是一位专业的 AI 学习教练，名叫"小智"。你的职责是帮助用户高效学习、解决学习中的问题。

## 你的能力
你拥有以下工具，可以根据需要调用：
- **create_learning_plan**: 为用户创建个性化学习计划
- **search_resources**: 搜索学习资源和资料
- **analyze_mistake**: 分析错题，找出知识薄弱点
- **recognize_image**: 识别图片内容（OCR、公式、解释等）
- **generate_daily_tasks**: 生成每日学习任务
- **update_user_profile**: 更新用户学习画像

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

## 回复风格
- 友好亲切，像朋友一样交流
- 使用简洁的中文
- 适当使用 emoji 增加亲和力
- 给出具体可执行的建议

当前时间: {current_time}
"""

# AI 伴读助手系统提示词
READING_COMPANION_PROMPT = """你是一位智能伴读助手，名叫"小智"。你的职责是帮助用户阅读和理解各种学习材料。

## 你的能力
你拥有以下工具，可以根据需要调用：
- **recognize_image**: 识别图片中的文字、公式、图表
- **explain_content**: 解释复杂概念和知识点
- **search_resources**: 搜索相关的补充资料
- **create_notes**: 帮助整理学习笔记
- **generate_questions**: 生成练习题检验理解

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

当前时间: {current_time}
"""


class LearningAgent:
    """AI 学习教练/伴读 Agent"""
    
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
            openai_api_key=settings.DEEPSEEK_API_KEY,
            openai_api_base=settings.DEEPSEEK_API_BASE,
            temperature=0.7,
            streaming=True,
        )
        
        # 获取工具
        self.tools = get_all_tools(user_id=user_id, memory=self.memory)
        
        # 创建 Agent
        self._create_agent()
    
    def _create_agent(self):
        """创建 LangChain Agent"""
        # 选择提示词模板
        system_prompt = (
            LEARNING_COACH_PROMPT if self.mode == "coach" 
            else READING_COMPANION_PROMPT
        )
        
        # 构建提示词
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        # 创建 Agent
        agent = create_openai_tools_agent(self.llm, self.tools, prompt)
        
        # 创建执行器
        self.agent_executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=settings.DEBUG,
            max_iterations=5,  # 最大工具调用次数
            handle_parsing_errors=True,
            return_intermediate_steps=True,
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
        
        # 执行 Agent
        result = await self.agent_executor.ainvoke(input_data)
        
        # 保存对话记录
        await self.memory.add_message("user", message)
        await self.memory.add_message("assistant", result["output"])
        
        # 分析并更新用户画像
        await self._analyze_and_evolve(message, result)
        
        return result["output"]
    
    async def chat_stream(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[str]:
        """
        与 Agent 对话（流式）
        
        Args:
            message: 用户消息
            context: 额外上下文
            
        Yields:
            Agent 回复的文本块
        """
        # 准备输入
        input_data = self._prepare_input(message, context)
        
        full_response = ""
        
        # 流式执行
        async for event in self.agent_executor.astream_events(
            input_data,
            version="v2",
        ):
            kind = event["event"]
            
            # 处理 LLM 流式输出
            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    full_response += content
                    yield content
            
            # 处理工具调用通知
            elif kind == "on_tool_start":
                tool_name = event["name"]
                yield f"\n🔧 正在调用 {tool_name}...\n"
            
            elif kind == "on_tool_end":
                yield "\n✅ 工具调用完成\n"
        
        # 保存对话记录
        await self.memory.add_message("user", message)
        await self.memory.add_message("assistant", full_response)
        
        # 异步分析并进化
        await self._analyze_and_evolve(message, {"output": full_response})
    
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

