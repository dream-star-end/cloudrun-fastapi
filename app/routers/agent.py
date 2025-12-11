"""
AI Agent API 路由
提供智能对话接口，支持工具调用和流式响应
"""

import json
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agent import LearningAgent, AgentMemory
from ..agent.memory import MemoryManager


router = APIRouter(prefix="/api/agent", tags=["AI Agent"])


# ==================== 请求/响应模型 ====================

class AgentChatRequest(BaseModel):
    """Agent 对话请求"""
    user_id: str = Field(description="用户ID")
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
async def agent_chat(request: AgentChatRequest):
    """
    与 AI Agent 对话（非流式）
    
    Agent 会根据对话内容自动：
    - 调用相关工具（创建计划、搜索资源等）
    - 更新用户画像
    - 生成个性化回复
    """
    try:
        # 创建 Agent
        memory = MemoryManager.get_memory(request.user_id)
        agent = LearningAgent(
            user_id=request.user_id,
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
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def agent_chat_stream(request: AgentChatRequest):
    """
    与 AI Agent 对话（流式响应 SSE）
    
    实时返回 Agent 的思考过程和回复，包括工具调用通知
    """
    try:
        # 创建 Agent
        memory = MemoryManager.get_memory(request.user_id)
        agent = LearningAgent(
            user_id=request.user_id,
            mode=request.mode,
            memory=memory,
        )
        
        async def generate():
            try:
                async for chunk in agent.chat_stream(
                    message=request.message,
                    context=request.context,
                ):
                    # SSE 格式
                    yield f"data: {json.dumps({'content': chunk})}\n\n"
                
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


@router.get("/profile/{user_id}", response_model=UserProfileResponse)
async def get_user_profile(user_id: str):
    """获取用户画像"""
    try:
        memory = MemoryManager.get_memory(user_id)
        profile = memory.get_user_profile()
        
        return UserProfileResponse(
            success=True,
            profile=profile,
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{user_id}")
async def get_chat_history(
    user_id: str,
    limit: int = Query(default=20, le=100),
):
    """获取对话历史"""
    try:
        memory = MemoryManager.get_memory(user_id)
        history = memory.get_raw_history(limit=limit)
        
        return {
            "success": True,
            "history": history,
            "summary": memory.get_conversation_summary(),
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear-history")
async def clear_chat_history(request: ClearHistoryRequest):
    """清空对话历史"""
    try:
        memory = MemoryManager.get_memory(request.user_id)
        memory.clear_history()
        
        return {"success": True, "message": "对话历史已清空"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/suggestions/{user_id}")
async def get_suggestions(user_id: str):
    """获取个性化建议"""
    try:
        memory = MemoryManager.get_memory(user_id)
        agent = LearningAgent(
            user_id=user_id,
            mode="coach",
            memory=memory,
        )
        
        suggestions = await agent.get_suggestions()
        
        return {
            "success": True,
            "suggestions": suggestions,
        }
        
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

