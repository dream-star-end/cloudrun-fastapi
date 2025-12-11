"""
用户相关工具
"""

import json
from typing import Optional, Type, List, TYPE_CHECKING
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    from ..memory import AgentMemory


class UpdateUserProfileInput(BaseModel):
    """更新用户画像的输入参数"""
    learning_goal: str = Field(default="", description="新的学习目标")
    interest: str = Field(default="", description="新发现的兴趣领域")
    achievement: str = Field(default="", description="新获得的成就")
    preference: str = Field(default="", description="用户偏好（如喜欢视频学习）")


class UpdateUserProfileTool(BaseTool):
    """更新用户学习画像"""
    
    name: str = "update_user_profile"
    description: str = """更新用户的学习画像信息。
    当发现用户有新的学习目标、兴趣、成就或偏好时使用。
    这有助于提供更个性化的学习建议。"""
    args_schema: Type[BaseModel] = UpdateUserProfileInput
    
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
        learning_goal: str = "",
        interest: str = "",
        achievement: str = "",
        preference: str = "",
    ) -> str:
        """更新用户画像"""
        
        if not self.memory:
            return "无法更新用户画像"
        
        updates = []
        
        if learning_goal:
            self.memory.add_learning_goal(learning_goal)
            updates.append(f"学习目标: {learning_goal}")
        
        if interest:
            profile = self.memory.get_user_profile()
            if interest not in profile.get("interests", []):
                profile["interests"].append(interest)
            updates.append(f"兴趣领域: {interest}")
        
        if achievement:
            self.memory.add_achievement(achievement)
            updates.append(f"成就: {achievement}")
        
        if preference:
            profile = self.memory.get_user_profile()
            profile["preferences"]["noted"] = preference
            updates.append(f"偏好: {preference}")
        
        if updates:
            return f"✅ 已更新用户画像：\n" + "\n".join(f"- {u}" for u in updates)
        else:
            return "没有需要更新的信息"


class GetUserStatsInput(BaseModel):
    """获取用户统计的输入参数"""
    stat_type: str = Field(
        default="all",
        description="统计类型：goals(目标)/achievements(成就)/interests(兴趣)/all(全部)"
    )


class GetUserStatsTool(BaseTool):
    """获取用户学习统计"""
    
    name: str = "get_user_stats"
    description: str = """获取用户的学习统计信息。
    当用户想了解自己的学习数据、成就、目标进度时使用。
    可以查看学习目标、已获成就、兴趣领域等信息。"""
    args_schema: Type[BaseModel] = GetUserStatsInput
    
    user_id: str = ""
    memory: Optional["AgentMemory"] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, user_id: str, memory: "AgentMemory", **kwargs):
        super().__init__(**kwargs)
        self.user_id = user_id
        self.memory = memory
    
    def _run(self, stat_type: str = "all") -> str:
        import asyncio
        return asyncio.run(self._arun(stat_type))
    
    async def _arun(self, stat_type: str = "all") -> str:
        """获取用户统计"""
        
        if not self.memory:
            return "无法获取用户数据"
        
        profile = self.memory.get_user_profile()
        
        output_parts = ["📊 学习统计\n"]
        
        if stat_type in ["goals", "all"]:
            goals = profile.get("learning_goals", [])
            if goals:
                output_parts.append("🎯 **学习目标**")
                for i, goal in enumerate(goals, 1):
                    output_parts.append(f"   {i}. {goal}")
                output_parts.append("")
            else:
                output_parts.append("🎯 暂无设定的学习目标\n")
        
        if stat_type in ["achievements", "all"]:
            achievements = profile.get("achievements", [])
            if achievements:
                output_parts.append("🏆 **获得成就**")
                for ach in achievements[-5:]:  # 最近5个
                    output_parts.append(f"   • {ach['content']}")
                output_parts.append("")
            else:
                output_parts.append("🏆 暂无成就记录\n")
        
        if stat_type in ["interests", "all"]:
            interests = profile.get("interests", [])
            if interests:
                output_parts.append("💡 **兴趣领域**")
                output_parts.append(f"   {', '.join(interests[:10])}")
                output_parts.append("")
            else:
                output_parts.append("💡 暂未记录兴趣领域\n")
        
        if stat_type == "all":
            output_parts.append(f"📝 互动次数: {profile.get('interaction_count', 0)}")
            
            if profile.get("knowledge_levels"):
                output_parts.append("\n📈 **知识水平**")
                for domain, level in profile["knowledge_levels"].items():
                    output_parts.append(f"   • {domain}: {level}")
        
        return "\n".join(output_parts)

