"""
图片识别 API 路由
支持 OCR、图片解释、公式识别等
"""
from fastapi import APIRouter, HTTPException
from ..models import RecognizeRequest, RecognizeResponse
from ..services.ai_service import AIService

router = APIRouter(prefix="/api/recognize", tags=["图片识别"])


@router.post("", response_model=RecognizeResponse)
async def recognize_image(request: RecognizeRequest):
    """
    图片识别接口
    
    - **image_url**: 图片 URL（支持 http/https/base64）
    - **recognize_type**: 识别类型
        - `ocr`: 文字识别
        - `explain`: 图片解释
        - `summary`: 内容总结
        - `formula`: 公式识别
    - **custom_prompt**: 自定义提示词（可选）
    """
    try:
        result = await AIService.recognize_image(
            image_url=request.image_url,
            recognize_type=request.recognize_type.value,
            custom_prompt=request.custom_prompt,
        )
        
        return RecognizeResponse(
            success=True,
            result=result,
            recognize_type=request.recognize_type.value,
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-mistake")
async def analyze_mistake_image(
    image_url: str,
    user_answer: str = "",
    subject: str = "",
):
    """
    错题图片分析（快捷接口）
    
    上传错题图片，AI 自动识别题目并分析错误原因
    """
    try:
        # 先识别图片内容
        question = await AIService.recognize_image(
            image_url=image_url,
            recognize_type="ocr",
        )
        
        # 再进行错题分析
        analysis = await AIService.analyze_mistake(
            question=question,
            user_answer=user_answer,
            subject=subject,
            image_url=image_url,
        )
        
        return {
            "success": True,
            "question": question,
            "analysis": analysis,
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

