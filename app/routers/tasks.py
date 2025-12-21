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
    uncompleted_titles: List[str] = []
    for t in tasks:
        if not t.get("completed"):
            title = t.get("title") or ""
            if title:
                uncompleted_titles.append(str(title))
        if len(uncompleted_titles) >= 5:
            break
    return {"total": total, "completed": completed, "completionRate": rate, "uncompletedTitles": uncompleted_titles}


async def _compute_learning_context(openid: str, plan_id: str, carryover_stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    汇总“已学习内容/进度”用于生成今日任务：
    - 昨日未完成任务（carryover）
    - 错题待复盘（mistakes）
    """
    db = get_db()

    # 错题：取最近未掌握的几条
    mistakes = await db.query(
        "mistakes",
        {"openid": openid, "mastered": False},
        limit=5,
        order_by="createdAt",
        order_type="desc",
    )
    simplified_mistakes: List[Dict[str, Any]] = []
    for m in mistakes:
        simplified_mistakes.append(
            {
                "id": m.get("_id") or m.get("id"),
                "topic": (m.get("category") or "") if m.get("category") else None,
                "question": m.get("question") or "",
            }
        )

    carryover = carryover_stats or await _compute_yesterday_stats(openid, plan_id)
    return {"mistakes": simplified_mistakes, "carryover": {"uncompletedTitles": carryover.get("uncompletedTitles", [])}}


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
    learning_context = await _compute_learning_context(openid, plan_id, carryover_stats=yesterday_stats)

    # 使用 AI 生成今日任务（用户要求：不要快速规则生成）
    tasks = await PlanService.generate_daily_tasks(
        domain=domain,
        daily_hours=daily_hours,
        current_phase=current_phase,
        learning_history=learning_history,
        today_stats=yesterday_stats,
        learning_context=learning_context,
    )

    # 并发兜底：若在我们生成期间已有其它请求写入，则直接返回已存在任务，避免重复写入
    existing_after = await db.query(
        "plan_tasks",
        {"openid": openid, "planId": plan_id, "dateStr": today_str},
        limit=200,
        order_by="order",
        order_type="asc",
    )
    if existing_after:
        return {"success": True, "hasActivePlan": True, "isNew": False, "tasks": existing_after}

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
            "generatedBy": "fastapi_ai",
            "calendarDate": today_str,
        }
        new_id = await db.add("plan_tasks", doc)
        doc["_id"] = new_id
        saved.append(doc)

    return {"success": True, "hasActivePlan": True, "isNew": True, "tasks": saved}


@router.get("/today")
async def get_today_tasks(request: Request):
    """
    获取今日任务（不生成）
    - 可选 query: plan_id（避免多 active 计划时串台）
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    plan_repo = PlanRepository(db)

    plan_id_override = request.query_params.get("plan_id") or request.query_params.get("planId")
    plan: Optional[Dict[str, Any]] = None
    if plan_id_override:
        p = await db.get_by_id("study_plans", str(plan_id_override))
        if p and p.get("openid") == openid and p.get("status") == "active":
            plan = p
    if not plan:
        plan = await plan_repo.get_active_plan(openid)
    if not plan:
        return {"success": True, "hasActivePlan": False, "tasks": []}

    plan_id = plan.get("_id") or plan.get("id")
    today_start, today_end = _beijing_day_range(0)
    today_str = (today_start + timedelta(hours=8)).date().isoformat()

    tasks = await db.query(
        "plan_tasks",
        {"openid": openid, "planId": plan_id, "dateStr": today_str},
        limit=200,
        order_by="order",
        order_type="asc",
    )
    if not tasks:
        tasks = await db.query(
            "plan_tasks",
            {"openid": openid, "planId": plan_id, "date": {"$gte": {"$date": today_start.isoformat()}, "$lt": {"$date": today_end.isoformat()}}},
            limit=200,
            order_by="order",
            order_type="asc",
        )
    return {"success": True, "hasActivePlan": True, "dateStr": today_str, "tasks": tasks}


@router.post("/toggle")
async def toggle_task(request: Request):
    """
    完成/取消完成任务（替代云函数 toggleTask，减少中间链条）
    body: { task_id, completed }
    """
    openid = _get_openid_from_request(request)
    db = get_db()

    try:
        body = await request.json()
    except Exception:
        body = {}
    task_id = (body or {}).get("task_id") or (body or {}).get("taskId") or (body or {}).get("id")
    completed = bool((body or {}).get("completed"))
    if not task_id:
        raise HTTPException(status_code=400, detail="缺少 task_id")

    task = await db.get_by_id("plan_tasks", str(task_id))
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.get("openid") != openid:
        raise HTTPException(status_code=403, detail="无权限操作该任务")

    update_data: Dict[str, Any] = {"completed": completed}
    if completed:
        update_data["completedAt"] = {"$date": datetime.now(timezone.utc).isoformat()}
    else:
        update_data["completedAt"] = None

    ok = await db.update_by_id("plan_tasks", str(task_id), update_data)
    if not ok:
        raise HTTPException(status_code=500, detail="更新失败")

    plan_id = task.get("planId")
    if not plan_id:
        return {"success": True}

    today_start, today_end = _beijing_day_range(0)
    today_str = (today_start + timedelta(hours=8)).date().isoformat()

    # 今日进度：优先 dateStr
    today_tasks = await db.query(
        "plan_tasks",
        {"openid": openid, "planId": plan_id, "dateStr": today_str},
        limit=200,
    )
    if not today_tasks:
        today_tasks = await db.query(
            "plan_tasks",
            {"openid": openid, "planId": plan_id, "date": {"$gte": {"$date": today_start.isoformat()}, "$lt": {"$date": today_end.isoformat()}}},
            limit=200,
        )
    today_total = len(today_tasks)
    today_completed = len([t for t in today_tasks if t.get("completed")])
    today_progress = int(round((today_completed / today_total) * 100)) if today_total else 0

    # 总体进度：按任务完成率粗略计算（与云函数逻辑保持一致）
    all_tasks = await db.query("plan_tasks", {"openid": openid, "planId": plan_id}, limit=1000)
    all_total = len(all_tasks)
    all_completed = len([t for t in all_tasks if t.get("completed")])
    overall_progress = int(round((all_completed / all_total) * 100)) if all_total else 0

    # 更新计划进度（兼容云函数的字段结构）
    await db.update_by_id(
        "study_plans",
        str(plan_id),
        {
            "progress": overall_progress,
            "todayProgress": today_progress,
            "progressDetail.taskCompletionRate": overall_progress,
            "progressDetail.todayProgress": today_progress,
            "progressDetail.updatedAt": {"$date": datetime.now(timezone.utc).isoformat()},
        },
    )

    return {
        "success": True,
        "data": {
            "todayProgress": today_progress,
            "overallProgress": overall_progress,
            "completedCount": today_completed,
            "totalCount": today_total,
        },
    }


@router.post("/scheduler/generate-all")
async def scheduler_generate_all_tasks(request: Request):
    """
    定时任务：为所有活跃计划生成明日任务（替代云函数 dailyTaskScheduler）
    
    建议通过云托管的定时任务配置，每天北京时间 0:00 调用此接口
    或通过外部定时任务（如 cron）调用
    
    注意：此接口应设置访问限制，仅允许内部调用
    """
    db = get_db()
    
    # 获取所有活跃计划
    plans = await db.query(
        "study_plans",
        {"status": "active"},
        limit=1000,
    )
    
    results = {
        "total": len(plans),
        "success": 0,
        "failed": 0,
        "errors": [],
    }
    
    tomorrow_start, tomorrow_end = _beijing_day_range(1)
    tomorrow_str = (tomorrow_start + timedelta(hours=8)).date().isoformat()
    now = datetime.now(timezone.utc).isoformat()
    
    for plan in plans:
        try:
            openid = plan.get("openid")
            plan_id = plan.get("_id") or plan.get("id")
            
            if not openid or not plan_id:
                continue
            
            # 检查是否已有明日任务
            existing = await db.query(
                "plan_tasks",
                {"openid": openid, "planId": plan_id, "dateStr": tomorrow_str},
                limit=1,
            )
            
            if existing:
                results["success"] += 1
                continue
            
            # 获取当前阶段
            current_phase = _get_current_phase(plan)
            
            # 生成任务
            domain = plan.get("domainName") or plan.get("domain", "")
            daily_hours = float(plan.get("dailyHours") or 2)
            
            # 获取历史数据
            learning_history = await _compute_learning_history(openid, plan_id)
            
            tasks = await PlanService.generate_daily_tasks(
                domain=domain,
                daily_hours=daily_hours,
                current_phase=current_phase,
                learning_history=learning_history,
            )
            
            # 保存任务
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
                    "date": {"$date": tomorrow_start.isoformat()},
                    "dateStr": tomorrow_str,
                    "createdAt": {"$date": now},
                    "generatedBy": "scheduler",
                }
                await db.add("plan_tasks", doc)
            
            results["success"] += 1
            
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({
                "planId": plan.get("_id"),
                "error": str(e),
            })
    
    return {"success": True, "data": results}

