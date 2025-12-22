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
    import logging
    logger = logging.getLogger(__name__)
    
    openid = _get_openid_from_request(request)
    db = get_db()

    plan_repo = PlanRepository(db)

    # 允许前端显式指定 plan_id，避免在历史遗留"多条 active 计划"时取错计划
    plan_id_override: Optional[str] = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            raw_override = body.get("plan_id") or body.get("planId")
            plan_id_override = str(raw_override) if raw_override else None
    except Exception:
        body = None

    plan: Optional[Dict[str, Any]] = None
    if plan_id_override:
        logger.info(f"[tasks/ensure] 前端指定 plan_id: {plan_id_override}")
        # 校验该 plan_id 归属当前用户且处于 active（否则回退到自动选择）
        p = await db.get_by_id("study_plans", plan_id_override)
        if p and p.get("openid") == openid and p.get("status") == "active":
            plan = p
            logger.info("[tasks/ensure] 使用前端指定的计划")
        else:
            logger.info("[tasks/ensure] 前端指定的计划不存在或不属于当前用户，将自动选择")

    if not plan:
        plan = await plan_repo.get_active_plan(openid)
    if not plan:
        return {"success": True, "hasActivePlan": False, "isNew": False, "tasks": []}

    # 确保 plan_id 是字符串格式
    raw_id = plan.get("_id") or plan.get("id")
    plan_id = str(raw_id) if raw_id else None
    if not plan_id:
        raise HTTPException(status_code=500, detail="学习计划缺少 _id")

    today_start, today_end = _beijing_day_range(0)
    
    # 计算 dateStr (YYYY-MM-DD) 用于精确匹配，避免 Date 类型和时区问题
    today_str = (today_start + timedelta(hours=8)).date().isoformat()
    
    logger.info(f"[tasks/ensure] 查询今日任务: openid={openid[:8]}***, planId={plan_id}, dateStr={today_str}")

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
    logger.info(f"[tasks/ensure] dateStr 查询结果: {len(existing)} 条任务")
    
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
        logger.info(f"[tasks/ensure] date 范围查询结果: {len(existing)} 条任务")

    if existing:
        logger.info("[tasks/ensure] 返回已存在的任务")
        return {"success": True, "hasActivePlan": True, "isNew": False, "tasks": existing}

    # 生成任务（无则写库）
    logger.info("[tasks/ensure] 开始生成今日任务")
    domain = plan.get("domainName") or plan.get("domain") or ""
    daily_hours = float(plan.get("dailyHours") or 2)

    current_phase = _get_current_phase(plan)
    learning_history = await _compute_learning_history(openid, plan_id)
    yesterday_stats = await _compute_yesterday_stats(openid, plan_id)
    learning_context = await _compute_learning_context(openid, plan_id, carryover_stats=yesterday_stats)

    # 注入个性化偏好（若前端/计划已保存）
    personalization = (plan.get("personalization") or plan.get("preferences") or {}) if isinstance(plan, dict) else {}
    if isinstance(personalization, dict):
        learning_context["preferences"] = personalization

    # ========= 动态重排：把昨日未完成任务自动搬到今天 =========
    total_minutes = max(20, int(daily_hours * 60))
    carry_max_minutes = int(total_minutes * 0.6)  # 最多占用当天 60% 时长，避免“越欠越多”
    carry_max_count = 3

    y_start, y_end = _beijing_day_range(-1)
    y_str = (y_start + timedelta(hours=8)).date().isoformat()
    y_tasks = await db.query(
        "plan_tasks",
        {"openid": openid, "planId": plan_id, "dateStr": y_str},
        limit=200,
        order_by="order",
        order_type="asc",
    )
    y_pending = []
    for t in y_tasks:
        if t.get("completed"):
            continue
        # 避免重复搬运
        if t.get("carriedToDateStr") == today_str:
            continue
        y_pending.append(t)

    # 按优先级排序（high > medium > low），同优先级按 order
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    y_pending.sort(key=lambda x: (priority_rank.get(x.get("priority", "medium"), 1), int(x.get("order") or 0)))

    carry_tasks = []
    carry_minutes = 0
    for t in y_pending:
        if len(carry_tasks) >= carry_max_count:
            break
        dur = int(t.get("duration") or 30)
        if carry_minutes + dur > carry_max_minutes:
            continue
        carry_tasks.append(t)
        carry_minutes += dur

    # 写入“搬运任务”
    saved: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    order_cursor = 0
    if carry_tasks:
        logger.info(f"[tasks/ensure] 搬运昨日未完成任务: {len(carry_tasks)} 条, {carry_minutes} 分钟")
        for t in carry_tasks:
            doc = {
                "planId": plan_id,
                "openid": openid,
                "phaseId": (current_phase or {}).get("id") or t.get("phaseId"),
                "title": t.get("title") or "补做任务",
                "description": t.get("description") or "",
                "duration": int(t.get("duration", 30)),
                "priority": t.get("priority", "medium"),
                "type": t.get("type", "review"),
                "completed": False,
                "order": order_cursor,
                "date": {"$date": today_start.isoformat()},
                "dateStr": today_str,
                "createdAt": {"$date": now},
                "generatedBy": "carryover",
                "calendarDate": today_str,
                "carriedFromDateStr": y_str,
                "originTaskId": str(t.get("_id") or t.get("id") or ""),
            }
            new_id = await db.add("plan_tasks", doc)
            doc["_id"] = new_id
            saved.append(doc)
            order_cursor += 1

            # 标记原任务已被搬运（避免反复搬运）
            origin_id = t.get("_id") or t.get("id")
            if origin_id:
                await db.update_by_id("plan_tasks", str(origin_id), {"carriedToDateStr": today_str, "carriedAt": {"$date": now}})

        # 给 AI 一个节奏提示
        learning_context["pace"] = {
            "carryoverMinutes": carry_minutes,
            "missedDays": 1 if (yesterday_stats.get("completionRate", 0) == 0 and yesterday_stats.get("total", 0) > 0) else 0,
        }

    # 使用 AI 生成今日任务（用户要求：不要快速规则生成）
    remaining_minutes = max(0, total_minutes - carry_minutes)
    adjusted_daily_hours = max(0.3, remaining_minutes / 60.0) if remaining_minutes else 0.3
    tasks = await PlanService.generate_daily_tasks(
        domain=domain,
        daily_hours=adjusted_daily_hours,
        current_phase=current_phase,
        learning_history=learning_history,
        today_stats=yesterday_stats,
        learning_context=learning_context,
    )
    logger.info(f"[tasks/ensure] AI 生成了 {len(tasks)} 条任务")

    # 并发兜底：若在我们生成期间已有其它请求写入，则直接返回已存在任务，避免重复写入
    existing_after = await db.query(
        "plan_tasks",
        {"openid": openid, "planId": plan_id, "dateStr": today_str},
        limit=200,
        order_by="order",
        order_type="asc",
    )
    if existing_after:
        logger.info(f"[tasks/ensure] 生成期间已有其他请求写入，返回已存在的 {len(existing_after)} 条任务")
        return {"success": True, "hasActivePlan": True, "isNew": False, "tasks": existing_after}

    # 继续保存 AI 生成的任务（order 接在搬运任务之后）
    for i, t in enumerate(tasks):
        doc = {
            "planId": plan_id,  # 已确保是字符串格式
            "openid": openid,
            "phaseId": (current_phase or {}).get("id"),
            "title": t.get("title", f"任务{i+1}"),
            "description": t.get("description", ""),
            "duration": int(t.get("duration", 30)),
            "priority": t.get("priority", "medium"),
            "type": t.get("type", "learn"),
            "completed": False,
            "order": order_cursor + i,
            "date": {"$date": today_start.isoformat()},
            "dateStr": today_str,  # 新增字段，用于精确查询
            "createdAt": {"$date": now},
            "generatedBy": "fastapi_ai",
            "calendarDate": today_str,
        }
        new_id = await db.add("plan_tasks", doc)
        doc["_id"] = new_id
        saved.append(doc)
    
    logger.info(f"[tasks/ensure] 成功保存 {len(saved)} 条任务，planId={plan_id}, dateStr={today_str}")
    return {"success": True, "hasActivePlan": True, "isNew": True, "tasks": saved}


@router.get("/today")
async def get_today_tasks(request: Request):
    """
    获取今日任务（不生成）
    - 可选 query: plan_id（避免多 active 计划时串台）
    """
    import logging
    logger = logging.getLogger(__name__)
    
    openid = _get_openid_from_request(request)
    db = get_db()
    plan_repo = PlanRepository(db)

    raw_override = request.query_params.get("plan_id") or request.query_params.get("planId")
    plan_id_override = str(raw_override) if raw_override else None
    plan: Optional[Dict[str, Any]] = None
    if plan_id_override:
        p = await db.get_by_id("study_plans", plan_id_override)
        if p and p.get("openid") == openid and p.get("status") == "active":
            plan = p
    if not plan:
        plan = await plan_repo.get_active_plan(openid)
    if not plan:
        return {"success": True, "hasActivePlan": False, "tasks": []}

    # 确保 plan_id 是字符串格式
    raw_id = plan.get("_id") or plan.get("id")
    plan_id = str(raw_id) if raw_id else None
    today_start, today_end = _beijing_day_range(0)
    today_str = (today_start + timedelta(hours=8)).date().isoformat()
    
    logger.info(f"[tasks/today] 查询今日任务: openid={openid[:8]}***, planId={plan_id}, dateStr={today_str}")

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
    
    logger.info(f"[tasks/today] 查询结果: {len(tasks)} 条任务")
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

    raw_plan_id = task.get("planId")
    plan_id = str(raw_plan_id) if raw_plan_id else None
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


@router.post("/migrate-datestr")
async def migrate_datestr(request: Request):
    """
    数据迁移：为旧的 plan_tasks 记录补充 dateStr 字段
    仅需执行一次
    """
    import logging
    logger = logging.getLogger(__name__)
    
    db = get_db()
    
    # 查询所有没有 dateStr 字段的任务（通过 date 字段存在但 dateStr 不存在来判断）
    # 由于云开发数据库不支持 $exists，我们改为查询所有任务然后过滤
    all_tasks = await db.query(
        "plan_tasks",
        {},  # 查询所有
        limit=1000,
    )
    
    migrated_count = 0
    errors = []
    
    for task in all_tasks:
        # 跳过已有 dateStr 的记录
        if task.get("dateStr"):
            continue
        
        task_id = task.get("_id")
        if not task_id:
            continue
        
        # 从 date 字段提取日期
        date_val = task.get("date")
        if not date_val:
            continue
        
        try:
            # 解析 date 字段
            if isinstance(date_val, dict) and "$date" in date_val:
                date_str_raw = date_val["$date"]
                from datetime import datetime
                dt = datetime.fromisoformat(date_str_raw.replace("Z", "+00:00"))
            elif isinstance(date_val, str):
                from datetime import datetime
                dt = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
            else:
                continue
            
            # 转换为北京时间日期字符串
            from datetime import timedelta
            beijing_dt = dt + timedelta(hours=8)
            date_str = beijing_dt.strftime("%Y-%m-%d")
            
            # 更新记录
            await db.update_by_id("plan_tasks", str(task_id), {"dateStr": date_str})
            migrated_count += 1
            logger.info(f"[migrate] 已迁移任务 {task_id}: dateStr={date_str}")
            
        except Exception as e:
            errors.append({"task_id": task_id, "error": str(e)})
            logger.error(f"[migrate] 迁移任务 {task_id} 失败: {e}")
    
    return {
        "success": True,
        "data": {
            "total_tasks": len(all_tasks),
            "migrated": migrated_count,
            "errors": errors,
        }
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
    today_start0, _ = _beijing_day_range(0)
    today_str0 = (today_start0 + timedelta(hours=8)).date().isoformat()
    now = datetime.now(timezone.utc).isoformat()
    
    for plan in plans:
        try:
            openid = plan.get("openid")
            raw_id = plan.get("_id") or plan.get("id")
            plan_id = str(raw_id) if raw_id else None
            
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
            
            # ========= 动态重排：把今日未完成任务自动搬到明天（定时器版）=========
            domain = plan.get("domainName") or plan.get("domain", "")
            daily_hours = float(plan.get("dailyHours") or 2)

            total_minutes = max(20, int(daily_hours * 60))
            carry_max_minutes = int(total_minutes * 0.6)
            carry_max_count = 3

            today_tasks = await db.query(
                "plan_tasks",
                {"openid": openid, "planId": plan_id, "dateStr": today_str0},
                limit=200,
                order_by="order",
                order_type="asc",
            )
            pending_today = []
            for t in today_tasks:
                if t.get("completed"):
                    continue
                if t.get("carriedToDateStr") == tomorrow_str:
                    continue
                pending_today.append(t)
            priority_rank = {"high": 0, "medium": 1, "low": 2}
            pending_today.sort(key=lambda x: (priority_rank.get(x.get("priority", "medium"), 1), int(x.get("order") or 0)))

            carry_tasks = []
            carry_minutes = 0
            for t in pending_today:
                if len(carry_tasks) >= carry_max_count:
                    break
                dur = int(t.get("duration") or 30)
                if carry_minutes + dur > carry_max_minutes:
                    continue
                carry_tasks.append(t)
                carry_minutes += dur

            order_cursor = 0
            for t in carry_tasks:
                doc = {
                    "planId": plan_id,
                    "openid": openid,
                    "phaseId": (current_phase or {}).get("id") or t.get("phaseId"),
                    "title": t.get("title") or "补做任务",
                    "description": t.get("description") or "",
                    "duration": int(t.get("duration", 30)),
                    "priority": t.get("priority", "medium"),
                    "type": t.get("type", "review"),
                    "completed": False,
                    "order": order_cursor,
                    "date": {"$date": tomorrow_start.isoformat()},
                    "dateStr": tomorrow_str,
                    "createdAt": {"$date": now},
                    "generatedBy": "scheduler_carryover",
                    "carriedFromDateStr": today_str0,
                    "originTaskId": str(t.get("_id") or t.get("id") or ""),
                }
                await db.add("plan_tasks", doc)
                order_cursor += 1
                origin_id = t.get("_id") or t.get("id")
                if origin_id:
                    await db.update_by_id("plan_tasks", str(origin_id), {"carriedToDateStr": tomorrow_str, "carriedAt": {"$date": now}})

            remaining_minutes = max(0, total_minutes - carry_minutes)
            adjusted_daily_hours = max(0.3, remaining_minutes / 60.0) if remaining_minutes else 0.3
            
            # 获取历史数据
            learning_history = await _compute_learning_history(openid, plan_id)

            # 注入个性化偏好（若计划已保存）
            personalization = plan.get("personalization") if isinstance(plan, dict) else {}
            learning_context = {
                "carryover": {"uncompletedTitles": [t.get("title") for t in pending_today[:5] if t.get("title")]},
                "preferences": personalization if isinstance(personalization, dict) else {},
                "pace": {"carryoverMinutes": carry_minutes},
            }

            tasks = await PlanService.generate_daily_tasks(
                domain=domain,
                daily_hours=adjusted_daily_hours,
                current_phase=current_phase,
                learning_history=learning_history,
                learning_context=learning_context,
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
                    "order": order_cursor + i,
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

