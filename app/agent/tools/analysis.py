"""
分析相关工具
"""

from typing import Optional, Type, TYPE_CHECKING
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from ...config import settings

if TYPE_CHECKING:
    from ..memory import AgentMemory


class AnalyzeMistakeInput(BaseModel):
    """错题分析的输入参数"""
    question: str = Field(description="题目内容")
    user_answer: str = Field(description="用户的答案")
    correct_answer: str = Field(default="", description="正确答案（如果知道）")
    subject: str = Field(default="", description="学科/领域")
    image_url: str = Field(default="", description="题目图片URL（如果有）")


class AnalyzeMistakeTool(BaseTool):
    """分析错题"""
    
    name: str = "analyze_mistake"
    description: str = """分析用户的错题，找出错误原因并给出改进建议。
    当用户做错题目、不理解为什么错、或想要弄懂某道题时使用。
    会分析错误类型、知识漏洞，并提供针对性的学习建议。"""
    args_schema: Type[BaseModel] = AnalyzeMistakeInput
    
    def _run(self, **kwargs) -> str:
        import asyncio
        return asyncio.run(self._arun(**kwargs))
    
    async def _arun(
        self,
        question: str,
        user_answer: str,
        correct_answer: str = "",
        subject: str = "",
        image_url: str = "",
    ) -> str:
        """异步分析错题"""
        
        llm = ChatOpenAI(
            model=settings.DEEPSEEK_MODEL,
            openai_api_key=settings.DEEPSEEK_API_KEY,
            openai_api_base=settings.DEEPSEEK_API_BASE,
            temperature=0.5,
        )
        
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


class AnalyzeLearningStatusInput(BaseModel):
    """学情分析的输入参数"""
    period: str = Field(
        default="week",
        description="分析周期：day(今日)/week(本周)/month(本月)/all(全部)"
    )


class AnalyzeLearningStatusTool(BaseTool):
    """分析学习状态"""
    
    name: str = "analyze_learning_status"
    description: str = """分析用户的学习状态和进度。
    当用户想了解自己的学习情况、需要学习建议、或想知道进步程度时使用。
    会分析学习时长、完成任务、知识掌握程度等。"""
    args_schema: Type[BaseModel] = AnalyzeLearningStatusInput
    
    user_id: str = ""
    memory: Optional["AgentMemory"] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, user_id: str, memory: "AgentMemory", **kwargs):
        super().__init__(**kwargs)
        self.user_id = user_id
        self.memory = memory
    
    def _run(self, period: str = "week") -> str:
        import asyncio
        return asyncio.run(self._arun(period))
    
    async def _arun(self, period: str = "week") -> str:
        """异步分析学习状态"""
        
        # 获取用户画像
        profile = {}
        if self.memory:
            profile = self.memory.get_user_profile()
        
        llm = ChatOpenAI(
            model=settings.DEEPSEEK_MODEL,
            openai_api_key=settings.DEEPSEEK_API_KEY,
            openai_api_base=settings.DEEPSEEK_API_BASE,
            temperature=0.7,
        )
        
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

