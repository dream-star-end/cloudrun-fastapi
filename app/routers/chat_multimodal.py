"""
多模态聊天 API 路由
支持文本、图片、语音输入，使用智能模型路由

Requirements: 6.1, 6.2, 6.3, 6.4
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.model_router import ModelRouter
from ..services.model_config_service import ModelConfigService
from ..db.wxcloud import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["多模态对话"])


class MultimodalMessage(BaseModel):
    """多模态消息"""
    text: Optional[str] = Field(default=None, description="文本内容")
    image_url: Optional[str] = Field(default=None, description="图片URL（云存储）")
    image_base64: Optional[str] = Field(default=None, description="图片Base64编码")
    voice_text: Optional[str] = Field(default=None, description="语音转文本结果")
    voice_url: Optional[str] = Field(default=None, description="语音文件URL")


class HistoryMessage(BaseModel):
    """历史消息"""
    role: str = Field(description="角色: user/assistant/system")
    content: str = Field(description="消息内容")


class DocumentContext(BaseModel):
    """文档上下文（文档伴读场景）"""
    title: Optional[str] = Field(default=None, description="文档标题")
    content: Optional[str] = Field(default=None, description="文档内容")
    page: Optional[int] = Field(default=None, description="当前页码")


class MultimodalChatRequest(BaseModel):
    """多模态聊天请求"""
    message: MultimodalMessage = Field(description="当前消息")
    history: List[HistoryMessage] = Field(default=[], description="对话历史")
    context: Optional[DocumentContext] = Field(default=None, description="文档上下文")
    stream: bool = Field(default=True, description="是否流式响应")
    user_memory: Optional[dict] = Field(default=None, description="用户记忆/画像")


def _get_openid_from_request(request: Request) -> Optional[str]:
    """
    从云托管注入的 Header 中提取 openid
    """
    return (
        request.headers.get("x-wx-openid")
        or request.headers.get("X-WX-OPENID")
    )


async def _save_chat_message(openid: str, role: str, content: str, msg_type: str = "text"):
    """保存聊天消息到数据库"""
    if not openid:
        return
    try:
        db = get_db()
        await db.add("chat_history", {
            "openid": openid,
            "role": role,
            "content": content,
            "msg_type": msg_type,
            "timestamp": {"$date": datetime.now(timezone.utc).isoformat()},
        })
    except Exception as e:
        logger.warning(f"[ChatMultimodal] 保存消息失败: {e}")


def _get_message_content_for_save(message: MultimodalMessage) -> tuple:
    """
    获取用于保存的消息内容和类型
    
    Returns:
        (content, msg_type)
    """
    if message.image_url or message.image_base64:
        content = message.text or "[图片]"
        if message.image_url:
            content = f"{content}\n[图片: {message.image_url}]"
        return content, "image"
    elif message.voice_text:
        return message.voice_text, "voice"
    else:
        return message.text or "", "text"


@router.post("/multimodal")
async def chat_multimodal(request: MultimodalChatRequest, raw_request: Request):
    """
    多模态聊天接口（支持流式 SSE）
    
    支持的输入类型：
    - 纯文本：message.text
    - 图片：message.image_url 或 message.image_base64
    - 语音（已转文本）：message.voice_text
    - 文本+图片：同时提供 text 和 image_url
    
    流式响应事件类型：
    - text: 文本内容片段
    - fallback_notice: 模型降级通知
    - error: 错误信息
    - done: 完成信号
    
    注：通过 X-WX-OPENID 自动关联用户
    """
    openid = _get_openid_from_request(raw_request)
    
    if not openid:
        logger.warning("[ChatMultimodal] 请求缺少 openid")
        raise HTTPException(status_code=401, detail="未授权：缺少用户标识")
    
    logger.info(f"[ChatMultimodal] 收到请求: openid={openid[:8]}..., stream={request.stream}")
    
    # 验证消息内容
    msg = request.message
    if not any([msg.text, msg.image_url, msg.image_base64, msg.voice_text]):
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    
    # 保存用户消息
    user_content, msg_type = _get_message_content_for_save(msg)
    await _save_chat_message(openid, "user", user_content, msg_type)
    
    # 转换历史消息格式
    history = [{"role": h.role, "content": h.content} for h in request.history]
    
    # 转换上下文
    context = None
    if request.context:
        context = {
            "title": request.context.title,
            "content": request.context.content,
            "page": request.context.page,
        }
    
    # 转换消息格式
    message_dict = {
        "text": msg.text,
        "image_url": msg.image_url,
        "image_base64": msg.image_base64,
        "voice_text": msg.voice_text,
        "voice_url": msg.voice_url,
    }
    
    if request.stream:
        return await _stream_response(
            openid=openid,
            message=message_dict,
            history=history,
            context=context,
            user_memory=request.user_memory,
        )
    else:
        return await _non_stream_response(
            openid=openid,
            message=message_dict,
            history=history,
            context=context,
            user_memory=request.user_memory,
        )


async def _stream_response(
    openid: str,
    message: dict,
    history: list,
    context: Optional[dict],
    user_memory: Optional[dict],
):
    """
    流式响应处理
    """
    full_content_holder = {"content": ""}
    
    async def generate():
        try:
            async for event in ModelRouter.route_and_call(
                openid=openid,
                message=message,
                history=history,
                context=context,
                stream=True,
                user_memory=user_memory,
            ):
                event_type = event.get("type", "unknown")
                
                if event_type == "text":
                    content = event.get("content", "")
                    full_content_holder["content"] += content
                    
                    # 构建 SSE 事件
                    sse_data = {"type": "text", "content": content}
                    
                    # 如果有降级信息，附加到第一个文本事件
                    if event.get("fallback_used"):
                        sse_data["fallback_used"] = True
                        sse_data["fallback_reason"] = event.get("fallback_reason")
                    
                    yield f"data: {json.dumps(sse_data)}\n\n"
                
                elif event_type == "fallback_notice":
                    yield f"data: {json.dumps(event)}\n\n"
                
                elif event_type == "error":
                    yield f"data: {json.dumps({'type': 'error', 'error': event.get('error', '未知错误')})}\n\n"
                
                elif event_type == "done":
                    # 保存 AI 回复
                    if full_content_holder["content"]:
                        await _save_chat_message(openid, "assistant", full_content_holder["content"])
                    
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
            # 如果没有收到 done 事件，也要保存
            if full_content_holder["content"]:
                await _save_chat_message(openid, "assistant", full_content_holder["content"])
            
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error(f"[ChatMultimodal] 流式响应错误: {type(e).__name__}: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _non_stream_response(
    openid: str,
    message: dict,
    history: list,
    context: Optional[dict],
    user_memory: Optional[dict],
):
    """
    非流式响应处理
    """
    try:
        full_content = ""
        fallback_info = None
        
        async for event in ModelRouter.route_and_call(
            openid=openid,
            message=message,
            history=history,
            context=context,
            stream=False,
            user_memory=user_memory,
        ):
            event_type = event.get("type", "unknown")
            
            if event_type == "text":
                full_content += event.get("content", "")
                if event.get("fallback_used"):
                    fallback_info = {
                        "used": True,
                        "reason": event.get("fallback_reason"),
                    }
            
            elif event_type == "fallback_notice":
                fallback_info = {
                    "used": True,
                    "reason": event.get("fallback_reason"),
                    "message": event.get("message"),
                }
            
            elif event_type == "error":
                raise HTTPException(status_code=500, detail=event.get("error", "未知错误"))
        
        # 保存 AI 回复
        if full_content:
            await _save_chat_message(openid, "assistant", full_content)
        
        response = {
            "success": True,
            "content": full_content,
        }
        
        if fallback_info:
            response["fallback"] = fallback_info
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ChatMultimodal] 非流式响应错误: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/model-config")
async def get_model_config(raw_request: Request):
    """
    获取当前用户的模型配置
    
    返回用户配置的默认模型信息
    """
    openid = _get_openid_from_request(raw_request)
    
    if not openid:
        raise HTTPException(status_code=401, detail="未授权：缺少用户标识")
    
    try:
        config = await ModelConfigService.get_user_config(openid)
        
        return {
            "success": True,
            "data": {
                "defaults": config.get("defaults", {}),
                "has_text_model": bool(config.get("defaults", {}).get("text")),
                "has_voice_model": bool(config.get("defaults", {}).get("voice")),
                "has_multimodal_model": bool(config.get("defaults", {}).get("multimodal")),
            }
        }
    except Exception as e:
        logger.error(f"[ChatMultimodal] 获取配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
