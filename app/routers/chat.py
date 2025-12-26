"""
AI 对话 API 路由
支持流式和非流式响应
所有对话都与用户关联，保存到数据库
"""
import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from ..models import ChatRequest, ChatResponse
from ..services.ai_service import AIService
from ..db.wxcloud import get_db

router = APIRouter(prefix="/api/chat", tags=["AI 对话"])


def _get_openid_from_request(request: Request) -> Optional[str]:
    """
    从云托管注入的 Header 中提取 openid
    对于聊天功能，openid 为可选（允许未登录使用）
    """
    return (
        request.headers.get("x-wx-openid")
        or request.headers.get("X-WX-OPENID")
    )


async def _save_chat_message(openid: str, role: str, content: str):
    """保存聊天消息到数据库"""
    if not openid:
        return
    try:
        db = get_db()
        await db.add("chat_history", {
            "openid": openid,
            "role": role,
            "content": content,
            "timestamp": {"$date": datetime.now(timezone.utc).isoformat()},
        })
    except Exception:
        # 静默失败，不影响聊天流程
        pass


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, raw_request: Request):
    """
    AI 对话接口（非流式）
    
    - **messages**: 对话历史
    - **model_type**: 模型类型 (text/vision/longtext)
    - **temperature**: 生成温度 (0-2)
    - **max_tokens**: 最大生成长度
    - **user_memory**: 用户记忆/画像（可选）
    
    注：通过 X-WX-OPENID 自动关联用户，保存聊天记录
    """
    try:
        openid = _get_openid_from_request(raw_request)
        
        # 转换消息格式
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        
        # 保存用户消息（最后一条）
        if openid and messages:
            last_user_msg = next((m for m in reversed(messages) if m["role"] == "user"), None)
            if last_user_msg:
                await _save_chat_message(openid, "user", last_user_msg["content"])
        
        content = await AIService.chat(
            messages=messages,
            model_type=request.model_type,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            user_memory=request.user_memory,
            openid=openid,
        )
        
        # 保存 AI 回复
        if openid:
            await _save_chat_message(openid, "assistant", content)
        
        return ChatResponse(success=True, content=content)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def chat_stream(request: ChatRequest, raw_request: Request):
    """
    AI 对话接口（流式响应 SSE）
    
    返回 Server-Sent Events 格式的流式数据
    
    注：通过 X-WX-OPENID 自动关联用户，保存聊天记录
    """
    try:
        openid = _get_openid_from_request(raw_request)
        
        # 转换消息格式
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        
        # 保存用户消息（最后一条）
        if openid and messages:
            last_user_msg = next((m for m in reversed(messages) if m["role"] == "user"), None)
            if last_user_msg:
                await _save_chat_message(openid, "user", last_user_msg["content"])
        
        # 用于收集完整回复
        full_content_holder = {"content": ""}
        
        async def generate():
            try:
                async for chunk in AIService.chat_stream(
                    messages=messages,
                    model_type=request.model_type,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    user_memory=request.user_memory,
                    openid=openid,
                ):
                    full_content_holder["content"] += chunk
                    # SSE 格式，使用 JSON 编码（ensure_ascii=True 默认值）
                    # 中文会被转为 \uXXXX 格式，确保传输的全是 ASCII 字符
                    # 客户端 JSON.parse() 会自动还原中文
                    yield f"data: {json.dumps({'content': chunk})}\n\n"
                
                # 保存 AI 回复
                if openid and full_content_holder["content"]:
                    await _save_chat_message(openid, "assistant", full_content_holder["content"])
                
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

