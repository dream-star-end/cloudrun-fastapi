"""
用户相关工具
基于 LangChain 1.0 的 @tool 装饰器
"""

from typing import TYPE_CHECKING
from langchain_core.tools import tool, BaseTool

if TYPE_CHECKING:
    from ..memory import AgentMemory


def create_update_user_profile_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """
    创建更新用户画像工具的工厂函数
    """
    
    @tool
    async def update_user_profile(
        learning_goal: str = "",
        interest: str = "",
        achievement: str = "",
        preference: str = "",
    ) -> str:
        """更新用户的学习画像信息。
        
        当发现用户有新的学习目标、兴趣、成就或偏好时使用。
        这有助于提供更个性化的学习建议。
        
        Args:
            learning_goal: 新的学习目标
            interest: 新发现的兴趣领域
            achievement: 新获得的成就
            preference: 用户偏好（如喜欢视频学习）
        
        Returns:
            更新结果
        """
        if not memory:
            return "无法更新用户画像"
        
        updates = []
        
        if learning_goal:
            memory.add_learning_goal(learning_goal)
            updates.append(f"学习目标: {learning_goal}")
        
        if interest:
            profile = memory.get_user_profile()
            if interest not in profile.get("interests", []):
                profile["interests"].append(interest)
            updates.append(f"兴趣领域: {interest}")
        
        if achievement:
            memory.add_achievement(achievement)
            updates.append(f"成就: {achievement}")
        
        if preference:
            profile = memory.get_user_profile()
            profile["preferences"]["noted"] = preference
            updates.append(f"偏好: {preference}")
        
        if updates:
            return f"✅ 已更新用户画像：\n" + "\n".join(f"- {u}" for u in updates)
        else:
            return "没有需要更新的信息"
    
    return update_user_profile


def create_get_user_stats_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """
    创建获取用户统计工具的工厂函数
    """
    
    @tool
    async def get_user_stats(
        stat_type: str = "all",
    ) -> str:
        """获取用户的学习统计信息。
        
        当用户想了解自己的学习数据、成就、目标进度时使用。
        可以查看学习目标、已获成就、兴趣领域等信息。
        
        Args:
            stat_type: 统计类型 goals/achievements/interests/all，默认all
        
        Returns:
            用户学习统计信息
        """
        if not memory:
            return "无法获取用户数据"
        
        profile = memory.get_user_profile()
        
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
    
    return get_user_stats
