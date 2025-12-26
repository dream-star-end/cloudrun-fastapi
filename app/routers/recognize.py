"""
图片识别 API 路由
支持 OCR、图片解释、公式识别等
支持流式和非流式响应
所有识别记录可与用户关联
"""
import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from ..models import RecognizeRequest, RecognizeResponse
from ..services.ai_service import AIService
from ..db.wxcloud import get_db

router = APIRouter(prefix="/api/recognize", tags=["图片识别"])


def _get_openid_from_request(request: Request) -> Optional[str]:
    """
    从云托管注入的 Header 中提取 openid
    对于识别功能，openid 为可选
    """
    return (
        request.headers.get("x-wx-openid")
        or request.headers.get("X-WX-OPENID")
    )


async def _save_recognize_record(openid: str, image_url: str, recognize_type: str, result: str):
    """保存识别记录到数据库（可选功能）"""
    if not openid:
        return
    try:
        db = get_db()
        await db.add("recognize_records", {
            "openid": openid,
            "imageUrl": image_url,
            "recognizeType": recognize_type,
            "result": result[:2000] if result else "",  # 限制长度
            "createdAt": {"$date": datetime.now(timezone.utc).isoformat()},
        })
    except Exception:
        # 静默失败，不影响识别流程
        pass


@router.post("", response_model=RecognizeResponse)
async def recognize_image(request: RecognizeRequest, raw_request: Request):
    """
    图片识别接口（非流式）
    
    - **image_url**: 图片 URL（支持 http/https/base64）
    - **recognize_type**: 识别类型
        - `ocr`: 文字识别
        - `explain`: 图片解释
        - `summary`: 内容总结
        - `formula`: 公式识别
    - **custom_prompt**: 自定义提示词（可选）
    
    注：通过 X-WX-OPENID 自动关联用户
    """
    try:
        openid = _get_openid_from_request(raw_request)
        
        result = await AIService.recognize_image(
            image_url=request.image_url,
            recognize_type=request.recognize_type.value,
            custom_prompt=request.custom_prompt,
            openid=openid,
        )
        
        # 保存识别记录
        if openid:
            await _save_recognize_record(
                openid,
                request.image_url,
                request.recognize_type.value,
                result
            )
        
        return RecognizeResponse(
            success=True,
            result=result,
            recognize_type=request.recognize_type.value,
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def recognize_image_stream(request: RecognizeRequest, raw_request: Request):
    """
    图片识别接口（流式响应 SSE）
    
    返回 Server-Sent Events 格式的流式数据
    
    - **image_url**: 图片 URL（支持 http/https/base64）
    - **recognize_type**: 识别类型
        - `ocr`: 文字识别
        - `explain`: 图片解释
        - `summary`: 内容总结
        - `formula`: 公式识别
    - **custom_prompt**: 自定义提示词（可选）
    
    注：通过 X-WX-OPENID 自动关联用户
    """
    try:
        openid = _get_openid_from_request(raw_request)
        
        # 用于收集完整结果
        full_result_holder = {"content": ""}
        
        async def generate():
            try:
                async for chunk in AIService.recognize_image_stream(
                    image_url=request.image_url,
                    recognize_type=request.recognize_type.value,
                    custom_prompt=request.custom_prompt,
                    openid=openid,
                ):
                    full_result_holder["content"] += chunk
                    # SSE 格式，使用 JSON 编码（ensure_ascii=True 默认值）
                    # 中文会被转为 \uXXXX 格式，确保传输的全是 ASCII 字符
                    yield f"data: {json.dumps({'content': chunk})}\n\n"
                
                # 保存识别记录
                if openid and full_result_holder["content"]:
                    await _save_recognize_record(
                        openid,
                        request.image_url,
                        request.recognize_type.value,
                        full_result_holder["content"]
                    )
                
                yield "data: [DONE]\n\n"
                
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-mistake")
async def analyze_mistake_image(
    raw_request: Request,
    image_url: str,
    user_answer: str = "",
    subject: str = "",
):
    """
    错题图片分析（快捷接口）
    
    上传错题图片，AI 自动识别题目并分析错误原因
    
    注：通过 X-WX-OPENID 自动关联用户
    """
    try:
        openid = _get_openid_from_request(raw_request)
        
        # 先识别图片内容
        question = await AIService.recognize_image(
            image_url=image_url,
            recognize_type="ocr",
            openid=openid,
        )
        
        # 再进行错题分析
        analysis = await AIService.analyze_mistake(
            question=question,
            user_answer=user_answer,
            subject=subject,
            image_url=image_url,
            openid=openid,
        )
        
        # 保存识别记录
        if openid:
            await _save_recognize_record(
                openid,
                image_url,
                "analyze-mistake",
                f"题目：{question}\n分析：{analysis}"
            )
        
        return {
            "success": True,
            "question": question,
            "analysis": analysis,
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

