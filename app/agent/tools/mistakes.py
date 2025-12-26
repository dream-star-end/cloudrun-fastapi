"""
错题本相关工具
支持 AI Agent 操作错题本功能
使用数据库直连
"""

import logging
import traceback
from typing import Optional, List, TYPE_CHECKING
from langchain_core.tools import tool, BaseTool
from langchain_openai import ChatOpenAI
import json

from ...config import settings
from ...db.wxcloud import MistakeRepository, get_db
from ...services.model_config_service import ModelConfigService

if TYPE_CHECKING:
    from ..memory import AgentMemory

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


async def _get_text_llm(user_id: str = None, temperature: float = 0.7):
    """
    获取文本模型 LLM 实例
    
    优先使用用户配置的文本模型，否则使用系统默认配置
    """
    if user_id:
        try:
            model_config = await ModelConfigService.get_model_for_type(user_id, "text")
            if model_config.get("api_key"):
                return ChatOpenAI(
                    model=model_config["model"],
                    api_key=model_config["api_key"],
                    base_url=model_config["base_url"],
                    temperature=temperature,
                )
        except Exception as e:
            logger.warning(f"[mistakes] 获取用户模型配置失败: {e}")
    
    # 降级：使用系统默认配置（需要用户在小程序中配置）
    return ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,
        api_key="",  # 需要用户配置
        base_url=settings.DEEPSEEK_API_BASE,
        temperature=temperature,
    )

def _normalize_tags(tags: List[str]) -> List[str]:
    out: List[str] = []
    for t in tags or []:
        if not isinstance(t, str):
            continue
        s = t.strip().strip(",，;；、").strip()
        if not s:
            continue
        out.append(s[:24])
    # 去重
    seen = set()
    uniq: List[str] = []
    for t in out:
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(t)
    return uniq[:8]


async def _ai_generate_tags(question: str, user_answer: str = "", correct_answer: str = "", analysis: str = "", user_id: str = None) -> List[str]:
    """
    用 LLM 为错题生成标签（不预置）。
    返回短标签列表（3~6 个，最多 8 个）。
    """
    llm = await _get_text_llm(user_id, temperature=0.2)

    prompt = f"""请为下面这道错题生成标签（tags）。
要求：
- 输出必须是严格的 JSON 数组，例如 ["一元二次方程","配方法","计算错误"]
- 3~6 个标签
- 标签要短（中文优先），只包含主题/知识点/技能/错误类型，不要句子，不要编号
- 不要输出任何额外文字

题目：{question}
我的答案：{user_answer}
正确答案：{correct_answer}
补充说明：{analysis}
"""

    resp = await llm.ainvoke([{"role": "user", "content": prompt}])
    text = resp.content if resp else ""
    try:
        v = json.loads(text)
        if isinstance(v, list):
            return _normalize_tags([str(x) for x in v])
    except Exception:
        pass
    # 兜底：从中间提取 JSON 数组
    try:
        import re
        m = re.search(r"\[[\s\S]*\]", text or "")
        if m:
            v = json.loads(m.group())
            if isinstance(v, list):
                return _normalize_tags([str(x) for x in v])
    except Exception:
        pass
    return []


def create_get_mistakes_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """获取错题列表工具"""
    
    @tool
    async def get_mistakes(
        tag: Optional[str] = None,
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
        logger.info(f"[get_mistakes] 开始获取错题列表, user_id={user_id}, tag={tag}, status={status}")
        
        try:
            logger.debug("[get_mistakes] 创建 MistakeRepository...")
            repo = MistakeRepository()
            
            # 获取统计数据
            logger.debug("[get_mistakes] 获取错题统计...")
            stats = await repo.get_stats(user_id)
            logger.debug(f"[get_mistakes] 统计数据: {stats}")
            
            # 获取错题列表
            mastered = True if status == "mastered" else (False if status == "pending" else None)
            logger.debug(f"[get_mistakes] 获取错题列表, mastered={mastered}...")
            mistakes = await repo.get_mistakes(user_id, category=None, tag=tag, mastered=mastered, limit=10)
            logger.debug(f"[get_mistakes] 获取到 {len(mistakes)} 条错题")
            
            result = f"""📕 错题本

📊 统计概览：
- 总错题数：{stats.get('total', 0)} 题
- 待复习：{stats.get('pending', 0)} 题
- 已掌握：{stats.get('mastered', 0)} 题
"""
            
            # 按标签统计（展示 Top N）
            by_tag = stats.get("byTag", {}) or {}
            if by_tag:
                result += "\n🏷️ 常见标签（Top 5）：\n"
                top = sorted(by_tag.items(), key=lambda x: x[1], reverse=True)[:5]
                for t, c in top:
                    result += f"  - {t}：{c} 题\n"
            
            # 显示错题列表
            if mistakes:
                result += f"\n📋 {'最近' if not tag else ('标签「' + str(tag) + '」')}错题：\n"
                for i, mistake in enumerate(mistakes[:5], 1):
                    question = mistake.get("question", "")
                    if len(question) > 30:
                        question = question[:30] + "..."
                    status_icon = "✅" if mistake.get("mastered") else "❌"
                    tags = mistake.get("tags") or []
                    tag_str = ""
                    if isinstance(tags, list) and tags:
                        tag_str = " [" + "、".join([str(x) for x in tags[:3] if x]) + "]"
                    result += f"  {i}. {status_icon} {question}{tag_str}\n"
            
            result += "\n💡 功能提示：\n"
            result += "  - 发送题目图片，我可以帮你分析错因\n"
            result += "  - 说「分析这道题」让我帮你找出问题\n"
            result += "  - 说「生成复习题」帮你巩固知识点"
            
            logger.info("[get_mistakes] 获取错题列表成功")
            return result
            
        except Exception as e:
            # 记录详细的错误信息和堆栈
            logger.error(f"[get_mistakes] 获取错题失败: {type(e).__name__}: {str(e)}")
            logger.error(f"[get_mistakes] 堆栈跟踪:\n{traceback.format_exc()}")
            
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
        analysis: Optional[str] = None,
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
            
            tags = await _ai_generate_tags(
                question=question,
                user_answer=user_answer or "",
                correct_answer=correct_answer or "",
                analysis=analysis or "",
                user_id=user_id,
            )

            data = {
                "question": question,
                "answer": user_answer or "",
                "correctAnswer": correct_answer or "",
                "analysis": analysis or "",
                "tags": tags,
                "source": "agent",
            }
            
            mistake_id = await repo.add_mistake(user_id, data)
            
            return f"""✅ 错题已记录！

📝 题目：{question[:100]}{'...' if len(question) > 100 else ''}
❌ 你的答案：{user_answer or '未填写'}
✅ 正确答案：{correct_answer or '待补充'}
🏷️ 标签：{'、'.join(tags) if tags else '（AI 暂未生成）'}

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
            llm = await _get_text_llm(user_id, temperature=0.7)
            
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
