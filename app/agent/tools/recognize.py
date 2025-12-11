"""
图片识别工具
基于 LangChain 1.0 的 @tool 装饰器
"""

from langchain_core.tools import tool, BaseTool
from langchain_openai import ChatOpenAI

from ...config import settings


@tool
async def recognize_image(
    image_url: str,
    recognize_type: str = "auto",
    custom_prompt: str = "",
) -> str:
    """识别图片中的内容。
    
    支持以下功能：
    - OCR文字识别：提取图片中的文字
    - 公式识别：识别数学公式并转为LaTeX
    - 图片解释：解释图片内容和含义
    
    适用于用户上传题目图片、笔记图片、公式图片等场景。
    
    Args:
        image_url: 图片URL地址（必须是公网可访问的URL）
        recognize_type: 识别类型 ocr/formula/explain/auto，默认auto
        custom_prompt: 自定义识别提示词（可选）
    
    Returns:
        识别结果
    """
    # 根据识别类型选择提示词
    prompts = {
        "ocr": """请仔细识别图片中的所有文字内容。
要求：
1. 保持原有的格式和布局
2. 如果有表格，用markdown表格格式输出
3. 如果有公式，用LaTeX格式表示
4. 标注任何不确定的文字""",
        
        "formula": """请识别图片中的数学公式。
要求：
1. 将公式转换为标准LaTeX格式
2. 如果有多个公式，每个公式单独一行
3. 简要说明公式的含义
4. 如果公式有编号，保留编号""",
        
        "explain": """请详细解释这张图片的内容。
要求：
1. 描述图片中的主要元素
2. 解释图片要传达的信息或知识点
3. 如果是题目，说明解题思路
4. 如果有图表，分析数据含义""",
        
        "auto": """请分析这张图片的内容。
1. 首先判断图片类型（题目、公式、笔记、图表等）
2. 根据类型进行相应处理：
   - 如果是文字，进行OCR识别
   - 如果是公式，转换为LaTeX
   - 如果是题目，提取题目并给出解题思路
   - 如果是图表，分析数据含义""",
    }
    
    prompt = custom_prompt if custom_prompt else prompts.get(recognize_type, prompts["auto"])
    
    try:
        # 使用视觉模型
        llm = ChatOpenAI(
            model=settings.DEEPSEEK_VISION_MODEL,
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_API_BASE,
            temperature=0.3,
        )
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ]
        
        response = await llm.ainvoke(messages)
        
        type_names = {
            "ocr": "📝 文字识别结果",
            "formula": "📐 公式识别结果",
            "explain": "🔍 图片解析",
            "auto": "📸 识别结果",
        }
        
        title = type_names.get(recognize_type, "识别结果")
        return f"{title}：\n\n{response.content}"
        
    except Exception as e:
        return f"图片识别失败: {str(e)}"


def recognize_image_tool() -> BaseTool:
    """返回图片识别工具"""
    return recognize_image
