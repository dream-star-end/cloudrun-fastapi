"""
AI Agent 记忆系统 (DB 持久化版)
实现对话记忆和用户画像的持久化存储

功能：
- 短期记忆：当前对话上下文
- 长期记忆：用户画像、学习历史
- 记忆压缩：自动总结长对话
- 持久化：使用云开发数据库存储
"""

import logging
from typing import Dict, Any, List
from datetime import datetime
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from ..db.wxcloud import get_db

logger = logging.getLogger(__name__)

class AgentMemory:
    """Agent 记忆管理器"""
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        # 获取数据库实例
        self.db = get_db()
        
        # 内存缓存 (初始化为空，调用 load() 后填充)
        self._data: Dict[str, Any] = {
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
        self._loaded = False
        self._doc_id = None  # agent_memories 集合中的文档 ID
    
    async def load(self):
        """从数据库加载记忆"""
        if self._loaded:
            return

        try:
            # 1. 加载 Agent 状态 (user_profile, conversation_summary)
            # 使用 agent_memories 集合存储 Agent 专用的记忆数据
            agent_memory = await self.db.get_one("agent_memories", {"openid": self.user_id})
            
            if agent_memory:
                self._doc_id = agent_memory.get("_id")
                # 恢复数据
                if "user_profile" in agent_memory:
                    self._data["user_profile"] = agent_memory["user_profile"]
                if "conversation_summary" in agent_memory:
                    self._data["conversation_summary"] = agent_memory["conversation_summary"]
            else:
                # 初始化新的记忆文档
                logger.info(f"为用户 {self.user_id} 初始化新的 Agent 记忆")
                # 暂时不保存，等到有更新时再保存
            
            # 2. 加载最近的聊天记录 (chat_history)
            # 取最近 20 条
            messages = await self.db.query(
                "chat_history", 
                {"openid": self.user_id}, 
                limit=20, 
                order_by="timestamp", 
                order_type="desc"
            )
            # 数据库按 desc 取出的，需要反转为时间顺序
            messages.reverse()
            
            # 转换格式适配
            self._data["messages"] = []
            for msg in messages:
                self._data["messages"].append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                    "timestamp": msg.get("timestamp"),
                })
            
            self._loaded = True
            logger.info(f"用户 {self.user_id} 记忆加载完成，消息数: {len(self._data['messages'])}")
            
        except Exception as e:
            logger.error(f"加载用户记忆失败: {e}")
            # 出错时保持初始状态，避免阻塞
            self._loaded = True
            
    async def _save_agent_memory(self):
        """保存 Agent 状态到数据库"""
        data_to_save = {
            "openid": self.user_id,
            "user_profile": self._data["user_profile"],
            "conversation_summary": self._data["conversation_summary"],
            "updatedAt": {"$date": datetime.now().isoformat()}
        }
        
        try:
            if self._doc_id:
                await self.db.update_by_id("agent_memories", self._doc_id, data_to_save)
            else:
                # 检查是否存在（防止并发创建）
                existing = await self.db.get_one("agent_memories", {"openid": self.user_id})
                if existing:
                    self._doc_id = existing.get("_id")
                    await self.db.update_by_id("agent_memories", self._doc_id, data_to_save)
                else:
                    data_to_save["createdAt"] = {"$date": datetime.now().isoformat()}
                    self._doc_id = await self.db.add("agent_memories", data_to_save)
        except Exception as e:
            logger.error(f"保存 Agent 记忆失败: {e}")

    # ==================== 对话历史 ====================
    
    async def add_message(self, role: str, content: str):
        """添加消息到历史"""
        timestamp = datetime.now().isoformat()
        
        # 1. 更新内存
        self._data["messages"].append({
            "role": role,
            "content": content,
            "timestamp": timestamp,
        })
        
        # 2. 写入数据库 (chat_history)
        try:
            await self.db.add("chat_history", {
                "openid": self.user_id,
                "role": role,
                "content": content,
                "timestamp": timestamp,  # 字符串格式，兼容性好
                "createdAt": {"$date": timestamp}
            })
        except Exception as e:
            logger.error(f"保存聊天记录失败: {e}")
        
        # 更新交互计数
        if role == "user":
            if "interaction_count" not in self._data["user_profile"]:
                self._data["user_profile"]["interaction_count"] = 0
            self._data["user_profile"]["interaction_count"] += 1
            # 这是一个简单的更新，不需要每次都存库，可以累积或在 update_user_profile 时存
        
        # 如果消息过多，自动压缩
        if len(self._data["messages"]) > 10:
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
        # 保留最近的 6 条消息（3轮对话），其余的进行压缩
        keep_count = 6
        if len(self._data["messages"]) <= keep_count:
            return
            
        old_messages = self._data["messages"][:-keep_count]
        
        if not old_messages:
            return
        
        # 生成摘要（这里简化处理，实际应用 LLM）
        summary_parts = []
        for msg in old_messages:
            role = "用户" if msg["role"] == "user" else "助手"
            content = msg["content"]
            # 截断过长消息
            if len(content) > 100:
                content = content[:100] + "..."
            summary_parts.append(f"{role}: {content}")
        
        new_summary = "\n".join(summary_parts)
        
        # 合并到现有摘要
        if self._data["conversation_summary"]:
            current_summary = self._data["conversation_summary"]
            # 保持总摘要不至于无限增长
            if len(current_summary) > 1000:
                 current_summary = current_summary[-1000:]
            self._data["conversation_summary"] = (
                current_summary + "\n...\n" + new_summary
            )
        else:
            self._data["conversation_summary"] = new_summary
        
        # 更新内存中的消息列表
        self._data["messages"] = self._data["messages"][-keep_count:]
        
        # 保存状态到数据库
        await self._save_agent_memory()
    
    def get_conversation_summary(self) -> str:
        """获取对话摘要"""
        return self._data["conversation_summary"] or "这是新对话的开始"
    
    def clear_history(self):
        """清空对话历史"""
        self._data["messages"] = []
        self._data["conversation_summary"] = ""
        # 实际场景中可能需要删除数据库记录，或者只是重置 session
        # 这里仅重置内存，不删除历史聊天记录
    
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
        
        updated = False
        
        # 更新学习风格
        if insights.get("learning_style"):
            profile["learning_style"] = insights["learning_style"]
            updated = True
        
        # 更新知识水平
        if insights.get("knowledge_level"):
            level_str = insights["knowledge_level"]
            if ":" in level_str:
                domain, level = level_str.split(":", 1)
                profile["knowledge_levels"][domain.strip()] = level.strip()
                updated = True
        
        # 添加兴趣
        if insights.get("interests"):
            for interest in insights["interests"]:
                if interest and interest not in profile["interests"]:
                    profile["interests"].append(interest)
                    updated = True
            profile["interests"] = profile["interests"][-20:]
        
        # 添加难点
        if insights.get("pain_points"):
            for point in insights["pain_points"]:
                if point and point not in profile["pain_points"]:
                    profile["pain_points"].append(point)
                    updated = True
            profile["pain_points"] = profile["pain_points"][-10:]
        
        # 更新偏好
        if insights.get("preferences"):
            if isinstance(insights["preferences"], dict):
                profile["preferences"].update(insights["preferences"])
            else:
                profile["preferences"]["general"] = insights["preferences"]
            updated = True
        
        if updated:
            profile["updated_at"] = datetime.now().isoformat()
            # 保存到数据库
            await self._save_agent_memory()
    
    async def add_learning_goal(self, goal: str):
        """添加学习目标"""
        profile = self._data["user_profile"]
        if goal not in profile["learning_goals"]:
            profile["learning_goals"].append(goal)
            await self._save_agent_memory()
    
    async def add_achievement(self, achievement: str):
        """添加成就"""
        profile = self._data["user_profile"]
        profile["achievements"].append({
            "content": achievement,
            "time": datetime.now().isoformat(),
        })
        await self._save_agent_memory()
    
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

    # ==================== 兼容性方法 ====================
    # 移除 export_data/import_data 或做空实现，因为现在依赖数据库
