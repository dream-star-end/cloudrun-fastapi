"""
任务管理相关工具
支持 AI Agent 操作每日学习任务
使用数据库直连
"""

import logging
import traceback
from typing import Optional, List, TYPE_CHECKING
from langchain_core.tools import tool, BaseTool
from datetime import datetime

from ...db.wxcloud import TaskRepository, PlanRepository, get_db

if TYPE_CHECKING:
    from ..memory import AgentMemory

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def create_get_today_tasks_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """获取今日任务工具"""
    
    @tool
    async def get_today_tasks() -> str:
        """获取今天的学习任务列表。
        
        当用户询问"今天有什么任务"、"今日学习任务"、"我要学什么"时调用此工具。
        
        Returns:
            今日任务列表及完成状态
        """
        logger.info(f"[get_today_tasks] 开始获取今日任务, user_id={user_id}")
        
        try:
            logger.debug("[get_today_tasks] 创建 TaskRepository...")
            task_repo = TaskRepository()
            
            logger.debug("[get_today_tasks] 获取今日任务...")
            tasks = await task_repo.get_today_tasks(user_id)
            logger.debug(f"[get_today_tasks] 获取到 {len(tasks)} 个任务")
            
            today = datetime.now().strftime('%Y-%m-%d')
            
            if not tasks:
                # 检查是否有学习计划
                plan_repo = PlanRepository()
                plan = await plan_repo.get_active_plan(user_id)
                
                if plan:
                    return f"""📋 今日任务（{today}）

暂无今日任务。

💡 你有一个进行中的学习计划：「{plan.get('goal', '学习计划')}」

需要我帮你生成今天的学习任务吗？"""
                else:
                    return f"""📋 今日任务（{today}）

暂无任务，因为你还没有创建学习计划。

💡 让我帮你创建一个学习计划吧！告诉我：
1. 你想学什么？
2. 每天可以学习多长时间？
3. 有没有截止日期？"""
            
            # 构建任务列表
            completed = [t for t in tasks if t.get("completed")]
            pending = [t for t in tasks if not t.get("completed")]
            
            result = f"""📋 今日任务（{today}）

📊 进度：{len(completed)}/{len(tasks)} 完成
"""
            
            if pending:
                result += "\n⏳ **待完成：**\n"
                for i, task in enumerate(pending, 1):
                    duration = task.get("duration", 30)
                    result += f"{i}. {task.get('title', '任务')} ({duration}分钟)\n"
            
            if completed:
                result += "\n✅ **已完成：**\n"
                for task in completed:
                    result += f"- ~~{task.get('title', '任务')}~~\n"
            
            # 添加鼓励语
            progress = len(completed) / len(tasks) * 100 if tasks else 0
            if progress == 100:
                result += "\n🎉 太棒了！今日任务全部完成！"
            elif progress >= 50:
                result += "\n💪 已经过半，继续加油！"
            else:
                result += "\n✨ 开始行动吧，完成今天的学习目标！"
            
            return result
            
        except Exception as e:
            logger.error(f"[get_today_tasks] 获取任务失败: {type(e).__name__}: {str(e)}")
            logger.error(f"[get_today_tasks] 堆栈跟踪:\n{traceback.format_exc()}")
            return f"""⚠️ 获取任务失败

请在小程序「学习计划」页面查看任务列表。

错误信息：{str(e)}"""
    
    return get_today_tasks


def create_complete_task_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """完成任务工具"""
    
    @tool
    async def complete_task(task_name: str) -> str:
        """标记某个学习任务为已完成。
        
        当用户说"我完成了XX任务"、"XX做完了"时调用此工具。
        
        Args:
            task_name: 要标记完成的任务名称
        
        Returns:
            任务完成确认信息
        """
        try:
            task_repo = TaskRepository()
            tasks = await task_repo.get_today_tasks(user_id)
            
            # 查找匹配的任务
            matched_task = None
            for task in tasks:
                title = task.get("title", "")
                if task_name.lower() in title.lower() or title.lower() in task_name.lower():
                    matched_task = task
                    break
            
            if not matched_task:
                return f"""❌ 未找到匹配的任务：{task_name}

你今天的任务有：
{chr(10).join([f"- {t.get('title', '任务')}" for t in tasks[:5]])}

请告诉我具体要完成哪个任务。"""
            
            if matched_task.get("completed"):
                return f"ℹ️ 任务「{matched_task.get('title')}」已经完成过了哦~"
            
            # 标记完成
            task_id = matched_task.get("_id")
            success = await task_repo.complete_task(task_id, True)
            
            if success:
                # 获取更新后的进度
                progress = await task_repo.get_task_progress(user_id)
                completed = progress.get("completed", 0)
                total = progress.get("total", 0)
                
                # 鼓励语
                messages = [
                    "太棒了！继续加油 💪",
                    "很好！保持这个节奏 ✨",
                    "完成一项！再接再厉 🌟",
                    "不错！距离目标更近了 🎯",
                ]
                import random
                encourage = random.choice(messages)
                
                if completed == total:
                    encourage = "🎉 今日任务全部完成！太厉害了！"
                
                return f"""✅ 任务已完成：{matched_task.get('title')}

📊 今日进度：{completed}/{total}
{'█' * completed}{'░' * (total - completed)} {progress.get('progress', 0):.0f}%

{encourage}"""
            else:
                return f"⚠️ 更新任务状态失败，请在小程序中操作。"
                
        except Exception as e:
            return f"""⚠️ 完成任务失败

请在小程序「学习计划」页面手动完成任务。

错误信息：{str(e)}"""
    
    return complete_task


def create_get_task_progress_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """获取任务进度工具"""
    
    @tool
    async def get_task_progress() -> str:
        """获取学习任务的完成进度。
        
        当用户询问"我的进度怎么样"、"任务完成了多少"、"学习进度"时调用此工具。
        
        Returns:
            任务完成进度信息
        """
        try:
            task_repo = TaskRepository()
            progress = await task_repo.get_task_progress(user_id)
            
            total = progress.get("total", 0)
            completed = progress.get("completed", 0)
            percentage = progress.get("progress", 0)
            
            if total == 0:
                return """📊 今日暂无任务

你还没有今日任务，需要我帮你：
1. 创建一个学习计划？
2. 生成今天的学习任务？"""
            
            # 进度条
            filled = int(percentage / 10)
            progress_bar = "█" * filled + "░" * (10 - filled)
            
            # 状态评估
            if percentage == 100:
                status = "🏆 完美！"
                suggestion = "今日任务全部完成，可以适当休息或预习明天的内容。"
            elif percentage >= 80:
                status = "🌟 优秀！"
                suggestion = "再坚持一下，就能完成今天的目标了！"
            elif percentage >= 50:
                status = "💪 加油！"
                suggestion = "已经完成一半了，保持节奏继续学习！"
            else:
                status = "⏰ 需努力"
                suggestion = "今天的学习任务还有不少，抓紧时间开始吧！"
            
            # 列出未完成任务
            tasks = progress.get("tasks", [])
            pending = [t for t in tasks if not t.get("completed")]
            
            result = f"""📊 今日学习进度

{progress_bar} {percentage:.0f}%
✅ 已完成：{completed} 项
⏳ 待完成：{total - completed} 项
📈 状态：{status}

💡 {suggestion}"""
            
            if pending and len(pending) <= 3:
                result += "\n\n⏳ 待完成任务：\n"
                for task in pending:
                    result += f"- {task.get('title', '任务')}\n"
            
            return result
            
        except Exception as e:
            return f"""⚠️ 获取进度失败

请在小程序「学习计划」页面查看进度。

错误信息：{str(e)}"""
    
    return get_task_progress


def create_adjust_tasks_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """调整任务工具"""
    
    @tool
    async def suggest_task_adjustment(
        reason: str,
        adjustment_type: str = "reduce",
    ) -> str:
        """根据用户情况建议调整任务。
        
        当用户说"任务太多了"、"今天没时间"、"想增加任务"时调用此工具。
        
        Args:
            reason: 调整原因，如"时间不够"、"太简单了"
            adjustment_type: 调整类型 reduce/increase/reschedule
        
        Returns:
            任务调整建议
        """
        try:
            task_repo = TaskRepository()
            progress = await task_repo.get_task_progress(user_id)
            
            tasks = progress.get("tasks", [])
            pending = [t for t in tasks if not t.get("completed")]
            total_minutes = sum(t.get("duration", 30) for t in pending)
            
            if adjustment_type == "reduce":
                suggestion = f"""📝 任务调整建议（减少）

📊 当前状态：
- 待完成任务：{len(pending)} 项
- 预计时长：{total_minutes} 分钟

💡 调整建议：

1. **优先完成重要任务**
   选择1-2个最重要的任务先完成"""
                
                if pending:
                    suggestion += f"\n   推荐：{pending[0].get('title', '任务')}"
                
                suggestion += f"""

2. **延期处理**
   其他任务可以顺延到明天

3. **拆分大任务**
   如果某个任务太大，可以只完成一部分

⚠️ 学习贵在坚持，少量但持续比突击更有效！

需要我帮你调整明天的任务量吗？"""

            elif adjustment_type == "increase":
                suggestion = f"""📝 任务调整建议（增加）

很高兴你状态这么好！💪

📊 当前状态：
- 已完成：{progress.get('completed', 0)}/{progress.get('total', 0)}

💡 增量建议：

1. **深入学习**
   - 在当前主题上做更多练习
   - 阅读相关拓展资料

2. **复习巩固**
   - 复习之前学过的内容
   - 整理学习笔记

3. **预习明天**
   - 提前预习明天的任务
   - 搜索相关学习资源

⚠️ 注意劳逸结合，避免过度疲劳！

需要我搜索一些拓展学习资源吗？"""

            else:  # reschedule
                suggestion = f"""📝 任务调整建议（重新安排）

📊 当前状态：
- 待完成：{len(pending)} 项，共 {total_minutes} 分钟

💡 重新安排建议：

1. **按优先级排序**
   - 重要且紧急的任务优先
   - 简单任务穿插在中间

2. **时间块安排**
   - 上午：学习新知识
   - 下午：做练习
   - 晚上：复习总结

3. **设定时间限制**
   - 每个任务设定完成时限
   - 用番茄钟辅助专注

需要我帮你制定一个新的学习计划吗？"""
            
            return suggestion
            
        except Exception as e:
            return f"""⚠️ 获取任务信息失败

请在小程序「学习计划」页面查看和调整任务。

错误信息：{str(e)}"""
    
    return suggest_task_adjustment
