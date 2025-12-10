"""
AI 对话 API 路由
支持流式和非流式响应
"""
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from ..models import ChatRequest, ChatResponse
from ..services.ai_service import AIService

router = APIRouter(prefix="/api/chat", tags=["AI 对话"])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    AI 对话接口（非流式）
    
    - **messages**: 对话历史
    - **model_type**: 模型类型 (text/vision/longtext)
    - **temperature**: 生成温度 (0-2)
    - **max_tokens**: 最大生成长度
    - **user_memory**: 用户记忆/画像（可选）
    """
    try:
        # 转换消息格式
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        
        content = await AIService.chat(
            messages=messages,
            model_type=request.model_type,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            user_memory=request.user_memory,
        )
        
        return ChatResponse(success=True, content=content)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """
    AI 对话接口（流式响应 SSE）
    
    返回 Server-Sent Events 格式的流式数据
    """
    try:
        # 转换消息格式
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        
        async def generate():
            try:
                async for chunk in AIService.chat_stream(
                    messages=messages,
                    model_type=request.model_type,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    user_memory=request.user_memory,
                ):
                    # SSE 格式，使用 JSON 编码确保中文字符正确传输
                    # ensure_ascii=False 保持中文可读，但在传输层会被正确编码
                    yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
                
                yield "data: [DONE]\n\n"
                
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        
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

