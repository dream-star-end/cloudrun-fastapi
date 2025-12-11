"""
番茄专注相关工具
支持 AI Agent 操作番茄钟功能
使用数据库直连
"""

from typing import Optional, TYPE_CHECKING
from langchain_core.tools import tool, BaseTool
from datetime import datetime

from ...db.wxcloud import FocusRepository, get_db

if TYPE_CHECKING:
    from ..memory import AgentMemory


def create_get_focus_stats_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """获取专注统计工具"""
    
    @tool
    async def get_focus_stats() -> str:
        """获取用户的番茄专注统计数据。
        
        当用户询问"我今天专注了多久"、"番茄钟记录"、"专注统计"时调用此工具。
        
        Returns:
            专注时间统计信息
        """
        try:
            repo = FocusRepository()
            stats = await repo.get_today_stats(user_id)
            
            today_count = stats.get("todayCount", 0)
            today_minutes = stats.get("todayMinutes", 0)
            records = stats.get("records", [])
            
            # 计算时间
            hours = today_minutes // 60
            minutes = today_minutes % 60
            time_str = f"{hours}小时{minutes}分钟" if hours > 0 else f"{minutes}分钟"
            
            result = f"""🍅 今日专注统计

📊 数据概览：
- 完成番茄数：{today_count} 个
- 专注时长：{time_str}
- 平均每个：{today_minutes // today_count if today_count > 0 else 0} 分钟
"""
            
            # 显示最近的专注记录
            if records:
                result += "\n📋 今日记录：\n"
                for record in records[:5]:
                    task = record.get("task", "专注学习")
                    duration = record.get("duration", 25)
                    result += f"  🍅 {task} ({duration}分钟)\n"
            
            # 建议
            if today_count == 0:
                result += "\n💡 今天还没有开始专注，现在开始一个番茄吧！"
            elif today_count < 4:
                result += f"\n💡 再完成 {4 - today_count} 个番茄，就能完成一轮了！"
            else:
                result += f"\n🎉 太棒了！今天已经完成了 {today_count // 4} 轮番茄！"
            
            result += "\n\n🔗 前往小程序「番茄专注」开始计时！"
            
            return result
            
        except Exception as e:
            return f"""🍅 番茄专注统计

⚠️ 获取数据失败，请在小程序中查看。

💡 番茄工作法建议：
- 标准番茄：25分钟专注 + 5分钟休息
- 深度番茄：45分钟专注 + 10分钟休息
- 每完成4个番茄，休息15-30分钟

🔗 前往小程序「番茄专注」开始计时！"""
    
    return get_focus_stats


def create_suggest_focus_plan_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """建议专注计划工具"""
    
    @tool
    async def suggest_focus_plan(
        available_time: float = 2.0,
        task_type: str = "学习",
    ) -> str:
        """根据可用时间建议专注计划。
        
        当用户说"帮我安排专注时间"、"我有X小时要学习"时调用此工具。
        
        Args:
            available_time: 可用时间（小时），默认2.0
            task_type: 任务类型，如"学习"、"阅读"、"编程"
        
        Returns:
            专注计划建议
        """
        total_minutes = int(available_time * 60)
        
        # 计算可以完成的番茄数
        # 标准番茄：25分钟专注 + 5分钟休息 = 30分钟一个周期
        pomodoro_count = total_minutes // 30
        remaining = total_minutes % 30
        
        # 判断是否可以完成一轮（4个番茄）
        full_rounds = pomodoro_count // 4
        extra_pomodoros = pomodoro_count % 4
        
        plan = f"""🍅 专注计划建议（{task_type}）

⏰ 可用时间：{available_time} 小时（{total_minutes} 分钟）
📊 计划安排：可完成 {pomodoro_count} 个番茄

"""
        
        # 详细时间安排
        current_time = datetime.now()
        schedule = []
        
        if full_rounds >= 1:
            plan += "🔴 **一轮完整番茄（约2小时）**\n"
            for i in range(4):
                plan += f"  {i+1}. 🍅 专注25分钟\n"
                if i < 3:
                    plan += f"     ☕ 休息5分钟\n"
                else:
                    plan += f"     🌴 长休息15分钟\n"
            plan += "\n"
        
        if full_rounds > 1:
            plan += f"💡 可以继续进行第 {2}-{full_rounds} 轮\n\n"
        
        if extra_pomodoros > 0 and full_rounds < 1:
            plan += f"🔴 **番茄计划**\n"
            for i in range(extra_pomodoros):
                plan += f"  {i+1}. 🍅 专注25分钟 → ☕ 休息5分钟\n"
            plan += "\n"
        
        if remaining >= 15:
            plan += f"⏰ 剩余 {remaining} 分钟可以用来：\n"
            plan += "  - 复习笔记\n"
            plan += "  - 整理学习资料\n"
            plan += "  - 预习下一个主题\n\n"
        
        # 专注技巧
        plan += f"""💡 专注技巧：

1. **开始前**
   - 关闭手机通知
   - 准备好学习材料
   - 设定明确的小目标

2. **专注中**
   - 不要中断，有事记在纸上
   - 使用番茄钟计时
   - 保持专注于当前任务

3. **休息时**
   - 离开座位走动
   - 眺望远方放松眼睛
   - 喝水、上厕所

🔗 现在就去小程序「番茄专注」开始吧！"""
        
        return plan
    
    return suggest_focus_plan
