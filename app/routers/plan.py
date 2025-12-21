"""
学习计划 API 路由

完整功能（替代云函数）：
- 获取活跃计划
- 保存计划
- 删除计划
- 生成计划
- 生成阶段详情
- 获取目标达成率
- 生成明日任务
"""
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..db.wxcloud import get_db, PlanRepository
from ..models import (
    AnalyzeMistakeRequest,
    AnalyzeMistakeResponse,
    GeneratePlanRequest,
    GeneratePlanResponse,
    GenerateTasksRequest,
    GenerateTasksResponse,
)
from ..services.ai_service import AIService
from ..services.plan_service import PlanService

router = APIRouter(prefix="/api/plan", tags=["学习计划"])


# ==================== 工具函数 ====================


def _get_openid_from_request(request: Request) -> str:
    openid = request.headers.get("x-wx-openid") or request.headers.get("X-WX-OPENID")
    if not openid:
        raise HTTPException(
            status_code=401,
            detail="缺少用户身份（X-WX-OPENID），请使用 wx.cloud.callContainer 内网调用",
        )
    return openid


def _beijing_now() -> datetime:
    """获取北京时间"""
    return datetime.now(timezone.utc) + timedelta(hours=8)


def _beijing_day_range(days_offset: int = 0):
    """获取北京时间某天的 UTC 时间范围"""
    now_utc = datetime.now(timezone.utc)
    beijing_now = now_utc + timedelta(hours=8)
    beijing_day = beijing_now.date() + timedelta(days=days_offset)
    day_start_utc = (
        datetime(beijing_day.year, beijing_day.month, beijing_day.day, tzinfo=timezone.utc)
        - timedelta(hours=8)
    )
    day_end_utc = day_start_utc + timedelta(days=1)
    return day_start_utc, day_end_utc


def _beijing_date_str(days_offset: int = 0) -> str:
    """获取北京时间日期字符串 YYYY-MM-DD"""
    today_start, _ = _beijing_day_range(days_offset)
    return (today_start + timedelta(hours=8)).date().isoformat()


def _parse_phase_duration_days(duration: str) -> int:
    """解析阶段时长为天数"""
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
    """获取当前学习阶段"""
    phases = plan.get("phases") or []
    if not phases:
        return None

    created_at = plan.get("createdAt")
    if isinstance(created_at, dict) and "$date" in created_at:
        try:
            created_at = datetime.fromisoformat(created_at["$date"].replace("Z", "+00:00"))
        except Exception:
            created_at = None
    elif isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except Exception:
            created_at = None

    if not created_at:
        return phases[0]

    now_utc = datetime.now(timezone.utc)
    days_since_start = int((now_utc - created_at).total_seconds() // (24 * 3600))

    accumulated = 0
    for i, phase in enumerate(phases):
        accumulated += _parse_phase_duration_days(str(phase.get("duration", "")))
        if days_since_start < accumulated:
            return {**phase, "index": i + 1}
    return {**phases[-1], "index": len(phases)}


def _calculate_remaining_days(plan: Dict[str, Any]) -> Optional[int]:
    """计算剩余天数"""
    deadline = plan.get("deadline")
    if not deadline:
        return None
    try:
        if isinstance(deadline, str):
            deadline_date = datetime.strptime(deadline, "%Y-%m-%d").date()
        else:
            return None
        today = _beijing_now().date()
        return (deadline_date - today).days
    except Exception:
        return None


# ==================== 计划管理 API ====================


@router.get("/whoami")
async def whoami(request: Request):
    """
    获取当前用户身份信息
    用于前端获取并缓存 openid，以便在流式请求中使用
    """
    openid = _get_openid_from_request(request)
    return {"success": True, "openid": openid}


@router.get("/active")
async def get_active_plan(request: Request):
    """
    获取当前活跃计划 + 今日任务
    """
    import logging
    logger = logging.getLogger(__name__)
    
    openid = _get_openid_from_request(request)
    db = get_db()
    plan_repo = PlanRepository(db)

    plan = await plan_repo.get_active_plan(openid)
    if not plan:
        return {"success": True, "hasActivePlan": False, "plan": None, "todayTasks": []}

    # 确保 plan_id 是字符串格式
    raw_id = plan.get("_id") or plan.get("id")
    plan_id = str(raw_id) if raw_id else None
    if not plan_id:
        raise HTTPException(status_code=500, detail="学习计划缺少 _id")

    today_str = _beijing_date_str(0)
    
    logger.info(f"[plan/active] 查询今日任务: openid={openid[:8]}***, planId={plan_id}, dateStr={today_str}")

    # 查询今日任务
    tasks = await db.query(
        "plan_tasks",
        {"openid": openid, "planId": plan_id, "dateStr": today_str},
        limit=200,
        order_by="order",
        order_type="asc",
    )
    logger.info(f"[plan/active] dateStr 查询结果: {len(tasks)} 条任务")
    
    if not tasks:
        today_start, today_end = _beijing_day_range(0)
        tasks = await db.query(
            "plan_tasks",
            {
                "openid": openid,
                "planId": plan_id,
                "date": {
                    "$gte": {"$date": today_start.isoformat()},
                    "$lt": {"$date": today_end.isoformat()},
                },
            },
            limit=200,
            order_by="order",
            order_type="asc",
        )
        logger.info(f"[plan/active] date 范围查询结果: {len(tasks)} 条任务")

    # 补充计划派生字段
    plan["daysLeft"] = _calculate_remaining_days(plan)
    current_phase = _get_current_phase(plan)
    if current_phase:
        plan["currentPhase"] = current_phase

    return {
        "success": True,
        "hasActivePlan": True,
        "plan": plan,
        "todayTasks": tasks,
        "dateStr": today_str,
    }


@router.post("/save")
async def save_plan(request: Request):
    """
    保存学习计划（替代云函数 savePlan）
    - 将旧的 active 计划置为 archived
    - 保存新计划
    """
    openid = _get_openid_from_request(request)
    db = get_db()

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体格式错误")

    plan_data = body.get("plan") or {}
    goal = body.get("goal") or plan_data.get("goal", "")
    domain = body.get("domain") or plan_data.get("domain", "")
    deadline = body.get("deadline") or plan_data.get("deadline")
    daily_hours = float(body.get("dailyHours") or body.get("daily_hours") or 2)
    current_level = body.get("currentLevel") or body.get("current_level") or "beginner"

    # 获取领域名称
    domain_names = {
        "postgraduate": "考研",
        "english": "英语学习",
        "programming": "编程技术",
        "certification": "职业认证",
        "academic": "学业提升",
        "other": "其他",
    }
    domain_name = domain_names.get(domain, domain)

    # 将现有 active 计划置为 archived
    await db.update(
        "study_plans",
        {"openid": openid, "status": "active"},
        {"status": "archived"},
    )

    # 为每个阶段生成 ID
    phases = plan_data.get("phases") or []
    for i, phase in enumerate(phases):
        if not phase.get("id"):
            phase["id"] = f"phase_{i+1}_{uuid.uuid4().hex[:8]}"
        phase["status"] = "completed"  # 框架已生成，后续可补充详情

    now = datetime.now(timezone.utc).isoformat()
    new_plan = {
        "openid": openid,
        "goal": goal,
        "domain": domain,
        "domainName": domain_name,
        "deadline": deadline,
        "dailyHours": daily_hours,
        "currentLevel": current_level,
        "status": "active",
        "progress": 0,
        "todayProgress": 0,
        "completedDays": 0,
        "phases": phases,
        "totalDuration": plan_data.get("total_duration") or plan_data.get("totalDuration", ""),
        "dailySchedule": plan_data.get("daily_schedule") or plan_data.get("dailySchedule", []),
        "tips": plan_data.get("tips", []),
        "createdAt": {"$date": now},
        "updatedAt": {"$date": now},
    }

    plan_id = await db.add("study_plans", new_plan)
    new_plan["_id"] = plan_id

    return {"success": True, "data": {"planId": plan_id, "plan": new_plan}}


@router.post("/delete")
async def delete_plan(request: Request):
    """
    删除当前活跃计划（置为 deleted 状态）
    """
    openid = _get_openid_from_request(request)
    db = get_db()

    # 获取当前活跃计划
    plan_repo = PlanRepository(db)
    plan = await plan_repo.get_active_plan(openid)
    if not plan:
        return {"success": True, "message": "没有活跃的计划"}

    # 确保 plan_id 是字符串格式
    raw_id = plan.get("_id") or plan.get("id")
    plan_id = str(raw_id) if raw_id else None

    # 将计划置为 deleted
    await db.update_by_id(
        "study_plans",
        plan_id,
        {"status": "deleted", "deletedAt": {"$date": datetime.now(timezone.utc).isoformat()}},
    )

    # 删除关联的任务（可选：也可以保留历史记录）
    await db.delete("plan_tasks", {"planId": plan_id})

    return {"success": True, "message": "计划已删除"}


# ==================== 计划生成 API ====================


@router.post("/generate", response_model=GeneratePlanResponse)
async def generate_plan(request: GeneratePlanRequest):
    """
    AI 生成学习计划
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[plan/generate] 收到请求: goal={request.goal[:50] if request.goal else ''}, domain={request.domain}")
    logger.info(f"[plan/generate] 参数: daily_hours={request.daily_hours}, deadline={request.deadline}, level={request.current_level}")
    
    try:
        result = await PlanService.generate_study_plan(
            goal=request.goal,
            domain=request.domain,
            daily_hours=request.daily_hours,
            deadline=request.deadline,
            current_level=request.current_level,
            preferences=request.preferences,
        )

        logger.info(f"[plan/generate] AI 生成结果: success={result.get('success')}")
        
        if result.get("success"):
            return GeneratePlanResponse(success=True, plan=result.get("plan"))
        else:
            error_msg = result.get("error", "生成失败")
            logger.error(f"[plan/generate] 生成失败: {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[plan/generate] 异常: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"计划生成异常: {str(e)}")


@router.post("/generate/stream")
async def generate_plan_stream(request: GeneratePlanRequest):
    """
    AI 生成学习计划（流式响应）
    
    返回 Server-Sent Events 格式：
    - data: {"type": "progress", "message": "..."} - 进度更新
    - data: {"type": "content", "content": "..."} - AI 原始输出片段
    - data: {"type": "result", "success": true, "plan": {...}} - 最终结果
    - data: {"type": "error", "error": "..."} - 错误信息
    - data: [DONE] - 结束标记
    """
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"[plan/generate/stream] 收到请求: goal={request.goal[:50] if request.goal else ''}, domain={request.domain}")
    
    async def generate():
        full_content = ""
        
        try:
            # 发送进度更新
            yield f"data: {json.dumps({'type': 'progress', 'message': '正在分析学习目标...'})}\n\n"
            
            # 构建 prompt
            prompt = PlanService._build_plan_prompt(
                request.goal,
                request.domain,
                request.daily_hours,
                request.deadline,
                request.current_level,
                request.preferences,
            )
            
            messages = [{"role": "user", "content": prompt}]
            
            yield f"data: {json.dumps({'type': 'progress', 'message': '正在生成学习计划...'})}\n\n"
            
            # 流式调用 AI
            async for chunk in AIService.chat_stream(
                messages=messages,
                model_type="text",
                temperature=0.7,
                max_tokens=4000,
            ):
                full_content += chunk
                # 发送内容片段
                yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"
            
            yield f"data: {json.dumps({'type': 'progress', 'message': '正在解析计划结构...'})}\n\n"
            
            # 解析 JSON
            json_match = re.search(r'\{[\s\S]*\}', full_content)
            if json_match:
                try:
                    plan = json.loads(json_match.group())
                    logger.info(f"[plan/generate/stream] 计划解析成功, phases数量: {len(plan.get('phases', []))}")
                    yield f"data: {json.dumps({'type': 'result', 'success': True, 'plan': plan})}\n\n"
                except json.JSONDecodeError as je:
                    logger.error(f"[plan/generate/stream] JSON 解析失败: {je}")
                    yield f"data: {json.dumps({'type': 'error', 'error': f'JSON解析失败: {str(je)}'})}\n\n"
            else:
                logger.error("[plan/generate/stream] AI 响应中未找到 JSON")
                yield f"data: {json.dumps({'type': 'error', 'error': '计划格式错误，未找到有效JSON'})}\n\n"
                
        except Exception as e:
            logger.error(f"[plan/generate/stream] 异常: {type(e).__name__}: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
        
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/phase-detail")
async def generate_phase_detail(request: Request):
    """
    生成学习阶段详情（替代云函数 generatePhaseDetail）
    """
    import logging
    logger = logging.getLogger(__name__)
    
    openid = _get_openid_from_request(request)
    db = get_db()

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体格式错误")

    plan_id = body.get("planId") or body.get("plan_id")
    phase_id = body.get("phaseId") or body.get("phase_id")

    if not plan_id or not phase_id:
        raise HTTPException(status_code=400, detail="缺少 planId 或 phaseId")

    logger.info(f"[phase-detail] 请求: planId={plan_id}, phaseId={phase_id}, openid={openid[:8] if openid else 'None'}***")

    # 获取计划
    plan = await db.get_by_id("study_plans", plan_id)
    
    if not plan:
        logger.error(f"[phase-detail] 计划不存在: planId={plan_id}")
        raise HTTPException(status_code=404, detail=f"计划不存在: {plan_id}")
    
    # 兼容旧版数据结构：如果数据被嵌套在 data 字段中，则提取出来
    # 这是由于之前 nodedb 的 add() 调用使用了错误的 { data: ... } 包装
    if "data" in plan and isinstance(plan.get("data"), dict) and "openid" not in plan:
        logger.warning("[phase-detail] 检测到旧版嵌套数据结构，正在提取...")
        nested_data = plan.get("data")
        plan = {**nested_data, "_id": plan.get("_id")}
    
    plan_openid = plan.get("openid")
    logger.info(f"[phase-detail] 计划查询结果: plan_openid={plan_openid[:8] if plan_openid else 'None'}***, plan_keys={list(plan.keys())[:5]}")
    
    if plan_openid != openid:
        logger.warning(f"[phase-detail] openid不匹配: request={openid[:8] if openid else 'None'}***, plan={plan_openid[:8] if plan_openid else 'None'}***")
        raise HTTPException(status_code=403, detail=f"无权访问该计划 (plan_openid={plan_openid[:8] if plan_openid else 'None'}***)")

    # 找到对应阶段
    phases = plan.get("phases") or []
    phase = None
    phase_index = -1
    for i, p in enumerate(phases):
        if p.get("id") == phase_id:
            phase = p
            phase_index = i
            break

    if not phase:
        raise HTTPException(status_code=404, detail="阶段不存在")

    # 调用 AI 生成详情
    result = await PlanService.generate_phase_detail(
        phase_name=phase.get("name", ""),
        phase_goals=phase.get("goals", []),
        domain=plan.get("domainName") or plan.get("domain", ""),
        duration=phase.get("duration", "1周"),
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "生成失败"))

    detail = result.get("detail", {})

    # 更新阶段信息
    updated_phase = {
        **phase,
        "status": "completed",
        "keyPoints": detail.get("key_points", []),
        "resources": [
            {"name": r.get("name", ""), "type": r.get("type", "")}
            for r in detail.get("learning_resources", [])
        ],
        "milestone": (
            detail.get("milestones", [{}])[0].get("goal", "") if detail.get("milestones") else ""
        ),
        "goals": phase.get("goals", []) or detail.get("practice_suggestions", []),
    }

    # 更新数据库
    phases[phase_index] = updated_phase
    await db.update_by_id("study_plans", plan_id, {"phases": phases})

    return {"success": True, "data": {"phaseDetail": updated_phase}}


@router.post("/phase-detail/stream")
async def generate_phase_detail_stream(request: Request):
    """
    生成学习阶段详情（流式响应）
    
    返回 Server-Sent Events 格式：
    - data: {"type": "progress", "message": "..."} - 进度更新
    - data: {"type": "content", "content": "..."} - AI 原始输出片段
    - data: {"type": "result", "success": true, "phaseDetail": {...}} - 最终结果
    - data: {"type": "error", "error": "..."} - 错误信息
    - data: [DONE] - 结束标记
    """
    import logging
    logger = logging.getLogger(__name__)
    
    openid = _get_openid_from_request(request)
    db = get_db()

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体格式错误")

    plan_id = body.get("planId") or body.get("plan_id")
    phase_id = body.get("phaseId") or body.get("phase_id")

    if not plan_id or not phase_id:
        raise HTTPException(status_code=400, detail="缺少 planId 或 phaseId")

    # 获取计划
    plan = await db.get_by_id("study_plans", plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="计划不存在")
    
    # 兼容旧版嵌套数据结构
    if "data" in plan and isinstance(plan.get("data"), dict) and "openid" not in plan:
        nested_data = plan.get("data")
        plan = {**nested_data, "_id": plan.get("_id")}
    
    if plan.get("openid") != openid:
        raise HTTPException(status_code=403, detail="无权访问该计划")

    # 找到对应阶段
    phases = plan.get("phases") or []
    phase = None
    phase_index = -1
    for i, p in enumerate(phases):
        if p.get("id") == phase_id:
            phase = p
            phase_index = i
            break

    if not phase:
        raise HTTPException(status_code=404, detail="阶段不存在")

    async def generate():
        full_content = ""
        
        try:
            yield f"data: {json.dumps({'type': 'progress', 'message': '正在分析阶段目标...'})}\n\n"
            
            yield f"data: {json.dumps({'type': 'progress', 'message': '正在生成阶段详情...'})}\n\n"
            
            # 流式调用 AI
            async for chunk in PlanService.generate_phase_detail_stream(
                phase_name=phase.get("name", ""),
                phase_goals=phase.get("goals", []),
                domain=plan.get("domainName") or plan.get("domain", ""),
                duration=phase.get("duration", "1周"),
            ):
                full_content += chunk
                yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"
            
            yield f"data: {json.dumps({'type': 'progress', 'message': '正在解析阶段详情...'})}\n\n"
            
            # 解析 JSON
            json_match = re.search(r'\{[\s\S]*\}', full_content)
            if json_match:
                try:
                    detail = json.loads(json_match.group())
                    
                    # 更新阶段信息
                    updated_phase = {
                        **phase,
                        "status": "completed",
                        "keyPoints": detail.get("key_points", []),
                        "resources": [
                            {"name": r.get("name", ""), "type": r.get("type", "")}
                            for r in detail.get("learning_resources", [])
                        ],
                        "milestone": (
                            detail.get("milestones", [{}])[0].get("goal", "") if detail.get("milestones") else ""
                        ),
                        "goals": phase.get("goals", []) or detail.get("practice_suggestions", []),
                    }
                    
                    # 更新数据库
                    phases[phase_index] = updated_phase
                    await db.update_by_id("study_plans", plan_id, {"phases": phases})
                    
                    yield f"data: {json.dumps({'type': 'result', 'success': True, 'phaseDetail': updated_phase})}\n\n"
                except json.JSONDecodeError as je:
                    logger.error(f"[phase-detail/stream] JSON 解析失败: {je}")
                    yield f"data: {json.dumps({'type': 'error', 'error': f'JSON解析失败: {str(je)}'})}\n\n"
            else:
                logger.error("[phase-detail/stream] AI 响应中未找到 JSON")
                yield f"data: {json.dumps({'type': 'error', 'error': '生成格式错误，未找到有效JSON'})}\n\n"
                
        except Exception as e:
            logger.error(f"[phase-detail/stream] 异常: {type(e).__name__}: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
        
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== 目标达成率 API ====================


@router.get("/achievement")
async def get_achievement_rate(request: Request):
    """
    获取目标达成率（替代云函数 getAchievementRate）
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    plan_repo = PlanRepository(db)

    plan = await plan_repo.get_active_plan(openid)
    if not plan:
        return {"success": True, "data": {"hasActivePlan": False}}

    # 确保 plan_id 是字符串格式
    raw_id = plan.get("_id") or plan.get("id")
    plan_id = str(raw_id) if raw_id else None

    # 计算任务完成率（最近7天）
    today_start, _ = _beijing_day_range(0)
    week_start = today_start - timedelta(days=7)

    all_tasks = await db.query(
        "plan_tasks",
        {
            "openid": openid,
            "planId": plan_id,
            "date": {
                "$gte": {"$date": week_start.isoformat()},
                "$lt": {"$date": (today_start + timedelta(days=1)).isoformat()},
            },
        },
        limit=500,
    )

    total_tasks = len(all_tasks)
    completed_tasks = len([t for t in all_tasks if t.get("completed")])
    task_completion_rate = int(round((completed_tasks / total_tasks) * 100)) if total_tasks else 0

    # 计算阶段进度
    current_phase = _get_current_phase(plan)
    phases = plan.get("phases") or []
    phase_progress = 0
    if current_phase and phases:
        phase_index = current_phase.get("index", 1)
        phase_progress = int(round((phase_index / len(phases)) * 100))

    # 计算学习活跃度（有任务的天数 / 7）
    active_days = len(set(t.get("dateStr") or "" for t in all_tasks if t.get("dateStr")))
    activity_rate = int(round((active_days / 7) * 100))

    # 综合达成率（加权平均）
    achievement_rate = int(
        round(task_completion_rate * 0.5 + phase_progress * 0.3 + activity_rate * 0.2)
    )

    # 达成等级
    if achievement_rate >= 80:
        level = "excellent"
        analysis = "学习进度非常棒！保持这个节奏，目标指日可待 🎉"
    elif achievement_rate >= 60:
        level = "good"
        analysis = "学习状态良好，继续努力，可以适当增加挑战 💪"
    elif achievement_rate >= 40:
        level = "warning"
        analysis = "学习进度稍慢，建议每天固定时间学习，养成习惯 📚"
    else:
        level = "danger"
        analysis = "需要调整学习计划，建议减少单次任务量，降低难度 🌱"

    # 预测
    remaining_days = _calculate_remaining_days(plan)
    prediction = ""
    if remaining_days and remaining_days > 0:
        if achievement_rate >= 70:
            prediction = "按当前进度，预计可以在截止日期前完成目标"
        else:
            prediction = f"还有 {remaining_days} 天，建议增加每日学习时间以确保达成目标"

    # 建议
    suggestions = []
    if task_completion_rate < 60:
        suggestions.append("尝试将大任务拆分成小步骤，更容易完成")
    if activity_rate < 70:
        suggestions.append("设置固定的学习时间，保持每日打卡")
    if phase_progress < 50 and remaining_days and remaining_days < 30:
        suggestions.append("时间紧迫，建议集中精力攻克当前阶段重点")

    return {
        "success": True,
        "data": {
            "hasActivePlan": True,
            "achievementRate": achievement_rate,
            "achievementLevel": level,
            "achievementAnalysis": analysis,
            "achievementPrediction": prediction,
            "taskCompletionRate": task_completion_rate,
            "phaseProgress": phase_progress,
            "activityRate": activity_rate,
            "remainingDays": remaining_days,
            "suggestions": suggestions,
        },
    }


# ==================== 明日任务 API ====================


@router.post("/tomorrow-tasks")
async def generate_tomorrow_tasks(request: Request):
    """
    生成明日任务（替代云函数 generateTomorrowTasks）
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    plan_repo = PlanRepository(db)

    plan = await plan_repo.get_active_plan(openid)
    if not plan:
        raise HTTPException(status_code=404, detail="没有活跃的学习计划")

    # 确保 plan_id 是字符串格式
    raw_id = plan.get("_id") or plan.get("id")
    plan_id = str(raw_id) if raw_id else None
    tomorrow_str = _beijing_date_str(1)
    tomorrow_start, tomorrow_end = _beijing_day_range(1)

    # 检查是否已有明日任务
    existing = await db.query(
        "plan_tasks",
        {"openid": openid, "planId": plan_id, "dateStr": tomorrow_str},
        limit=100,
    )
    if existing:
        return {
            "success": True,
            "data": {
                "tasks": existing,
                "isNew": False,
                "message": "明日任务已存在",
            },
        }

    # 获取学习上下文
    today_str = _beijing_date_str(0)
    today_tasks = await db.query(
        "plan_tasks",
        {"openid": openid, "planId": plan_id, "dateStr": today_str},
        limit=100,
    )
    today_completed = len([t for t in today_tasks if t.get("completed")])
    today_total = len(today_tasks)
    completion_rate = int(round((today_completed / today_total) * 100)) if today_total else 0

    # 获取当前阶段
    current_phase = _get_current_phase(plan)

    # 生成任务
    domain = plan.get("domainName") or plan.get("domain", "")
    daily_hours = float(plan.get("dailyHours") or 2)

    tasks = await PlanService.generate_daily_tasks(
        domain=domain,
        daily_hours=daily_hours,
        current_phase=current_phase,
        learning_history={"avgCompletionRate": completion_rate},
        today_stats={"completionRate": completion_rate},
    )

    # 保存任务
    saved_tasks: List[Dict[str, Any]] = []
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
            "date": {"$date": tomorrow_start.isoformat()},
            "dateStr": tomorrow_str,
            "createdAt": {"$date": now},
            "generatedBy": "fastapi_ai",
        }
        new_id = await db.add("plan_tasks", doc)
        doc["_id"] = new_id
        saved_tasks.append(doc)

    # 分析信息
    analysis = {
        "avgCompletionRate": completion_rate,
        "adjustment": (
            "根据您的完成率，已适当调整任务难度"
            if completion_rate < 70
            else "继续保持当前学习节奏"
        ),
    }

    return {
        "success": True,
        "data": {
            "tasks": saved_tasks,
            "analysis": analysis,
            "isNew": True,
            "message": "明日任务已生成",
        },
    }


@router.post("/tomorrow-tasks/stream")
async def generate_tomorrow_tasks_stream(request: Request):
    """
    生成明日任务（流式响应）
    
    返回 Server-Sent Events 格式：
    - data: {"type": "progress", "message": "..."} - 进度更新
    - data: {"type": "content", "content": "..."} - AI 原始输出片段
    - data: {"type": "result", "success": true, "tasks": [...]} - 最终结果
    - data: {"type": "error", "error": "..."} - 错误信息
    - data: [DONE] - 结束标记
    """
    import logging
    logger = logging.getLogger(__name__)
    
    openid = _get_openid_from_request(request)
    db = get_db()
    plan_repo = PlanRepository(db)

    plan = await plan_repo.get_active_plan(openid)
    if not plan:
        raise HTTPException(status_code=404, detail="没有活跃的学习计划")

    # 确保 plan_id 是字符串格式
    raw_id = plan.get("_id") or plan.get("id")
    plan_id = str(raw_id) if raw_id else None
    tomorrow_str = _beijing_date_str(1)
    tomorrow_start, tomorrow_end = _beijing_day_range(1)

    # 检查是否已有明日任务
    existing = await db.query(
        "plan_tasks",
        {"openid": openid, "planId": plan_id, "dateStr": tomorrow_str},
        limit=100,
    )
    if existing:
        # 已有任务，直接返回非流式结果
        return {
            "success": True,
            "data": {
                "tasks": existing,
                "isNew": False,
                "message": "明日任务已存在",
            },
        }

    # 获取学习上下文
    today_str = _beijing_date_str(0)
    today_tasks = await db.query(
        "plan_tasks",
        {"openid": openid, "planId": plan_id, "dateStr": today_str},
        limit=100,
    )
    today_completed = len([t for t in today_tasks if t.get("completed")])
    today_total = len(today_tasks)
    completion_rate = int(round((today_completed / today_total) * 100)) if today_total else 0

    # 获取当前阶段
    current_phase = _get_current_phase(plan)

    # 生成任务参数
    domain = plan.get("domainName") or plan.get("domain", "")
    daily_hours = float(plan.get("dailyHours") or 2)

    async def generate():
        full_content = ""
        
        try:
            yield f"data: {json.dumps({'type': 'progress', 'message': '正在分析学习进度...'})}\n\n"
            
            yield f"data: {json.dumps({'type': 'progress', 'message': '正在生成明日任务...'})}\n\n"
            
            # 流式调用 AI
            async for chunk in PlanService.generate_daily_tasks_stream(
                domain=domain,
                daily_hours=daily_hours,
                current_phase=current_phase,
                learning_history={"avgCompletionRate": completion_rate},
                today_stats={"completionRate": completion_rate},
            ):
                full_content += chunk
                yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"
            
            yield f"data: {json.dumps({'type': 'progress', 'message': '正在解析任务列表...'})}\n\n"
            
            # 解析 JSON 数组
            json_match = re.search(r'\[[\s\S]*\]', full_content)
            if json_match:
                try:
                    tasks = json.loads(json_match.group())
                    tasks = PlanService._validate_tasks(tasks, daily_hours)
                    
                    yield f"data: {json.dumps({'type': 'progress', 'message': '正在保存任务...'})}\n\n"
                    
                    # 保存任务
                    saved_tasks: List[Dict[str, Any]] = []
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
                            "date": {"$date": tomorrow_start.isoformat()},
                            "dateStr": tomorrow_str,
                            "createdAt": {"$date": now},
                            "generatedBy": "fastapi_ai_stream",
                        }
                        new_id = await db.add("plan_tasks", doc)
                        doc["_id"] = new_id
                        saved_tasks.append(doc)
                    
                    # 分析信息
                    analysis = {
                        "avgCompletionRate": completion_rate,
                        "adjustment": (
                            "根据您的完成率，已适当调整任务难度"
                            if completion_rate < 70
                            else "继续保持当前学习节奏"
                        ),
                    }
                    
                    yield f"data: {json.dumps({'type': 'result', 'success': True, 'tasks': saved_tasks, 'analysis': analysis, 'isNew': True})}\n\n"
                except json.JSONDecodeError as je:
                    logger.error(f"[tomorrow-tasks/stream] JSON 解析失败: {je}")
                    yield f"data: {json.dumps({'type': 'error', 'error': f'JSON解析失败: {str(je)}'})}\n\n"
            else:
                logger.error("[tomorrow-tasks/stream] AI 响应中未找到 JSON")
                yield f"data: {json.dumps({'type': 'error', 'error': '生成格式错误，未找到有效JSON'})}\n\n"
                
        except Exception as e:
            logger.error(f"[tomorrow-tasks/stream] 异常: {type(e).__name__}: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
        
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== 其他 API ====================


@router.post("/generate-tasks", response_model=GenerateTasksResponse)
async def generate_daily_tasks(request: GenerateTasksRequest):
    """
    生成每日学习任务（不保存，仅返回）
    """
    try:
        tasks = await PlanService.generate_daily_tasks(
            domain=request.domain,
            daily_hours=request.daily_hours,
            current_phase=request.current_phase,
            learning_history=request.learning_history,
            today_stats=request.today_stats,
        )
        return GenerateTasksResponse(success=True, tasks=tasks)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-mistake", response_model=AnalyzeMistakeResponse)
async def analyze_mistake(request: AnalyzeMistakeRequest):
    """
    错题分析
    """
    try:
        analysis = await AIService.analyze_mistake(
            question=request.question,
            user_answer=request.user_answer,
            correct_answer=request.correct_answer,
            subject=request.subject,
            image_url=request.image_url,
        )
        return AnalyzeMistakeResponse(success=True, analysis=analysis)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
