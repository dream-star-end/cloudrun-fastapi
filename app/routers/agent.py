"""
AI Agent API 路由
提供智能对话接口，支持工具调用和流式响应
所有 Agent 对话都与用户关联（通过 X-WX-OPENID）
"""

import json
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agent import LearningAgent, AgentMemory
from ..agent.memory import MemoryManager


router = APIRouter(prefix="/api/agent", tags=["AI Agent"])


def _get_openid_from_request(request: Request) -> str:
    """
    从云托管注入的 Header 中提取 openid
    对于 Agent 功能，openid 是必需的
    """
    openid = (
        request.headers.get("x-wx-openid")
        or request.headers.get("X-WX-OPENID")
    )
    if not openid:
        raise HTTPException(
            status_code=401,
            detail="缺少用户身份（X-WX-OPENID），请使用 wx.cloud.callContainer 内网调用",
        )
    return openid


# ==================== 请求/响应模型 ====================

class AgentChatRequest(BaseModel):
    """Agent 对话请求"""
    # user_id 改为可选，优先使用请求头中的 openid
    user_id: Optional[str] = Field(default=None, description="用户ID（已废弃，使用请求头中的 X-WX-OPENID）")
    message: str = Field(description="用户消息")
    mode: str = Field(default="coach", description="Agent 模式: coach(教练)/reader(伴读)")
    context: Optional[dict] = Field(default=None, description="额外上下文（如当前阅读内容）")


class AgentChatResponse(BaseModel):
    """Agent 对话响应"""
    success: bool
    content: str
    suggestions: Optional[List[str]] = None


class UserProfileResponse(BaseModel):
    """用户画像响应"""
    success: bool
    profile: dict


class ClearHistoryRequest(BaseModel):
    """清空历史请求"""
    user_id: str


# ==================== API 端点 ====================

@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(request: AgentChatRequest, raw_request: Request):
    """
    与 AI Agent 对话（非流式）
    
    Agent 会根据对话内容自动：
    - 调用相关工具（创建计划、搜索资源等）
    - 更新用户画像
    - 生成个性化回复
    
    注：用户身份通过 X-WX-OPENID 请求头获取（云托管自动注入）
    """
    try:
        # 优先从请求头获取 openid，兼容旧版请求体中的 user_id
        openid = _get_openid_from_request(raw_request)
        
        # 创建 Agent
        memory = MemoryManager.get_memory(openid)
        agent = LearningAgent(
            user_id=openid,
            mode=request.mode,
            memory=memory,
        )
        
        # 对话
        response = await agent.chat(
            message=request.message,
            context=request.context,
        )
        
        # 获取建议
        suggestions = await agent.get_suggestions()
        
        return AgentChatResponse(
            success=True,
            content=response,
            suggestions=suggestions,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def json_encode_for_sse(obj) -> str:
    """
    将对象编码为 SSE 安全的 JSON 字符串
    
    使用 ensure_ascii=True 确保所有 Unicode 字符（包括 emoji）
    都被正确转义为 JSON 标准的 \\uXXXX 格式
    
    对于超出 BMP 的字符（如 emoji），JSON 会自动使用代理对表示
    例如：📊 -> \\ud83d\\udcca
    """
    return json.dumps(obj, ensure_ascii=True)


@router.post("/chat/stream")
async def agent_chat_stream(request: AgentChatRequest, raw_request: Request):
    """
    与 AI Agent 对话（流式响应 SSE）
    
    实时返回 Agent 的思考过程和回复，包括工具调用通知
    
    事件类型：
    - text: 文本内容流
    - tool_start: 工具调用开始，包含工具名称、描述、输入参数
    - tool_end: 工具调用结束，包含执行结果
    - tool_error: 工具调用出错
    
    注：用户身份通过 X-WX-OPENID 请求头获取（云托管自动注入）
    """
    try:
        # 优先从请求头获取 openid
        openid = _get_openid_from_request(raw_request)
        
        # 创建 Agent
        memory = MemoryManager.get_memory(openid)
        agent = LearningAgent(
            user_id=openid,
            mode=request.mode,
            memory=memory,
        )
        
        async def generate():
            try:
                async for event in agent.chat_stream(
                    message=request.message,
                    context=request.context,
                ):
                    # 使用 ensure_ascii=True 确保所有 Unicode 都转义为 \uXXXX 格式
                    # 这是 JSON 标准格式，JavaScript 可以正确解析
                    safe_json = json_encode_for_sse(event)
                    yield f"data: {safe_json}\n\n"
                
                yield "data: [DONE]\n\n"
                
            except Exception as e:
                error_event = {"type": "error", "error": str(e)}
                safe_json = json_encode_for_sse(error_event)
                yield f"data: {safe_json}\n\n"
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profile/{user_id}", response_model=UserProfileResponse)
async def get_user_profile(user_id: str, raw_request: Request):
    """
    获取用户画像
    
    注：user_id 路径参数已废弃，实际使用 X-WX-OPENID 请求头
    """
    try:
        # 优先从请求头获取 openid，兼容旧版 URL 参数
        openid = _get_openid_from_request(raw_request)
        
        memory = MemoryManager.get_memory(openid)
        profile = memory.get_user_profile()
        
        return UserProfileResponse(
            success=True,
            profile=profile,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{user_id}")
async def get_chat_history(
    user_id: str,
    raw_request: Request,
    limit: int = Query(default=20, le=100),
):
    """
    获取对话历史
    
    注：user_id 路径参数已废弃，实际使用 X-WX-OPENID 请求头
    """
    try:
        # 优先从请求头获取 openid
        openid = _get_openid_from_request(raw_request)
        
        memory = MemoryManager.get_memory(openid)
        history = memory.get_raw_history(limit=limit)
        
        return {
            "success": True,
            "history": history,
            "summary": memory.get_conversation_summary(),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear-history")
async def clear_chat_history(request: ClearHistoryRequest, raw_request: Request):
    """
    清空对话历史
    
    注：请求体中的 user_id 已废弃，实际使用 X-WX-OPENID 请求头
    """
    try:
        # 优先从请求头获取 openid
        openid = _get_openid_from_request(raw_request)
        
        memory = MemoryManager.get_memory(openid)
        memory.clear_history()
        
        return {"success": True, "message": "对话历史已清空"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/suggestions/{user_id}")
async def get_suggestions(user_id: str, raw_request: Request):
    """
    获取个性化建议
    
    注：user_id 路径参数已废弃，实际使用 X-WX-OPENID 请求头
    """
    try:
        # 优先从请求头获取 openid
        openid = _get_openid_from_request(raw_request)
        
        memory = MemoryManager.get_memory(openid)
        agent = LearningAgent(
            user_id=openid,
            mode="coach",
            memory=memory,
        )
        
        suggestions = await agent.get_suggestions()
        
        return {
            "success": True,
            "suggestions": suggestions,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_agent_stats():
    """获取 Agent 系统统计"""
    try:
        stats = MemoryManager.get_stats()
        return {
            "success": True,
            "stats": stats,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

