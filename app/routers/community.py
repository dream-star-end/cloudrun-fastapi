"""
学习社区 API 路由

功能：
- 分享学习计划
- 获取社区计划列表（热门/最新/我的分享）
- 点赞/取消点赞
- 评论
- 复制使用计划
- 社区统计
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..db.wxcloud import get_db, PlanRepository

router = APIRouter(prefix="/api/community", tags=["学习社区"])


# ==================== 请求/响应模型 ====================

class SharePlanRequest(BaseModel):
    planId: str
    title: str
    description: Optional[str] = ""


class CommentRequest(BaseModel):
    planId: str
    content: str
    replyTo: Optional[str] = None


class LikeRequest(BaseModel):
    planId: str
    liked: bool


class UsePlanRequest(BaseModel):
    planId: str


class ListRequest(BaseModel):
    tab: str = "hot"  # hot, new, mine
    page: int = 0
    pageSize: int = 10


# ==================== 工具函数 ====================

def _get_openid_from_request(request: Request) -> str:
    openid = request.headers.get("x-wx-openid") or request.headers.get("X-WX-OPENID")
    if not openid:
        raise HTTPException(
            status_code=401,
            detail="缺少用户身份（X-WX-OPENID），请使用 wx.cloud.callContainer 内网调用",
        )
    return openid


async def _get_user_info(db, openid: str) -> dict:
    """获取用户基本信息"""
    user = await db.get("users", {"openid": openid})
    if user:
        return {
            "openid": openid,
            "nickName": user.get("nickName", "学习者"),
            "avatarUrl": user.get("avatarUrl", ""),
        }
    return {
        "openid": openid,
        "nickName": "学习者",
        "avatarUrl": "",
    }


# ==================== API 路由 ====================

@router.get("/stats")
async def get_community_stats(request: Request):
    """
    获取社区统计数据
    用于首页展示社区概览
    """
    db = get_db()
    
    try:
        # 统计分享的计划数量
        plans = await db.query(
            "shared_plans",
            {"status": "active"},
            limit=1,
        )
        # 由于没有直接的 count 方法，我们用 query 统计
        all_plans = await db.query(
            "shared_plans",
            {"status": "active"},
            limit=10000,
        )
        plan_count = len(all_plans)
        
        # 统计活跃用户数（有分享或有评论的用户）
        user_openids = set()
        for p in all_plans:
            if p.get("openid"):
                user_openids.add(p.get("openid"))
        
        comments = await db.query(
            "community_comments",
            {"status": "active"},
            limit=10000,
        )
        for c in comments:
            if c.get("openid"):
                user_openids.add(c.get("openid"))
        
        user_count = len(user_openids)
        
        return {
            "success": True,
            "data": {
                "planCount": plan_count,
                "userCount": user_count,
            }
        }
    except Exception as e:
        return {
            "success": True,
            "data": {
                "planCount": 0,
                "userCount": 0,
            }
        }


@router.post("/plans/list")
async def get_community_plans(request: Request, body: ListRequest):
    """
    获取社区计划列表
    支持：热门(hot)、最新(new)、我的分享(mine)
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    tab = body.tab
    page = body.page
    page_size = body.pageSize
    
    # 构建查询条件
    query = {"status": "active"}
    if tab == "mine":
        query["openid"] = openid
    
    # 排序方式
    order_by = "publishedAt"
    order_type = "desc"
    if tab == "hot":
        # 热门按点赞数+使用数排序（简化处理：按点赞数）
        order_by = "likeCount"
    
    # 查询
    plans = await db.query(
        "shared_plans",
        query,
        limit=page_size,
        skip=page * page_size,
        order_by=order_by,
        order_type=order_type,
    )
    
    # 检查当前用户是否点赞了这些计划
    plan_ids = [str(p.get("_id") or p.get("id")) for p in plans if p.get("_id") or p.get("id")]
    user_likes = {}
    if plan_ids:
        likes = await db.query(
            "community_likes",
            {"openid": openid, "planId": {"$in": plan_ids}},
            limit=len(plan_ids),
        )
        for like in likes:
            user_likes[like.get("planId")] = True
    
    # 组装结果
    result_plans = []
    for p in plans:
        plan_id = str(p.get("_id") or p.get("id"))
        result_plans.append({
            **p,
            "_id": plan_id,
            "isLiked": user_likes.get(plan_id, False),
        })
    
    return {
        "success": True,
        "data": {
            "plans": result_plans,
        }
    }


@router.post("/share")
async def share_plan(request: Request, body: SharePlanRequest):
    """
    分享学习计划到社区
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    plan_id = body.planId
    title = body.title
    description = body.description or ""
    
    if not title.strip():
        raise HTTPException(status_code=400, detail="请输入分享标题")
    
    # 检查是否已分享过此计划
    existing = await db.get(
        "shared_plans",
        {"openid": openid, "originalPlanId": plan_id, "status": "active"}
    )
    if existing:
        raise HTTPException(status_code=400, detail="此计划已分享过")
    
    # 获取原计划
    plan = await db.get_by_id("study_plans", plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")
    
    # 兼容嵌套数据结构
    if "data" in plan and isinstance(plan.get("data"), dict) and "openid" not in plan:
        plan = {**plan.get("data"), "_id": plan.get("_id")}
    
    if plan.get("openid") != openid:
        raise HTTPException(status_code=403, detail="只能分享自己的计划")
    
    # 获取用户信息
    author = await _get_user_info(db, openid)
    
    # 创建分享记录
    now = datetime.now(timezone.utc).isoformat()
    shared_plan = {
        "openid": openid,
        "originalPlanId": plan_id,
        "title": title.strip(),
        "description": description.strip(),
        # 计划快照
        "goal": plan.get("goal", ""),
        "domain": plan.get("domain", ""),
        "domainName": plan.get("domainName", ""),
        "dailyHours": plan.get("dailyHours", 2),
        "currentLevel": plan.get("currentLevel", "beginner"),
        "totalDuration": plan.get("totalDuration", ""),
        "phases": plan.get("phases", []),
        # 作者信息
        "author": author,
        # 统计
        "likeCount": 0,
        "commentCount": 0,
        "useCount": 0,
        "viewCount": 0,
        # 状态
        "status": "active",
        "publishedAt": {"$date": now},
        "createdAt": {"$date": now},
        "updatedAt": {"$date": now},
    }
    
    shared_id = await db.add("shared_plans", shared_plan)
    shared_plan["_id"] = shared_id
    
    return {
        "success": True,
        "data": {
            "sharedPlan": shared_plan,
        }
    }


@router.post("/like")
async def toggle_like(request: Request, body: LikeRequest):
    """
    点赞/取消点赞
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    plan_id = body.planId
    liked = body.liked
    
    # 检查计划是否存在
    plan = await db.get_by_id("shared_plans", plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")
    
    # 检查是否已点赞
    existing_like = await db.get(
        "community_likes",
        {"planId": plan_id, "openid": openid}
    )
    
    now = datetime.now(timezone.utc).isoformat()
    
    if liked:
        # 点赞
        if not existing_like:
            await db.add("community_likes", {
                "planId": plan_id,
                "openid": openid,
                "createdAt": {"$date": now},
            })
            # 更新计划点赞数
            await db.update_by_id(
                "shared_plans",
                plan_id,
                {"likeCount": (plan.get("likeCount") or 0) + 1}
            )
    else:
        # 取消点赞
        if existing_like:
            like_id = str(existing_like.get("_id") or existing_like.get("id"))
            await db.delete_by_id("community_likes", like_id)
            # 更新计划点赞数
            await db.update_by_id(
                "shared_plans",
                plan_id,
                {"likeCount": max(0, (plan.get("likeCount") or 0) - 1)}
            )
    
    return {
        "success": True,
        "data": {
            "liked": liked,
        }
    }


@router.post("/comments/list")
async def get_comments(request: Request):
    """
    获取计划评论列表
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    try:
        body = await request.json()
    except:
        body = {}
    
    plan_id = body.get("planId")
    if not plan_id:
        raise HTTPException(status_code=400, detail="缺少 planId")
    
    comments = await db.query(
        "community_comments",
        {"planId": plan_id, "status": "active"},
        limit=100,
        order_by="createdAt",
        order_type="desc",
    )
    
    return {
        "success": True,
        "data": {
            "comments": comments,
        }
    }


@router.post("/comment")
async def add_comment(request: Request, body: CommentRequest):
    """
    添加评论
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    plan_id = body.planId
    content = body.content
    reply_to = body.replyTo
    
    if not content.strip():
        raise HTTPException(status_code=400, detail="请输入评论内容")
    
    if len(content) > 500:
        raise HTTPException(status_code=400, detail="评论内容不能超过500字")
    
    # 检查计划是否存在
    plan = await db.get_by_id("shared_plans", plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")
    
    # 获取用户信息
    author = await _get_user_info(db, openid)
    
    now = datetime.now(timezone.utc).isoformat()
    comment = {
        "planId": plan_id,
        "openid": openid,
        "content": content.strip(),
        "author": author,
        "replyTo": reply_to,
        "status": "active",
        "createdAt": {"$date": now},
    }
    
    comment_id = await db.add("community_comments", comment)
    comment["_id"] = comment_id
    
    # 更新计划评论数
    await db.update_by_id(
        "shared_plans",
        plan_id,
        {"commentCount": (plan.get("commentCount") or 0) + 1}
    )
    
    return {
        "success": True,
        "data": {
            "comment": comment,
        }
    }


@router.post("/use")
async def use_plan(request: Request, body: UsePlanRequest):
    """
    使用（复制）社区计划
    将社区计划复制为用户自己的计划
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    plan_id = body.planId
    
    # 获取分享的计划
    shared_plan = await db.get_by_id("shared_plans", plan_id)
    if not shared_plan:
        raise HTTPException(status_code=404, detail="计划不存在")
    
    if shared_plan.get("status") != "active":
        raise HTTPException(status_code=400, detail="该计划已下架")
    
    # 将现有活跃计划置为 archived
    await db.update(
        "study_plans",
        {"openid": openid, "status": "active"},
        {"status": "archived"},
    )
    
    # 为每个阶段生成新 ID
    phases = shared_plan.get("phases", [])
    for i, phase in enumerate(phases):
        phase["id"] = f"phase_{i+1}_{uuid.uuid4().hex[:8]}"
        phase["status"] = "completed"
    
    # 获取领域名称
    domain = shared_plan.get("domain", "")
    domain_names = {
        "postgraduate": "考研",
        "english": "英语学习",
        "programming": "编程技术",
        "certification": "职业认证",
        "academic": "学业提升",
        "other": "其他",
    }
    domain_name = domain_names.get(domain, shared_plan.get("domainName", domain))
    
    now = datetime.now(timezone.utc).isoformat()
    new_plan = {
        "openid": openid,
        "goal": shared_plan.get("goal", shared_plan.get("title", "")),
        "domain": domain,
        "domainName": domain_name,
        "deadline": None,  # 用户可以之后自己设置
        "dailyHours": shared_plan.get("dailyHours", 2),
        "currentLevel": shared_plan.get("currentLevel", "beginner"),
        "personalization": {},
        "status": "active",
        "progress": 0,
        "todayProgress": 0,
        "completedDays": 0,
        "phases": phases,
        "totalDuration": shared_plan.get("totalDuration", ""),
        "dailySchedule": [],
        "tips": [],
        # 记录来源
        "copiedFromSharedPlanId": plan_id,
        "copiedFromOpenid": shared_plan.get("openid"),
        "createdAt": {"$date": now},
        "updatedAt": {"$date": now},
    }
    
    new_plan_id = await db.add("study_plans", new_plan)
    new_plan["_id"] = new_plan_id
    
    # 更新分享计划的使用次数
    await db.update_by_id(
        "shared_plans",
        plan_id,
        {"useCount": (shared_plan.get("useCount") or 0) + 1}
    )
    
    return {
        "success": True,
        "data": {
            "plan": new_plan,
        }
    }


@router.post("/delete")
async def delete_shared_plan(request: Request):
    """
    删除（下架）分享的计划
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    try:
        body = await request.json()
    except:
        body = {}
    
    plan_id = body.get("planId")
    if not plan_id:
        raise HTTPException(status_code=400, detail="缺少 planId")
    
    # 获取分享的计划
    shared_plan = await db.get_by_id("shared_plans", plan_id)
    if not shared_plan:
        raise HTTPException(status_code=404, detail="计划不存在")
    
    if shared_plan.get("openid") != openid:
        raise HTTPException(status_code=403, detail="只能删除自己分享的计划")
    
    # 软删除
    now = datetime.now(timezone.utc).isoformat()
    await db.update_by_id(
        "shared_plans",
        plan_id,
        {"status": "deleted", "deletedAt": {"$date": now}}
    )
    
    return {
        "success": True,
        "message": "已删除",
    }

