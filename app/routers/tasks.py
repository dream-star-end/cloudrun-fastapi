"""
任务相关 API 路由

核心能力：
- 确保今日任务存在：如果今日无任务，则基于学习计划自动生成并写入数据库

说明：
- 小程序通过 wx.cloud.callContainer 内网调用时，云托管会注入用户身份 Header（如 X-WX-OPENID）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, Optional, Tuple, List

from fastapi import APIRouter, HTTPException, Request

from ..db.wxcloud import get_db, PlanRepository
from ..services.plan_service import PlanService


router = APIRouter(prefix="/api/tasks", tags=["任务"])


def _get_openid_from_request(request: Request) -> str:
    """
    从云托管注入的 Header 中提取 openid。
    常见 header（大小写不敏感）：
    - X-WX-OPENID
    - X-WX-OPENID / x-wx-openid
    """
    # Starlette headers 是大小写不敏感的，但这里兼容不同写法
    openid = (
        request.headers.get("x-wx-openid")
        or request.headers.get("X-WX-OPENID")
        or request.headers.get("x-wx-openid".upper())
    )
    if not openid:
        raise HTTPException(status_code=401, detail="缺少用户身份（X-WX-OPENID），请使用 wx.cloud.callContainer 内网调用")
    return openid


def _beijing_day_range(days_offset: int = 0) -> Tuple[datetime, datetime]:
    """
    获取北京时间（UTC+8）某天的 [dayStart, dayEnd) 对应的 UTC 时间点。
    与云函数的 Date.UTC(...)-offset 逻辑一致，便于跨端用范围查询。
    """
    now_utc = datetime.now(timezone.utc)
    beijing_now = now_utc + timedelta(hours=8)
    # 取北京时间日期，然后换回 UTC（减 8 小时）
    beijing_day = (beijing_now.date() + timedelta(days=days_offset))
    day_start_utc = datetime(beijing_day.year, beijing_day.month, beijing_day.day, tzinfo=timezone.utc) - timedelta(hours=8)
    day_end_utc = day_start_utc + timedelta(days=1)
    return day_start_utc, day_end_utc


def _parse_datetime_maybe(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, dict) and "$date" in value and isinstance(value["$date"], str):
        s = value["$date"].replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None
    if isinstance(value, str):
        s = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None
    return None


def _parse_phase_duration_days(duration: str) -> int:
    if not duration:
        return 7
    m = re.search(r"(\d+)\s*(周|天|月)", str(duration))
    if not m:
        return 7
    num = int(m.group(1))
    unit = m.group(2)
    if unit == "天":
        return num
    if unit == "周":
        return num * 7
    if unit == "月":
        return num * 30
    return 7


def _get_current_phase(plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    phases = plan.get("phases") or []
    if not phases:
        return None

    created_at = _parse_datetime_maybe(plan.get("createdAt"))
    if not created_at:
        return phases[0]

    now_utc = datetime.now(timezone.utc)
    days_since_start = int((now_utc - created_at).total_seconds() // (24 * 3600))

    accumulated = 0
    for phase in phases:
        accumulated += _parse_phase_duration_days(str(phase.get("duration", "")))
        if days_since_start < accumulated:
            return phase
    return phases[-1]


async def _compute_learning_history(openid: str, plan_id: str) -> Dict[str, Any]:
    db = get_db()
    today_start, _ = _beijing_day_range(0)
    start_7d = today_start - timedelta(days=7)

    tasks = await db.query(
        "plan_tasks",
        {
            "openid": openid,
            "planId": plan_id,
            "date": {"$gte": {"$date": start_7d.isoformat()}, "$lt": {"$date": (today_start + timedelta(days=1)).isoformat()}},
        },
        limit=1000,
        order_by="date",
        order_type="desc",
    )

    total = len(tasks)
    completed = len([t for t in tasks if t.get("completed")])
    avg_completion_rate = int(round((completed / total) * 100)) if total else 0
    return {
        "totalTasks": total,
        "completedTasks": completed,
        "avgCompletionRate": avg_completion_rate,
    }


async def _compute_yesterday_stats(openid: str, plan_id: str) -> Dict[str, Any]:
    db = get_db()
    y_start, y_end = _beijing_day_range(-1)
    tasks = await db.query(
        "plan_tasks",
        {
            "openid": openid,
            "planId": plan_id,
            "date": {"$gte": {"$date": y_start.isoformat()}, "$lt": {"$date": y_end.isoformat()}},
        },
        limit=1000,
    )
    total = len(tasks)
    completed = len([t for t in tasks if t.get("completed")])
    rate = int(round((completed / total) * 100)) if total else 0
    return {"total": total, "completed": completed, "completionRate": rate}


@router.post("/today/ensure")
async def ensure_today_tasks(request: Request):
    """
    确保今日任务存在：
    - 若今日已有任务：直接返回
    - 若今日无任务：基于活跃学习计划生成任务并写入 plan_tasks，再返回
    """
    openid = _get_openid_from_request(request)
    db = get_db()

    plan_repo = PlanRepository(db)

    # 允许前端显式指定 plan_id，避免在历史遗留“多条 active 计划”时取错计划
    plan_id_override: Optional[str] = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            plan_id_override = body.get("plan_id") or body.get("planId")
    except Exception:
        body = None

    plan: Optional[Dict[str, Any]] = None
    if plan_id_override:
        # 校验该 plan_id 归属当前用户且处于 active（否则回退到自动选择）
        p = await db.get_by_id("study_plans", str(plan_id_override))
        if p and p.get("openid") == openid and p.get("status") == "active":
            plan = p

    if not plan:
        plan = await plan_repo.get_active_plan(openid)
    if not plan:
        return {"success": True, "hasActivePlan": False, "isNew": False, "tasks": []}

    plan_id = plan.get("_id") or plan.get("id")
    if not plan_id:
        raise HTTPException(status_code=500, detail="学习计划缺少 _id")

    today_start, today_end = _beijing_day_range(0)
    
    # 计算 dateStr (YYYY-MM-DD) 用于精确匹配，避免 Date 类型和时区问题
    today_str = (today_start + timedelta(hours=8)).date().isoformat()

    # 1. 尝试通过 dateStr 查询 (新版逻辑)
    existing = await db.query(
        "plan_tasks",
        {
            "openid": openid,
            "planId": plan_id,
            "dateStr": today_str,
        },
        limit=200,
        order_by="order",
        order_type="asc",
    )
    
    # 2. 如果没找到，尝试通过 date 范围查询 (兼容旧数据)
    if not existing:
        existing = await db.query(
            "plan_tasks",
            {
                "openid": openid,
                "planId": plan_id,
                "date": {"$gte": {"$date": today_start.isoformat()}, "$lt": {"$date": today_end.isoformat()}},
            },
            limit=200,
            order_by="order",
            order_type="asc",
        )

    if existing:
        return {"success": True, "hasActivePlan": True, "isNew": False, "tasks": existing}

    # 生成任务（无则写库）
    domain = plan.get("domainName") or plan.get("domain") or ""
    daily_hours = float(plan.get("dailyHours") or 2)

    current_phase = _get_current_phase(plan)
    learning_history = await _compute_learning_history(openid, plan_id)
    yesterday_stats = await _compute_yesterday_stats(openid, plan_id)

    tasks = await PlanService.generate_daily_tasks(
        domain=domain,
        daily_hours=daily_hours,
        current_phase=current_phase,
        learning_history=learning_history,
        today_stats=yesterday_stats,
    )

    saved: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    for i, t in enumerate(tasks):
        doc = {
            "planId": plan_id,
            "openid": openid,
            "phaseId": (current_phase or {}).get("id"),
            "title": t.get("title", f"任务{i+1}"),
            "description": t.get("description", ""),
            "duration": int(t.get("duration", 30)),
            "priority": t.get("priority", "medium"),
            "type": t.get("type", "learn"),
            "completed": False,
            "order": i,
            "date": {"$date": today_start.isoformat()},
            "dateStr": today_str,  # 新增字段，用于精确查询
            "createdAt": {"$date": now},
            "generatedBy": "fastapi",
        }
        new_id = await db.add("plan_tasks", doc)
        doc["_id"] = new_id
        saved.append(doc)

    return {"success": True, "hasActivePlan": True, "isNew": True, "tasks": saved}


