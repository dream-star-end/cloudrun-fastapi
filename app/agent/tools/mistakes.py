"""
错题本相关工具
支持 AI Agent 操作错题本功能
使用数据库直连
"""

from typing import Optional, List, TYPE_CHECKING
from langchain_core.tools import tool, BaseTool
from langchain_openai import ChatOpenAI
import json

from ...config import settings
from ...db.wxcloud import MistakeRepository, get_db

if TYPE_CHECKING:
    from ..memory import AgentMemory


def create_get_mistakes_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """获取错题列表工具"""
    
    @tool
    async def get_mistakes(
        category: Optional[str] = None,
        status: str = "all",
    ) -> str:
        """获取用户的错题本内容。
        
        当用户询问"我的错题"、"错题本"、"哪些题做错了"时调用此工具。
        
        Args:
            category: 分类筛选，如"数学"、"英语"、"物理"（可选）
            status: 状态筛选 all/pending/mastered，默认all
        
        Returns:
            错题列表信息
        """
        try:
            repo = MistakeRepository()
            
            # 获取统计数据
            stats = await repo.get_stats(user_id)
            
            # 获取错题列表
            mastered = True if status == "mastered" else (False if status == "pending" else None)
            mistakes = await repo.get_mistakes(user_id, category=category, mastered=mastered, limit=10)
            
            result = f"""📕 错题本

📊 统计概览：
- 总错题数：{stats.get('total', 0)} 题
- 待复习：{stats.get('pending', 0)} 题
- 已掌握：{stats.get('mastered', 0)} 题
"""
            
            # 按分类统计
            by_category = stats.get('byCategory', {})
            if by_category:
                result += "\n📂 分类统计：\n"
                category_names = {
                    "math": "数学",
                    "english": "英语",
                    "physics": "物理",
                    "chemistry": "化学",
                    "other": "其他",
                }
                for cat, data in by_category.items():
                    name = category_names.get(cat, cat)
                    result += f"  - {name}：{data['total']} 题（已掌握 {data['mastered']}）\n"
            
            # 显示错题列表
            if mistakes:
                result += f"\n📋 {'最近' if not category else category_names.get(category, category)}错题：\n"
                for i, mistake in enumerate(mistakes[:5], 1):
                    question = mistake.get("question", "")
                    if len(question) > 30:
                        question = question[:30] + "..."
                    status_icon = "✅" if mistake.get("mastered") else "❌"
                    result += f"  {i}. {status_icon} {question}\n"
            
            result += "\n💡 功能提示：\n"
            result += "  - 发送题目图片，我可以帮你分析错因\n"
            result += "  - 说「分析这道题」让我帮你找出问题\n"
            result += "  - 说「生成复习题」帮你巩固知识点"
            
            return result
            
        except Exception as e:
            return f"""📕 错题本

⚠️ 获取数据失败，请在小程序中查看。

💡 功能说明：
- 📸 拍照添加错题
- 🤖 AI 智能分析错因
- 📝 生成复习题目
- ✅ 标记已掌握

🔗 前往小程序「错题本」查看完整内容！"""
    
    return get_mistakes


def create_add_mistake_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """添加错题工具"""
    
    @tool
    async def add_mistake(
        question: str,
        user_answer: Optional[str] = None,
        correct_answer: Optional[str] = None,
        category: str = "other",
    ) -> str:
        """添加一道新的错题到错题本。
        
        当用户说"记录这道错题"、"把这题加到错题本"时调用此工具。
        
        Args:
            question: 题目内容
            user_answer: 用户的错误答案（可选）
            correct_answer: 正确答案（可选）
            category: 科目分类 math/english/physics/chemistry/other
        
        Returns:
            添加确认信息
        """
        try:
            repo = MistakeRepository()
            
            data = {
                "question": question,
                "answer": user_answer or "",
                "correctAnswer": correct_answer or "",
                "category": category,
            }
            
            mistake_id = await repo.add_mistake(user_id, data)
            
            category_names = {
                "math": "数学",
                "english": "英语",
                "physics": "物理",
                "chemistry": "化学",
                "other": "其他",
            }
            
            return f"""✅ 错题已记录！

📝 题目：{question[:100]}{'...' if len(question) > 100 else ''}
📂 分类：{category_names.get(category, '其他')}
❌ 你的答案：{user_answer or '未填写'}
✅ 正确答案：{correct_answer or '待补充'}

💡 下一步建议：
1. 让我帮你分析这道题的错因
2. 在小程序中完善错题详情
3. 定期复习错题本

需要我分析这道题的错因吗？"""
            
        except Exception as e:
            return f"""⚠️ 添加错题失败

请在小程序「错题本」中手动添加。

错误信息：{str(e)}"""
    
    return add_mistake


def create_generate_review_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """生成复习题工具"""
    
    @tool
    async def generate_review_questions(
        category: Optional[str] = None,
        count: int = 5,
    ) -> str:
        """根据错题本生成复习题目。
        
        当用户说"帮我复习错题"、"生成复习题"、"错题练习"时调用此工具。
        
        Args:
            category: 指定科目分类（可选）
            count: 生成题目数量，默认5
        
        Returns:
            基于错题的复习内容
        """
        try:
            repo = MistakeRepository()
            
            # 获取待复习的错题
            mistakes = await repo.get_mistakes(user_id, category=category, mastered=False, limit=10)
            
            if not mistakes:
                return f"""📚 错题复习

暂无{'「' + category + '」分类的' if category else ''}待复习错题。

💡 建议：
1. 添加一些错题到错题本
2. 或者让我帮你搜索一些练习题

需要我帮你搜索相关练习题吗？"""
            
            # 使用 LLM 生成复习建议
            llm = ChatOpenAI(
                model=settings.DEEPSEEK_MODEL,
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_API_BASE,
                temperature=0.7,
            )
            
            # 构建错题摘要
            mistakes_summary = "\n".join([
                f"- {m.get('question', '')[:100]}" for m in mistakes[:5]
            ])
            
            prompt = f"""作为学习教练，根据以下错题生成复习建议：

错题列表：
{mistakes_summary}

请生成：
1. 这些错题涉及的主要知识点
2. 针对这些知识点的复习方法
3. 类似题目的解题思路

注意：简洁明了，有针对性。"""

            response = await llm.ainvoke([{"role": "user", "content": prompt}])
            
            return f"""📚 错题复习指南

📋 待复习错题：{len(mistakes)} 道

{response.content}

💡 复习完成后，记得在小程序中将已掌握的题目打勾！"""
            
        except Exception as e:
            return f"""📚 错题复习

⚠️ 生成复习内容失败

💡 手动复习方法：
1. 打开小程序「错题本」
2. 浏览待复习的题目
3. 尝试独立解答
4. 对照正确答案
5. 掌握后点击「已掌握」

错误信息：{str(e)}"""
    
    return generate_review_questions


def create_mark_mastered_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """标记错题已掌握工具"""
    
    @tool
    async def mark_mistake_mastered(question_hint: str) -> str:
        """标记某道错题为已掌握。
        
        当用户说"这题我会了"、"标记为已掌握"时调用此工具。
        
        Args:
            question_hint: 题目关键词或描述
        
        Returns:
            操作确认信息
        """
        try:
            repo = MistakeRepository()
            
            # 查找匹配的错题
            mistakes = await repo.get_mistakes(user_id, mastered=False, limit=50)
            
            matched = None
            for mistake in mistakes:
                question = mistake.get("question", "")
                if question_hint.lower() in question.lower() or question.lower() in question_hint.lower():
                    matched = mistake
                    break
            
            if not matched:
                return f"""❌ 未找到匹配的错题

关键词：{question_hint}

💡 请提供更准确的题目描述，或者在小程序中直接操作。

你的待复习错题：
{chr(10).join([f"- {m.get('question', '')[:30]}..." for m in mistakes[:5]])}"""
            
            # 标记为已掌握
            success = await repo.mark_mastered(matched.get("_id"), True)
            
            if success:
                # 获取更新后的统计
                stats = await repo.get_stats(user_id)
                
                return f"""✅ 已标记为掌握！

📝 题目：{matched.get('question', '')[:50]}...

📊 当前进度：
- 已掌握：{stats.get('mastered', 0)} 题
- 待复习：{stats.get('pending', 0)} 题

🎉 太棒了！继续加油，把更多错题攻克！"""
            else:
                return "⚠️ 更新失败，请在小程序中操作。"
            
        except Exception as e:
            return f"""⚠️ 操作失败

请在小程序「错题本」中手动标记。

错误信息：{str(e)}"""
    
    return mark_mistake_mastered
