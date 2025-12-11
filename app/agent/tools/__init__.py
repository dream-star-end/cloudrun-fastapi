"""
AI Agent 工具系统
封装小程序中的各种功能为 LangChain Tools

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

from .learning_plan import CreateLearningPlanTool, GenerateDailyTasksTool
from .search import SearchResourcesTool, SearchLearningMaterialsTool
from .recognize import RecognizeImageTool
from .analysis import AnalyzeMistakeTool, AnalyzeLearningStatusTool
from .user import UpdateUserProfileTool, GetUserStatsTool

if TYPE_CHECKING:
    from ..memory import AgentMemory


def get_all_tools(
    user_id: str,
    memory: "AgentMemory",
) -> List[BaseTool]:
    """
    获取所有可用工具
    
    Args:
        user_id: 用户ID
        memory: Agent 记忆实例
        
    Returns:
        工具列表
    """
    return [
        # 学习计划工具
        CreateLearningPlanTool(user_id=user_id, memory=memory),
        GenerateDailyTasksTool(user_id=user_id, memory=memory),
        
        # 搜索工具
        SearchResourcesTool(),
        SearchLearningMaterialsTool(),
        
        # 识别工具
        RecognizeImageTool(),
        
        # 分析工具
        AnalyzeMistakeTool(),
        AnalyzeLearningStatusTool(user_id=user_id, memory=memory),
        
        # 用户工具
        UpdateUserProfileTool(user_id=user_id, memory=memory),
        GetUserStatsTool(user_id=user_id, memory=memory),
    ]


__all__ = [
    "get_all_tools",
    "CreateLearningPlanTool",
    "GenerateDailyTasksTool", 
    "SearchResourcesTool",
    "SearchLearningMaterialsTool",
    "RecognizeImageTool",
    "AnalyzeMistakeTool",
    "AnalyzeLearningStatusTool",
    "UpdateUserProfileTool",
    "GetUserStatsTool",
]

