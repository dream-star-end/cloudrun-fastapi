"""
AI Agent 工具系统
基于 LangChain 1.0 的工具定义

工具列表：
- 学习计划工具：创建/修改学习计划
- 任务工具：生成/管理每日任务
- 搜索工具：联网搜索学习资源
- 识别工具：图片OCR、公式识别
- 分析工具：错题分析、学情分析
- 用户工具：更新用户画像
"""

from typing import List, TYPE_CHECKING
from langchain_core.tools import BaseTool

from .learning_plan import (
    create_learning_plan_tool,
    generate_daily_tasks_tool,
)
from .search import (
    search_resources_tool,
    search_learning_materials_tool,
)
from .recognize import recognize_image_tool
from .analysis import (
    analyze_mistake_tool,
    create_analyze_learning_status_tool,
)
from .user import (
    create_update_user_profile_tool,
    create_get_user_stats_tool,
)

if TYPE_CHECKING:
    from ..memory import AgentMemory


def get_all_tools(
    user_id: str,
    memory: "AgentMemory",
) -> List[BaseTool]:
    """
    获取所有可用工具
    
    LangChain 1.0 使用 @tool 装饰器定义的函数式工具
    
    Args:
        user_id: 用户ID
        memory: Agent 记忆实例
        
    Returns:
        工具列表
    """
    return [
        # 学习计划工具
        create_learning_plan_tool(user_id=user_id, memory=memory),
        generate_daily_tasks_tool(user_id=user_id, memory=memory),
        
        # 搜索工具
        search_resources_tool(),
        search_learning_materials_tool(),
        
        # 识别工具
        recognize_image_tool(),
        
        # 分析工具
        analyze_mistake_tool(),
        create_analyze_learning_status_tool(user_id=user_id, memory=memory),
        
        # 用户工具
        create_update_user_profile_tool(user_id=user_id, memory=memory),
        create_get_user_stats_tool(user_id=user_id, memory=memory),
    ]


__all__ = [
    "get_all_tools",
]
