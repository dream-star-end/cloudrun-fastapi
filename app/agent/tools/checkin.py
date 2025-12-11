"""
打卡相关工具
支持 AI Agent 直接操作小程序打卡功能
使用数据库直连
"""

import logging
import traceback
from typing import Optional, TYPE_CHECKING
from langchain_core.tools import tool, BaseTool
from datetime import datetime

from ...db.wxcloud import CheckinRepository, UserRepository, get_db

if TYPE_CHECKING:
    from ..memory import AgentMemory

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def create_checkin_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """创建打卡工具"""
    
    @tool
    async def do_checkin() -> str:
        """执行学习打卡。
        
        当用户说"帮我打卡"、"我要打卡"、"签到"时调用此工具。
        打卡可以记录用户的学习天数和连续学习streak。
        
        Returns:
            打卡结果，包含连续天数等信息
        """
        logger.info(f"[do_checkin] 开始执行打卡, user_id={user_id}")
        
        try:
            logger.debug("[do_checkin] 创建 CheckinRepository...")
            repo = CheckinRepository()
            
            logger.debug("[do_checkin] 调用 do_checkin...")
            result = await repo.do_checkin(user_id)
            logger.debug(f"[do_checkin] 打卡结果: {result}")
            
            if result.get("success"):
                data = result.get("data", {})
                streak = data.get("currentStreak", 1)
                study_days = data.get("studyDays", 1)
                
                # 根据连续天数给出不同的鼓励语
                if streak >= 30:
                    encourage = "🏆 太厉害了！你已经连续打卡一个月，坚持就是胜利！"
                elif streak >= 7:
                    encourage = "🔥 连续打卡一周，养成好习惯了！"
                elif streak >= 3:
                    encourage = "💪 连续三天，保持这个节奏！"
                else:
                    encourage = "✨ 每一天都是新的开始，加油！"
                
                logger.info(f"[do_checkin] 打卡成功, streak={streak}, study_days={study_days}")
                return f"""✅ 打卡成功！

📅 打卡时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}
🔥 连续打卡：{streak} 天
📊 累计学习：{study_days} 天

{encourage}"""
            else:
                error = result.get("error", "打卡失败")
                logger.warning(f"[do_checkin] 打卡失败: {error}")
                if "已打卡" in error:
                    return f"""ℹ️ 今日已打卡！

你今天已经完成打卡了，继续保持学习状态吧！

💡 提示：每天只能打卡一次哦~"""
                return f"❌ 打卡失败：{error}"
                
        except Exception as e:
            logger.error(f"[do_checkin] 打卡异常: {type(e).__name__}: {str(e)}")
            logger.error(f"[do_checkin] 堆栈跟踪:\n{traceback.format_exc()}")
            return f"""⚠️ 打卡服务暂时不可用

请稍后重试，或者直接在小程序中点击打卡按钮。

错误信息：{str(e)}"""
    
    return do_checkin


def create_get_checkin_status_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """获取打卡状态工具"""
    
    @tool
    async def get_checkin_status() -> str:
        """获取用户的打卡状态和统计信息。
        
        当用户询问"我今天打卡了吗"、"我的打卡记录"、"连续打卡多少天"时调用此工具。
        
        Returns:
            打卡统计信息，包含今日状态、连续天数、总天数等
        """
        logger.info(f"[get_checkin_status] 开始获取打卡状态, user_id={user_id}")
        
        try:
            logger.debug("[get_checkin_status] 创建 CheckinRepository...")
            repo = CheckinRepository()
            
            logger.debug("[get_checkin_status] 获取打卡统计...")
            stats = await repo.get_checkin_stats(user_id)
            logger.debug(f"[get_checkin_status] 统计数据: {stats}")
            
            today_status = "✅ 已打卡" if stats.get("todayChecked") else "❌ 未打卡"
            current_streak = stats.get("currentStreak", 0)
            longest_streak = stats.get("longestStreak", 0)
            study_days = stats.get("studyDays", 0)
            total_minutes = stats.get("totalMinutes", 0)
            this_month = stats.get("thisMonthDays", 0)
            
            # 计算学习时长
            hours = total_minutes // 60
            minutes = total_minutes % 60
            time_str = f"{hours}小时{minutes}分钟" if hours > 0 else f"{minutes}分钟"
            
            logger.info(f"[get_checkin_status] 获取成功, today={stats.get('todayChecked')}, streak={current_streak}")
            return f"""📊 你的打卡统计

📅 今日状态：{today_status}
🔥 连续打卡：{current_streak} 天
🏆 最长连续：{longest_streak} 天
📆 累计学习：{study_days} 天
⏱️ 总学习时长：{time_str}
📅 本月打卡：{this_month} 天

{'👏 今天已打卡，继续保持！' if stats.get("todayChecked") else '💡 今天还没打卡，现在就开始学习吧！'}"""
            
        except Exception as e:
            logger.error(f"[get_checkin_status] 获取打卡状态失败: {type(e).__name__}: {str(e)}")
            logger.error(f"[get_checkin_status] 堆栈跟踪:\n{traceback.format_exc()}")
            return f"""⚠️ 获取打卡数据失败

请稍后重试，或在小程序「打卡」页面查看。

错误信息：{str(e)}"""
    
    return get_checkin_status


def create_get_badges_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """获取成就徽章工具"""
    
    @tool
    async def get_badges() -> str:
        """获取用户已解锁的成就徽章。
        
        当用户询问"我的成就"、"有什么徽章"、"解锁了哪些成就"时调用此工具。
        
        Returns:
            用户的成就徽章列表
        """
        try:
            repo = CheckinRepository()
            stats = await repo.get_checkin_stats(user_id)
            
            # 徽章定义
            badges = [
                {"id": "first", "name": "初来乍到", "desc": "完成首次打卡", "icon": "🌱", 
                 "condition": stats.get("studyDays", 0) >= 1},
                {"id": "week", "name": "周周向上", "desc": "连续打卡7天", "icon": "🔥",
                 "condition": stats.get("longestStreak", 0) >= 7},
                {"id": "month", "name": "月度达人", "desc": "连续打卡30天", "icon": "⭐",
                 "condition": stats.get("longestStreak", 0) >= 30},
                {"id": "hundred", "name": "百日坚持", "desc": "累计打卡100天", "icon": "💎",
                 "condition": stats.get("studyDays", 0) >= 100},
            ]
            
            # 生成徽章列表
            unlocked = []
            locked = []
            
            for badge in badges:
                if badge["condition"]:
                    unlocked.append(f"{badge['icon']} **{badge['name']}** - {badge['desc']} ✓")
                else:
                    locked.append(f"🔒 {badge['name']} - {badge['desc']}")
            
            result = "🏆 成就徽章\n\n"
            
            if unlocked:
                result += "**已解锁：**\n" + "\n".join(unlocked) + "\n\n"
            
            if locked:
                result += "**待解锁：**\n" + "\n".join(locked) + "\n\n"
            
            result += f"📊 当前进度：累计 {stats.get('studyDays', 0)} 天，连续 {stats.get('currentStreak', 0)} 天\n"
            result += "\n💡 继续坚持，解锁更多成就！"
            
            return result
            
        except Exception as e:
            return f"""🏆 成就徽章系统

可解锁的徽章：
🌱 初来乍到 - 完成首次打卡
🔥 周周向上 - 连续打卡7天
⭐ 月度达人 - 连续打卡30天
💎 百日坚持 - 累计打卡100天

查看你的徽章解锁状态，请前往小程序「打卡」页面！"""
    
    return get_badges
