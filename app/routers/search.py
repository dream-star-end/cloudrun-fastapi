"""
联网搜索 API 路由
搜索记录可与用户关联
"""
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Request
from ..models import SearchRequest, SearchResponse
from ..services.search_service import SearchService
from ..db.wxcloud import get_db

router = APIRouter(prefix="/api/search", tags=["联网搜索"])


def _get_openid_from_request(request: Request) -> Optional[str]:
    """
    从云托管注入的 Header 中提取 openid
    对于搜索功能，openid 为可选
    """
    return (
        request.headers.get("x-wx-openid")
        or request.headers.get("X-WX-OPENID")
    )


async def _save_search_record(openid: str, query: str, search_type: str, result_count: int):
    """保存搜索记录到数据库（可选功能）"""
    if not openid:
        return
    try:
        db = get_db()
        await db.add("search_records", {
            "openid": openid,
            "query": query,
            "searchType": search_type,
            "resultCount": result_count,
            "createdAt": {"$date": datetime.now(timezone.utc).isoformat()},
        })
    except Exception:
        # 静默失败，不影响搜索流程
        pass


@router.post("", response_model=SearchResponse)
async def search(request: SearchRequest, raw_request: Request):
    """
    联网搜索接口
    
    - **query**: 搜索关键词
    - **search_depth**: 搜索深度 (basic/advanced)
    - **max_results**: 最大结果数 (1-20)
    - **include_domains**: 限定搜索域名（可选）
    
    注：通过 X-WX-OPENID 自动关联用户
    """
    try:
        openid = _get_openid_from_request(raw_request)
        
        result = await SearchService.search(
            query=request.query,
            search_depth=request.search_depth.value,
            max_results=request.max_results,
            include_domains=request.include_domains,
        )
        
        # 保存搜索记录
        if openid:
            await _save_search_record(
                openid,
                request.query,
                "general",
                len(result.get("results", []))
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
    raw_request: Request,
    topic: str,
    resource_type: str = "all",
):
    """
    搜索学习资源（快捷接口）
    
    - **topic**: 学习主题
    - **resource_type**: 资源类型 (all/video/article/course)
    
    注：通过 X-WX-OPENID 自动关联用户
    """
    try:
        openid = _get_openid_from_request(raw_request)
        
        result = await SearchService.search_learning_resources(
            topic=topic,
            resource_type=resource_type,
        )
        
        # 保存搜索记录
        if openid:
            await _save_search_record(
                openid,
                topic,
                f"learning-resources-{resource_type}",
                len(result.get("results", []))
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

