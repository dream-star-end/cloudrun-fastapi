"""
学习计划相关工具
基于 LangChain 1.0 的 @tool 装饰器

LangChain 1.0 推荐使用函数式工具定义：
- 更简洁的代码
- 自动推断参数类型
- 更好的类型提示支持
"""

import json
from typing import Optional, TYPE_CHECKING
from langchain_core.tools import tool, BaseTool
from langchain_openai import ChatOpenAI

from ...config import settings
from ...services.model_config_service import ModelConfigService

if TYPE_CHECKING:
    from ..memory import AgentMemory


async def _get_text_llm(user_id: str = None, temperature: float = 0.7):
    """
    获取文本模型 LLM 实例
    
    优先使用用户配置的文本模型，否则使用系统默认配置
    """
    if user_id:
        try:
            model_config = await ModelConfigService.get_model_for_type(user_id, "text")
            if model_config.get("api_key"):
                return ChatOpenAI(
                    model=model_config["model"],
                    api_key=model_config["api_key"],
                    base_url=model_config["base_url"],
                    temperature=temperature,
                )
        except Exception:
            pass
    
    # 降级：使用系统默认配置（需要用户在小程序中配置）
    return ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,
        api_key="",  # 需要用户配置
        base_url=settings.DEEPSEEK_API_BASE,
        temperature=temperature,
    )


def create_learning_plan_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """
    创建学习计划工具的工厂函数
    
    使用闭包捕获 user_id 和 memory
    """
    
    @tool
    async def create_learning_plan(
        goal: str,
        domain: str,
        daily_hours: float = 2.0,
        current_level: str = "beginner",
        deadline: Optional[str] = None,
    ) -> str:
        """为用户创建个性化学习计划。
        
        当用户想要学习新技能、准备考试、或需要系统性学习某个领域时使用此工具。
        输入学习目标、领域、每天可用时间等信息，生成分阶段的学习计划。
        
        Args:
            goal: 学习目标，如'掌握Python基础'
            domain: 学习领域，如'编程'、'数学'、'英语'
            daily_hours: 每天可用学习时间（小时），默认2.0
            current_level: 当前水平 beginner/intermediate/advanced，默认beginner
            deadline: 目标截止日期，格式 YYYY-MM-DD（可选）
        
        Returns:
            包含学习计划的JSON格式字符串
        """
        llm = await _get_text_llm(user_id, temperature=0.7)
        
        # 获取用户画像以个性化计划
        user_profile = ""
        if memory:
            user_profile = memory.get_user_profile_summary()
        
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
            if memory:
                memory.add_learning_goal(goal)
            
            return f"✅ 学习计划已创建！\n\n{json.dumps(plan, ensure_ascii=False, indent=2)}"
            
        except json.JSONDecodeError:
            return f"学习计划：\n\n{content}"
    
    return create_learning_plan


def generate_daily_tasks_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """
    生成每日任务工具的工厂函数
    """
    
    @tool
    async def generate_daily_tasks(
        domain: str,
        available_hours: float = 2.0,
        focus_area: Optional[str] = None,
    ) -> str:
        """生成今天的学习任务清单。
        
        根据用户的学习计划、进度和可用时间，生成具体可执行的每日任务。
        适合在用户询问"今天学什么"、"帮我安排今天的学习"时使用。
        
        Args:
            domain: 学习领域
            available_hours: 今天可用的学习时间（小时），默认2.0
            focus_area: 今天想要重点学习的内容（可选）
        
        Returns:
            今日学习任务列表
        """
        llm = await _get_text_llm(user_id, temperature=0.7)
        
        # 获取用户画像
        user_profile = ""
        if memory:
            user_profile = memory.get_user_profile_summary()
        
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
    
    return generate_daily_tasks
