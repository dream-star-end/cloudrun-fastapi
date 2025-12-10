"""
联网搜索 API 路由
"""
from fastapi import APIRouter, HTTPException
from typing import Optional, List
from ..models import SearchRequest, SearchResponse
from ..services.search_service import SearchService

router = APIRouter(prefix="/api/search", tags=["联网搜索"])


@router.post("", response_model=SearchResponse)
async def search(request: SearchRequest):
    """
    联网搜索接口
    
    - **query**: 搜索关键词
    - **search_depth**: 搜索深度 (basic/advanced)
    - **max_results**: 最大结果数 (1-20)
    - **include_domains**: 限定搜索域名（可选）
    """
    try:
        result = await SearchService.search(
            query=request.query,
            search_depth=request.search_depth.value,
            max_results=request.max_results,
            include_domains=request.include_domains,
        )
        
        return SearchResponse(
            success=result.get("success", False),
            query=result.get("query", request.query),
            answer=result.get("answer"),
            results=result.get("results", []),
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/learning-resources")
async def search_learning_resources(
    topic: str,
    resource_type: str = "all",
):
    """
    搜索学习资源（快捷接口）
    
    - **topic**: 学习主题
    - **resource_type**: 资源类型 (all/video/article/course)
    """
    try:
        result = await SearchService.search_learning_resources(
            topic=topic,
            resource_type=resource_type,
        )
        
        return {
            "success": result.get("success", False),
            "topic": topic,
            "resource_type": resource_type,
            "answer": result.get("answer"),
            "results": result.get("results", []),
            "formatted_message": SearchService.format_search_result_message(result),
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

