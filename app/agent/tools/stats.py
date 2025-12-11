"""
统计和排行相关工具
支持 AI Agent 查询学习统计和排行榜
使用数据库直连
"""

import logging
import traceback
from typing import Optional, TYPE_CHECKING
from langchain_core.tools import tool, BaseTool
from datetime import datetime, timedelta

from ...db.wxcloud import (
    UserRepository, 
    CheckinRepository, 
    TaskRepository, 
    FocusRepository,
    PlanRepository,
    get_db,
)

if TYPE_CHECKING:
    from ..memory import AgentMemory

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def create_get_learning_stats_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """获取学习统计工具"""
    
    @tool
    async def get_learning_stats(period: str = "today") -> str:
        """获取用户的学习统计数据。
        
        当用户询问"我的学习情况"、"学习统计"、"这周学了多久"时调用此工具。
        
        Args:
            period: 统计周期 today/week/month/all，默认today
        
        Returns:
            学习统计信息
        """
        logger.info(f"[get_learning_stats] 开始获取学习统计, user_id={user_id}, period={period}")
        
        try:
            logger.debug("[get_learning_stats] 创建 Repositories...")
            user_repo = UserRepository()
            checkin_repo = CheckinRepository()
            focus_repo = FocusRepository()
            task_repo = TaskRepository()
            
            # 获取基础统计
            logger.debug("[get_learning_stats] 获取用户统计数据...")
            stats = await user_repo.get_stats(user_id) or {}
            logger.debug(f"[get_learning_stats] 用户统计: {stats}")
            checkin_stats = await checkin_repo.get_checkin_stats(user_id)
            focus_stats = await focus_repo.get_today_stats(user_id)
            task_progress = await task_repo.get_task_progress(user_id)
            
            period_names = {
                "today": "今日",
                "week": "本周",
                "month": "本月",
                "all": "累计",
            }
            
            result = f"""📊 {period_names.get(period, '学习')}统计

"""
            
            if period == "today":
                result += f"""📅 今日数据：
- 打卡状态：{'✅ 已打卡' if checkin_stats.get('todayChecked') else '❌ 未打卡'}
- 专注时长：{focus_stats.get('todayMinutes', 0)} 分钟
- 番茄数量：{focus_stats.get('todayCount', 0)} 个
- 任务完成：{task_progress.get('completed', 0)}/{task_progress.get('total', 0)}
"""
            elif period == "week":
                result += f"""📅 本周数据：
- 学习天数：{checkin_stats.get('thisWeekDays', stats.get('thisWeekDays', 0))} 天
- 总学习时长：请在小程序查看详细图表
"""
            elif period == "month":
                result += f"""📅 本月数据：
- 打卡天数：{checkin_stats.get('thisMonthDays', 0)} 天
- 月度目标：在小程序中设置
"""
            else:  # all
                total_minutes = stats.get('totalMinutes', 0)
                hours = total_minutes // 60
                result += f"""📅 累计数据：
- 学习天数：{stats.get('studyDays', 0)} 天
- 学习时长：{hours} 小时 {total_minutes % 60} 分钟
- 最长连续：{checkin_stats.get('longestStreak', 0)} 天
"""
            
            # 连续打卡
            result += f"""
🔥 连续打卡：{checkin_stats.get('currentStreak', 0)} 天

"""
            
            # 给出建议
            if not checkin_stats.get('todayChecked'):
                result += "💡 今天还没打卡，记得打卡哦！\n"
            
            if task_progress.get('total', 0) > 0:
                progress = task_progress.get('progress', 0)
                if progress < 50:
                    result += "💡 今日任务还有一半以上，抓紧时间学习！\n"
                elif progress < 100:
                    result += "💡 再坚持一下，今天的任务就完成了！\n"
                else:
                    result += "🎉 今日任务已完成，太棒了！\n"
            
            return result
            
        except Exception as e:
            logger.error(f"[get_learning_stats] 获取统计失败: {type(e).__name__}: {str(e)}")
            logger.error(f"[get_learning_stats] 堆栈跟踪:\n{traceback.format_exc()}")
            return f"""📊 学习统计

⚠️ 获取数据失败

请在小程序中查看详细统计：
- 首页：查看本周学习柱状图
- 打卡页：查看月度日历
- 个人中心：查看累计数据

错误信息：{str(e)}"""
    
    return get_learning_stats


def create_get_rank_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """获取排行榜工具"""
    
    @tool
    async def get_ranking(rank_type: str = "streak") -> str:
        """获取学习排行榜信息。
        
        当用户询问"排行榜"、"我排第几"、"学习排名"时调用此工具。
        
        Args:
            rank_type: 排行类型 streak/minutes/days，默认streak
        
        Returns:
            排行榜信息
        """
        try:
            db = get_db()
            
            # 获取用户自己的统计
            user_repo = UserRepository()
            my_stats = await user_repo.get_stats(user_id) or {}
            
            rank_names = {
                "streak": "连续打卡",
                "minutes": "学习时长",
                "days": "累计天数",
            }
            
            # 根据排行类型获取用户的值
            if rank_type == "streak":
                my_value = my_stats.get("currentStreak", 0)
                unit = "天"
            elif rank_type == "minutes":
                my_value = my_stats.get("totalMinutes", 0)
                unit = "分钟"
            else:
                my_value = my_stats.get("studyDays", 0)
                unit = "天"
            
            result = f"""🏆 学习排行榜（{rank_names.get(rank_type, '综合')}）

📊 你的数据：
- {rank_names.get(rank_type, '数值')}：{my_value} {unit}

"""
            
            # 排名激励
            if rank_type == "streak":
                if my_value >= 30:
                    result += "🥇 太厉害了！你已经是连续打卡达人！\n"
                elif my_value >= 7:
                    result += "🥈 很棒！保持一周以上的连续打卡！\n"
                elif my_value >= 3:
                    result += "🥉 不错的开始，继续保持！\n"
                else:
                    result += "💪 每天打卡，慢慢积累连续天数！\n"
            
            result += f"""
📋 排行榜类型：
- 🔥 连续打卡排行
- ⏱️ 学习时长排行
- 📅 累计天数排行

💡 提升排名的方法：
1. 坚持每日打卡
2. 使用番茄钟专注学习
3. 完成每日学习任务

🔗 查看完整排行榜请前往小程序「排行榜」页面！"""
            
            return result
            
        except Exception as e:
            return f"""🏆 学习排行榜

⚠️ 获取排行数据失败

请在小程序「排行榜」页面查看。

💡 提升排名的方法：
1. 坚持每日打卡
2. 保持专注学习
3. 完成每日任务

错误信息：{str(e)}"""
    
    return get_ranking


def create_get_achievement_rate_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """获取目标达成率工具"""
    
    @tool
    async def get_achievement_rate() -> str:
        """获取学习计划的目标达成率。
        
        当用户询问"目标完成得怎么样"、"达成率"、"计划进度"时调用此工具。
        
        Returns:
            目标达成率分析
        """
        try:
            plan_repo = PlanRepository()
            achievement = await plan_repo.get_achievement_rate(user_id)
            
            if not achievement.get("hasActivePlan"):
                return """🎯 目标达成率

你目前没有进行中的学习计划。

💡 建议：
1. 创建一个学习计划
2. 设定明确的学习目标
3. 每天完成计划任务

需要我帮你创建一个学习计划吗？"""
            
            goal = achievement.get("planGoal", "学习目标")
            plan_progress = achievement.get("planProgress", 0)
            today_progress = achievement.get("todayProgress", 0)
            task_rate = achievement.get("taskCompletionRate", 0)
            
            # 评估达成状态
            if task_rate >= 80:
                status = "🌟 优秀"
                color = "绿"
            elif task_rate >= 60:
                status = "💪 良好"
                color = "蓝"
            elif task_rate >= 40:
                status = "⚠️ 一般"
                color = "黄"
            else:
                status = "❗ 需加油"
                color = "红"
            
            # 进度条
            filled = int(plan_progress / 10)
            progress_bar = "█" * filled + "░" * (10 - filled)
            
            return f"""🎯 目标达成率分析

📋 当前计划：{goal}

📊 进度概览：
{progress_bar} {plan_progress:.0f}%

📈 指标详情：
- 计划总进度：{plan_progress:.0f}%
- 今日完成率：{today_progress:.0f}%
- 任务完成率：{task_rate:.0f}%
- 当前状态：{status}

💡 提高达成率的建议：
1. 将大目标拆解为小任务
2. 每天固定时间学习
3. 及时调整不合理的计划
4. 利用碎片时间复习

需要我帮你调整学习计划吗？"""
            
        except Exception as e:
            return f"""🎯 目标达成率

⚠️ 获取数据失败

请在小程序「学习计划」页面查看达成率分析。

错误信息：{str(e)}"""
    
    return get_achievement_rate


def create_analyze_learning_pattern_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """分析学习模式工具"""
    
    @tool
    async def analyze_learning_pattern() -> str:
        """分析用户的学习模式和习惯。
        
        当用户询问"分析我的学习习惯"、"我的学习模式"、"学习建议"时调用此工具。
        
        Returns:
            学习模式分析和建议
        """
        try:
            user_repo = UserRepository()
            checkin_repo = CheckinRepository()
            focus_repo = FocusRepository()
            
            # 获取用户数据
            stats = await user_repo.get_stats(user_id) or {}
            user_memory = await user_repo.get_memory(user_id) or {}
            checkin_stats = await checkin_repo.get_checkin_stats(user_id)
            focus_stats = await focus_repo.get_today_stats(user_id)
            
            # 获取用户画像
            profile = user_memory.get("profile", {})
            
            result = """🔍 学习模式分析

"""
            
            # 基于数据的分析
            study_days = stats.get("studyDays", 0)
            total_minutes = stats.get("totalMinutes", 0)
            current_streak = checkin_stats.get("currentStreak", 0)
            
            if study_days > 0:
                avg_daily = total_minutes // study_days if study_days > 0 else 0
                result += f"""📊 学习数据分析：
- 累计学习 {study_days} 天
- 平均每天学习 {avg_daily} 分钟
- 当前连续打卡 {current_streak} 天

"""
            
            # 学习强度评估
            if avg_daily >= 120:
                intensity = "高强度学习者 📈"
                tip = "注意劳逸结合，避免过度疲劳"
            elif avg_daily >= 60:
                intensity = "稳定学习者 📊"
                tip = "保持这个节奏，持续进步"
            elif avg_daily >= 30:
                intensity = "轻度学习者 📉"
                tip = "可以适当增加学习时间"
            else:
                intensity = "需要提升 ⚡"
                tip = "建议每天至少学习30分钟"
            
            result += f"""📈 学习强度：{intensity}
💡 建议：{tip}

"""
            
            # 用户画像信息
            if profile:
                goals = profile.get("learningGoals", [])
                subjects = profile.get("subjects", [])
                weak_points = profile.get("weakPoints", [])
                
                if goals:
                    result += f"🎯 学习目标：{', '.join(goals[:3])}\n"
                if subjects:
                    result += f"📚 学习科目：{', '.join(subjects[:3])}\n"
                if weak_points:
                    result += f"⚠️ 薄弱环节：{', '.join(weak_points[:3])}\n"
                result += "\n"
            
            # 通用建议
            result += """💡 学习效率提升建议：

1. **最佳学习时间**
   - 早上 9-11 点：适合学习新知识
   - 下午 2-4 点：适合做练习
   - 晚上 8-10 点：适合复习总结

2. **学习方法**
   - 番茄工作法：25分钟专注学习
   - 费曼学习法：用自己的话复述
   - 间隔重复：分散学习效果更好

3. **保持动力**
   - 设定小目标，及时奖励自己
   - 找学习伙伴，相互监督
   - 记录进步，看到成长

需要我帮你制定更适合的学习计划吗？"""
            
            return result
            
        except Exception as e:
            # 返回通用建议
            return """🔍 学习模式分析

⚠️ 暂时无法获取你的学习数据

💡 通用学习建议：

1. **最佳学习时间**
   - 早上：适合学习新知识
   - 下午：适合做练习
   - 晚上：适合复习总结

2. **学习节奏**
   - 番茄工作法：25分钟专注
   - 间隔复习：分散学习更有效
   - 适度休息：避免疲劳学习

3. **效率提升**
   - 减少干扰：关闭手机通知
   - 明确目标：每次学习前设定目标
   - 及时反馈：完成任务后打勾

需要我帮你制定学习计划吗？"""
    
    return analyze_learning_pattern


def create_get_calendar_data_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """获取日历数据工具"""
    
    @tool
    async def get_calendar_data(
        date: Optional[str] = None,
    ) -> str:
        """获取某天的学习详情。
        
        当用户询问"某天学了什么"、"历史学习记录"时调用此工具。
        
        Args:
            date: 日期，格式 YYYY-MM-DD（可选，默认今天）
        
        Returns:
            该日期的学习详情
        """
        try:
            if not date:
                date = datetime.now().strftime('%Y-%m-%d')
            
            db = get_db()
            
            # 获取打卡记录
            checkin = await db.get_one("checkin_records", {"openid": user_id, "date": date})
            
            # 获取任务完成情况
            tasks = await db.query("plan_tasks", {"openid": user_id, "date": date})
            
            result = f"""📅 {date} 学习详情

"""
            
            # 打卡状态
            if checkin:
                result += f"✅ 打卡：已完成（{checkin.get('time', '')}）\n"
            else:
                result += "❌ 打卡：未打卡\n"
            
            # 任务情况
            if tasks:
                completed = [t for t in tasks if t.get("completed")]
                result += f"\n📋 任务：{len(completed)}/{len(tasks)} 完成\n"
                for task in tasks:
                    status = "✅" if task.get("completed") else "⏳"
                    result += f"  {status} {task.get('title', '任务')}\n"
            else:
                result += "\n📋 任务：无任务记录\n"
            
            result += "\n💡 查看完整日历数据，请前往小程序「打卡」页面！"
            
            return result
            
        except Exception as e:
            return f"""📅 {date or '今日'} 学习详情

⚠️ 获取数据失败

请在小程序「打卡」页面：
1. 点击日历中的日期
2. 查看该日期的学习详情

错误信息：{str(e)}"""
    
    return get_calendar_data
