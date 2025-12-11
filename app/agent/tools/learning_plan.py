"""
学习计划相关工具
"""

import json
from typing import Optional, Type, TYPE_CHECKING
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from ...config import settings

if TYPE_CHECKING:
    from ..memory import AgentMemory


class CreateLearningPlanInput(BaseModel):
    """创建学习计划的输入参数"""
    goal: str = Field(description="学习目标，如'掌握Python基础'")
    domain: str = Field(description="学习领域，如'编程'、'数学'、'英语'")
    daily_hours: float = Field(default=2.0, description="每天可用学习时间（小时）")
    current_level: str = Field(default="beginner", description="当前水平：beginner/intermediate/advanced")
    deadline: Optional[str] = Field(default=None, description="目标截止日期，格式 YYYY-MM-DD")


class CreateLearningPlanTool(BaseTool):
    """创建个性化学习计划"""
    
    name: str = "create_learning_plan"
    description: str = """为用户创建个性化学习计划。
    当用户想要学习新技能、准备考试、或需要系统性学习某个领域时使用此工具。
    输入学习目标、领域、每天可用时间等信息，生成分阶段的学习计划。"""
    args_schema: Type[BaseModel] = CreateLearningPlanInput
    
    user_id: str = ""
    memory: Optional["AgentMemory"] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, user_id: str, memory: "AgentMemory", **kwargs):
        super().__init__(**kwargs)
        self.user_id = user_id
        self.memory = memory
    
    def _run(self, **kwargs) -> str:
        """同步执行（不推荐）"""
        import asyncio
        return asyncio.run(self._arun(**kwargs))
    
    async def _arun(
        self,
        goal: str,
        domain: str,
        daily_hours: float = 2.0,
        current_level: str = "beginner",
        deadline: Optional[str] = None,
    ) -> str:
        """异步生成学习计划"""
        
        llm = ChatOpenAI(
            model=settings.DEEPSEEK_MODEL,
            openai_api_key=settings.DEEPSEEK_API_KEY,
            openai_api_base=settings.DEEPSEEK_API_BASE,
            temperature=0.7,
        )
        
        # 获取用户画像以个性化计划
        user_profile = ""
        if self.memory:
            user_profile = self.memory.get_user_profile_summary()
        
        prompt = f"""作为学习规划专家，请为用户创建一个详细的学习计划。

## 用户信息
- 学习目标: {goal}
- 学习领域: {domain}
- 每天可用时间: {daily_hours} 小时
- 当前水平: {current_level}
- 目标截止日期: {deadline or '无特定截止日期'}
- 用户画像: {user_profile}

## 输出要求
请生成一个JSON格式的学习计划，包含：
1. 总体概述
2. 分阶段规划（每个阶段包含目标、时长、关键任务）
3. 每周建议安排
4. 学习资源推荐

格式：
```json
{{
    "goal": "学习目标",
    "total_duration": "预计总时长",
    "phases": [
        {{
            "name": "阶段名称",
            "duration": "时长",
            "objectives": ["目标1", "目标2"],
            "key_tasks": ["任务1", "任务2"],
            "resources": ["资源1", "资源2"]
        }}
    ],
    "weekly_schedule": {{
        "weekday": "工作日安排",
        "weekend": "周末安排"
    }},
    "tips": ["学习建议1", "学习建议2"]
}}
```
"""
        
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        content = response.content
        
        # 尝试解析 JSON
        try:
            # 提取 JSON 部分
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0]
            else:
                json_str = content
            
            plan = json.loads(json_str.strip())
            
            # 记录到用户画像
            if self.memory:
                self.memory.add_learning_goal(goal)
            
            return f"✅ 学习计划已创建！\n\n{json.dumps(plan, ensure_ascii=False, indent=2)}"
            
        except json.JSONDecodeError:
            return f"学习计划：\n\n{content}"


class GenerateDailyTasksInput(BaseModel):
    """生成每日任务的输入参数"""
    domain: str = Field(description="学习领域")
    available_hours: float = Field(default=2.0, description="今天可用的学习时间（小时）")
    focus_area: Optional[str] = Field(default=None, description="今天想要重点学习的内容")


class GenerateDailyTasksTool(BaseTool):
    """生成每日学习任务"""
    
    name: str = "generate_daily_tasks"
    description: str = """生成今天的学习任务清单。
    根据用户的学习计划、进度和可用时间，生成具体可执行的每日任务。
    适合在用户询问"今天学什么"、"帮我安排今天的学习"时使用。"""
    args_schema: Type[BaseModel] = GenerateDailyTasksInput
    
    user_id: str = ""
    memory: Optional["AgentMemory"] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, user_id: str, memory: "AgentMemory", **kwargs):
        super().__init__(**kwargs)
        self.user_id = user_id
        self.memory = memory
    
    def _run(self, **kwargs) -> str:
        import asyncio
        return asyncio.run(self._arun(**kwargs))
    
    async def _arun(
        self,
        domain: str,
        available_hours: float = 2.0,
        focus_area: Optional[str] = None,
    ) -> str:
        """异步生成每日任务"""
        
        llm = ChatOpenAI(
            model=settings.DEEPSEEK_MODEL,
            openai_api_key=settings.DEEPSEEK_API_KEY,
            openai_api_base=settings.DEEPSEEK_API_BASE,
            temperature=0.7,
        )
        
        # 获取用户画像
        user_profile = ""
        if self.memory:
            user_profile = self.memory.get_user_profile_summary()
        
        prompt = f"""作为学习教练，请为用户生成今天的学习任务。

## 用户信息
- 学习领域: {domain}
- 今天可用时间: {available_hours} 小时
- 重点学习内容: {focus_area or '无特定要求'}
- 用户画像: {user_profile}

## 输出要求
生成3-5个具体可执行的学习任务，每个任务包含：
1. 任务名称
2. 预计时长（分钟）
3. 具体步骤
4. 完成标准

以清晰的列表格式输出。
"""
        
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        return f"📋 今日学习任务：\n\n{response.content}"

