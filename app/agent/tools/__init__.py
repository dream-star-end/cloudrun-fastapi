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
- 打卡工具：打卡、打卡状态、成就徽章
- 专注工具：番茄钟统计、专注计划
- 任务管理工具：今日任务、任务完成、进度查询
- 错题本工具：错题管理、复习生成
- 统计工具：学习统计、排行榜、达成率分析
- 文档工具：文档列表、搜索、统计（文档伴读）
"""

from typing import List, TYPE_CHECKING
from langchain_core.tools import BaseTool

# 学习计划相关
from .learning_plan import (
    create_learning_plan_tool,
    generate_daily_tasks_tool,
)

# 搜索相关
from .search import (
    search_resources_tool,
    search_learning_materials_tool,
)

# 图片识别
from .recognize import create_recognize_image_tool

# 分析相关
from .analysis import (
    create_analyze_mistake_tool,
    create_analyze_learning_status_tool,
)

# 用户相关
from .user import (
    create_update_user_profile_tool,
    create_get_user_stats_tool,
)

# 打卡相关
from .checkin import (
    create_checkin_tool,
    create_get_checkin_status_tool,
    create_get_badges_tool,
)

# 专注相关
from .focus import (
    create_get_focus_stats_tool,
    create_suggest_focus_plan_tool,
)

# 任务管理相关
from .tasks import (
    create_get_today_tasks_tool,
    create_complete_task_tool,
    create_get_task_progress_tool,
    create_adjust_tasks_tool,
)

# 错题本相关
from .mistakes import (
    create_get_mistakes_tool,
    create_add_mistake_tool,
    create_generate_review_tool,
    create_mark_mastered_tool,
)

# 统计相关
from .stats import (
    create_get_learning_stats_tool,
    create_get_rank_tool,
    create_get_achievement_rate_tool,
    create_analyze_learning_pattern_tool,
    create_get_calendar_data_tool,
)

# 文档相关（文档伴读）
from .documents import (
    create_get_documents_tool,
    create_search_documents_tool,
    create_get_document_stats_tool,
    create_get_recent_documents_tool,
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
        工具列表（共27个工具）
    """
    return [
        # ==================== 学习计划工具 ====================
        create_learning_plan_tool(user_id=user_id, memory=memory),
        generate_daily_tasks_tool(user_id=user_id, memory=memory),
        
        # ==================== 搜索工具 ====================
        search_resources_tool(),
        search_learning_materials_tool(),
        
        # ==================== 识别工具 ====================
        create_recognize_image_tool(user_id=user_id, memory=memory),
        
        # ==================== 分析工具 ====================
        create_analyze_mistake_tool(user_id=user_id, memory=memory),
        create_analyze_learning_status_tool(user_id=user_id, memory=memory),
        
        # ==================== 用户工具 ====================
        create_update_user_profile_tool(user_id=user_id, memory=memory),
        create_get_user_stats_tool(user_id=user_id, memory=memory),
        
        # ==================== 打卡工具 ====================
        create_checkin_tool(user_id=user_id, memory=memory),
        create_get_checkin_status_tool(user_id=user_id, memory=memory),
        create_get_badges_tool(user_id=user_id, memory=memory),
        
        # ==================== 专注工具 ====================
        create_get_focus_stats_tool(user_id=user_id, memory=memory),
        create_suggest_focus_plan_tool(user_id=user_id, memory=memory),
        
        # ==================== 任务管理工具 ====================
        create_get_today_tasks_tool(user_id=user_id, memory=memory),
        create_complete_task_tool(user_id=user_id, memory=memory),
        create_get_task_progress_tool(user_id=user_id, memory=memory),
        create_adjust_tasks_tool(user_id=user_id, memory=memory),
        
        # ==================== 错题本工具 ====================
        create_get_mistakes_tool(user_id=user_id, memory=memory),
        create_add_mistake_tool(user_id=user_id, memory=memory),
        create_generate_review_tool(user_id=user_id, memory=memory),
        create_mark_mastered_tool(user_id=user_id, memory=memory),
        
        # ==================== 统计工具 ====================
        create_get_learning_stats_tool(user_id=user_id, memory=memory),
        create_get_rank_tool(user_id=user_id, memory=memory),
        create_get_achievement_rate_tool(user_id=user_id, memory=memory),
        create_analyze_learning_pattern_tool(user_id=user_id, memory=memory),
        create_get_calendar_data_tool(user_id=user_id, memory=memory),
        
        # ==================== 文档工具（文档伴读）====================
        create_get_documents_tool(user_id=user_id, memory=memory),
        create_search_documents_tool(user_id=user_id, memory=memory),
        create_get_document_stats_tool(user_id=user_id, memory=memory),
        create_get_recent_documents_tool(user_id=user_id, memory=memory),
    ]


__all__ = [
    "get_all_tools",
]
