"""
分析相关工具
基于 LangChain 1.0 的 @tool 装饰器
"""

from typing import TYPE_CHECKING
from langchain_core.tools import tool, BaseTool
from langchain_openai import ChatOpenAI

from ...config import settings
from ...services.model_config_service import ModelConfigService

if TYPE_CHECKING:
    from ..memory import AgentMemory


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
        except Exception:
            pass
    
    # 降级：使用系统默认配置（需要用户在小程序中配置）
    return ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,
        api_key="",  # 需要用户配置
        base_url=settings.DEEPSEEK_API_BASE,
        temperature=temperature,
    )


@tool
async def analyze_mistake(
    question: str,
    user_answer: str,
    correct_answer: str = "",
    subject: str = "",
    image_url: str = "",
) -> str:
    """分析用户的错题，找出错误原因并给出改进建议。
    
    当用户做错题目、不理解为什么错、或想要弄懂某道题时使用。
    会分析错误类型、知识漏洞，并提供针对性的学习建议。
    
    Args:
        question: 题目内容
        user_answer: 用户的答案
        correct_answer: 正确答案（如果知道）
        subject: 学科/领域
        image_url: 题目图片URL（如果有）
    
    Returns:
        详细的错题分析报告
    """
    # 注意：此工具作为独立函数调用，无法获取 user_id
    # 使用系统默认配置（需要用户在小程序中配置模型）
    llm = await _get_text_llm(None, temperature=0.5)
    
    prompt = f"""作为学习分析专家，请分析这道错题：

## 题目信息
- 题目: {question}
- 学科: {subject or '未指定'}
- 用户答案: {user_answer}
- 正确答案: {correct_answer or '未提供'}

## 分析要求
请从以下几个方面进行分析：

1. **错误类型**: 判断是计算错误、概念理解错误、粗心大意还是其他类型
2. **错误原因**: 详细分析为什么会出错
3. **知识漏洞**: 指出可能存在的知识薄弱点
4. **正确解法**: 给出详细的正确解题步骤
5. **学习建议**: 提供具体的改进建议和练习方向

请用清晰的格式输出分析结果。
"""
    
    response = await llm.ainvoke([{"role": "user", "content": prompt}])
    return f"📊 错题分析：\n\n{response.content}"


def analyze_mistake_tool() -> BaseTool:
    """返回错题分析工具"""
    return analyze_mistake


def create_analyze_learning_status_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """
    创建学情分析工具的工厂函数
    """
    
    @tool
    async def analyze_learning_status(
        period: str = "week",
    ) -> str:
        """分析用户的学习状态和进度。
        
        当用户想了解自己的学习情况、需要学习建议、或想知道进步程度时使用。
        会分析学习时长、完成任务、知识掌握程度等。
        
        Args:
            period: 分析周期 day(今日)/week(本周)/month(本月)/all(全部)
        
        Returns:
            学习状态分析报告
        """
        # 获取用户画像
        profile = {}
        if memory:
            profile = memory.get_user_profile()
        
        llm = await _get_text_llm(user_id, temperature=0.7)
        
        prompt = f"""作为学习分析师，请根据用户画像分析学习状态：

## 用户画像
{profile}

## 分析周期
{period}

## 分析要求
请提供以下分析：

1. **学习概况**: 总结用户的整体学习情况
2. **进步亮点**: 指出用户做得好的地方
3. **待改进项**: 需要加强的方面
4. **学习建议**: 具体的下一步行动建议
5. **激励语**: 给用户一句鼓励的话

请用友好、积极的语气输出。
"""
        
        response = await llm.ainvoke([{"role": "user", "content": prompt}])
        return f"📈 学习状态分析：\n\n{response.content}"
    
    return analyze_learning_status
