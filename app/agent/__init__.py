"""
AI Agent 模块
基于 LangChain 1.0 的智能代理系统

功能：
- 智能对话与任务规划
- 工具调用（学习计划、搜索、识别等）
- 长期记忆与用户画像
- 自我进化机制
"""

from .core import LearningAgent
from .memory import AgentMemory
from .tools import get_all_tools

__all__ = ["LearningAgent", "AgentMemory", "get_all_tools"]

