"""
AI Agent 记忆系统
实现对话记忆和用户画像的持久化存储

功能：
- 短期记忆：当前对话上下文
- 长期记忆：用户画像、学习历史
- 记忆压缩：自动总结长对话
"""

from typing import Dict, Any, List
from datetime import datetime
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

# 内存存储（生产环境应替换为数据库）
_memory_store: Dict[str, Dict[str, Any]] = {}


class AgentMemory:
    """Agent 记忆管理器"""
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        self._ensure_initialized()
    
    def _ensure_initialized(self):
        """确保用户记忆已初始化"""
        if self.user_id not in _memory_store:
            _memory_store[self.user_id] = {
                "messages": [],  # 对话历史
                "user_profile": {  # 用户画像
                    "created_at": datetime.now().isoformat(),
                    "learning_goals": [],
                    "knowledge_levels": {},
                    "interests": [],
                    "learning_style": None,
                    "preferences": {},
                    "pain_points": [],
                    "achievements": [],
                    "interaction_count": 0,
                },
                "conversation_summary": "",  # 对话摘要
                "context": {},  # 临时上下文
            }
    
    @property
    def _data(self) -> Dict[str, Any]:
        """获取用户数据"""
        return _memory_store[self.user_id]
    
    # ==================== 对话历史 ====================
    
    async def add_message(self, role: str, content: str):
        """添加消息到历史"""
        self._data["messages"].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        
        # 更新交互计数
        if role == "user":
            self._data["user_profile"]["interaction_count"] += 1
        
        # 如果消息过多，自动压缩
        if len(self._data["messages"]) > 50:
            await self._compress_messages()
    
    def get_chat_history(self, limit: int = 10) -> List[BaseMessage]:
        """获取最近的对话历史（LangChain 格式）"""
        messages = self._data["messages"][-limit:]
        result = []
        
        for msg in messages:
            if msg["role"] == "user":
                result.append(HumanMessage(content=msg["content"]))
            else:
                result.append(AIMessage(content=msg["content"]))
        
        return result
    
    def get_raw_history(self, limit: int = 10) -> List[Dict[str, str]]:
        """获取原始对话历史"""
        return self._data["messages"][-limit:]
    
    async def _compress_messages(self):
        """压缩旧消息为摘要"""
        old_messages = self._data["messages"][:-20]
        
        if not old_messages:
            return
        
        # 生成摘要（这里简化处理，实际应用 LLM）
        summary_parts = []
        for msg in old_messages[-10:]:
            role = "用户" if msg["role"] == "user" else "助手"
            content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
            summary_parts.append(f"{role}: {content}")
        
        new_summary = "\n".join(summary_parts)
        
        # 合并到现有摘要
        if self._data["conversation_summary"]:
            self._data["conversation_summary"] = (
                self._data["conversation_summary"][-500:] + "\n...\n" + new_summary
            )
        else:
            self._data["conversation_summary"] = new_summary
        
        # 保留最近的消息
        self._data["messages"] = self._data["messages"][-20:]
    
    def get_conversation_summary(self) -> str:
        """获取对话摘要"""
        return self._data["conversation_summary"] or "这是新对话的开始"
    
    def clear_history(self):
        """清空对话历史"""
        self._data["messages"] = []
        self._data["conversation_summary"] = ""
    
    # ==================== 用户画像 ====================
    
    def get_user_profile(self) -> Dict[str, Any]:
        """获取完整用户画像"""
        return self._data["user_profile"]
    
    def get_user_profile_summary(self) -> str:
        """获取用户画像摘要（用于 prompt）"""
        profile = self._data["user_profile"]
        
        parts = []
        
        if profile.get("learning_goals"):
            parts.append(f"学习目标: {', '.join(profile['learning_goals'][:3])}")
        
        if profile.get("knowledge_levels"):
            levels = [f"{k}: {v}" for k, v in list(profile["knowledge_levels"].items())[:3]]
            parts.append(f"知识水平: {', '.join(levels)}")
        
        if profile.get("interests"):
            parts.append(f"兴趣领域: {', '.join(profile['interests'][:5])}")
        
        if profile.get("learning_style"):
            parts.append(f"学习风格: {profile['learning_style']}")
        
        if profile.get("pain_points"):
            parts.append(f"学习难点: {', '.join(profile['pain_points'][:3])}")
        
        parts.append(f"互动次数: {profile.get('interaction_count', 0)}")
        
        return "\n".join(parts) if parts else "新用户，暂无画像数据"
    
    async def update_user_profile(self, insights: Dict[str, Any]):
        """
        更新用户画像
        
        这是进化机制的核心：根据对话洞察持续更新用户画像
        """
        profile = self._data["user_profile"]
        
        # 更新学习风格
        if insights.get("learning_style"):
            profile["learning_style"] = insights["learning_style"]
        
        # 更新知识水平
        if insights.get("knowledge_level"):
            # 解析格式如 "Python: 初级"
            level_str = insights["knowledge_level"]
            if ":" in level_str:
                domain, level = level_str.split(":", 1)
                profile["knowledge_levels"][domain.strip()] = level.strip()
        
        # 添加兴趣
        if insights.get("interests"):
            for interest in insights["interests"]:
                if interest and interest not in profile["interests"]:
                    profile["interests"].append(interest)
            # 保持列表不过长
            profile["interests"] = profile["interests"][-20:]
        
        # 添加难点
        if insights.get("pain_points"):
            for point in insights["pain_points"]:
                if point and point not in profile["pain_points"]:
                    profile["pain_points"].append(point)
            profile["pain_points"] = profile["pain_points"][-10:]
        
        # 更新偏好
        if insights.get("preferences"):
            if isinstance(insights["preferences"], dict):
                profile["preferences"].update(insights["preferences"])
            else:
                profile["preferences"]["general"] = insights["preferences"]
        
        profile["updated_at"] = datetime.now().isoformat()
    
    def add_learning_goal(self, goal: str):
        """添加学习目标"""
        profile = self._data["user_profile"]
        if goal not in profile["learning_goals"]:
            profile["learning_goals"].append(goal)
    
    def add_achievement(self, achievement: str):
        """添加成就"""
        profile = self._data["user_profile"]
        profile["achievements"].append({
            "content": achievement,
            "time": datetime.now().isoformat(),
        })
    
    # ==================== 上下文管理 ====================
    
    def set_context(self, key: str, value: Any):
        """设置临时上下文"""
        self._data["context"][key] = value
    
    def get_context(self, key: str, default: Any = None) -> Any:
        """获取临时上下文"""
        return self._data["context"].get(key, default)
    
    def clear_context(self):
        """清空临时上下文"""
        self._data["context"] = {}
    
    # ==================== 导出/导入 ====================
    
    def export_data(self) -> Dict[str, Any]:
        """导出用户数据"""
        return {
            "user_id": self.user_id,
            "exported_at": datetime.now().isoformat(),
            "data": self._data,
        }
    
    def import_data(self, data: Dict[str, Any]):
        """导入用户数据"""
        if "data" in data:
            _memory_store[self.user_id] = data["data"]
        self._ensure_initialized()


class MemoryManager:
    """记忆管理器 - 管理所有用户的记忆"""
    
    @staticmethod
    def get_memory(user_id: str) -> AgentMemory:
        """获取用户的记忆实例"""
        return AgentMemory(user_id)
    
    @staticmethod
    def clear_user_data(user_id: str):
        """清除用户所有数据"""
        if user_id in _memory_store:
            del _memory_store[user_id]
    
    @staticmethod
    def get_all_users() -> List[str]:
        """获取所有用户ID"""
        return list(_memory_store.keys())
    
    @staticmethod
    def get_stats() -> Dict[str, Any]:
        """获取统计信息"""
        total_users = len(_memory_store)
        total_messages = sum(
            len(data.get("messages", []))
            for data in _memory_store.values()
        )
        
        return {
            "total_users": total_users,
            "total_messages": total_messages,
        }

