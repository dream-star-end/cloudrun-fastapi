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


# 领域名称映射（与前端 app.js 中的 studyDomains 保持一致）
DOMAIN_NAMES = {
    # 前端新版 domain ID
    "exam_postgraduate": "考研",
    "exam_civil": "考公",
    "exam_english": "英语",
    "exam_cert": "考证",
    "programming": "编程",
    "other": "其他",
    # 兼容旧版 domain ID
    "postgraduate": "考研",
    "english": "英语学习",
    "certification": "职业认证",
    "academic": "学业提升",
}


def _fix_domain_name(plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    修复计划的 domainName 字段，确保显示中文名称而非 domain ID
    """
    if not plan:
        return plan
    
    domain_name = plan.get("domainName", "")
    domain = plan.get("domain", "")
    
    # 如果 domainName 看起来是 domain ID（包含下划线或在映射表中），则转换为中文名称
    if domain_name in DOMAIN_NAMES:
        plan["domainName"] = DOMAIN_NAMES[domain_name]
    elif not domain_name and domain:
        # domainName 为空时，根据 domain 字段获取中文名称
        plan["domainName"] = DOMAIN_NAMES.get(domain, domain)
    
    return plan


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


def _parse_duration_to_days(duration: str) -> int:
    """解析时长字符串，返回天数"""
    if not duration:
        return 7
    # 提取纯时长部分（去掉括号里的日期范围）
    pure_duration = duration.split('(')[0].split('（')[0].strip()
    
    match = re.search(r'(\d+(?:\.\d+)?)\s*(周|天|月|个月)', pure_duration)
    if not match:
        return 7
    
    value = float(match.group(1))
    unit = match.group(2)
    
    if unit == '天':
        return int(value)
    elif unit == '周':
        return int(value * 7)
    elif unit in ('月', '个月'):
        return int(value * 30)
    return 7


def _days_to_readable(days: int) -> str:
    """将天数转换为可读的时长文本"""
    if days < 7:
        return f"{days}天"
    elif days < 30:
        weeks = round(days / 7)
        return f"{weeks}周"
    else:
        months = days / 30
        if months < 1:
            return f"{round(days / 7)}周"
        rounded_months = round(months * 2) / 2
        if rounded_months == int(rounded_months):
            return f"{int(rounded_months)}个月"
        return f"{rounded_months}个月"


def _calculate_phases_with_dates(phases: List[Dict], created_at: datetime, deadline_str: str = None) -> tuple:
    """
    计算每个阶段的具体日期范围，返回更新后的 phases 和 totalDuration
    
    Args:
        phases: 阶段列表
        created_at: 计划创建时间
        deadline_str: 截止日期字符串
    
    Returns:
        (updated_phases, total_duration_str)
    """
    if not phases:
        return phases, "待定"
    
    # 计算每个阶段的原始天数
    phase_days = []
    for phase in phases:
        days = _parse_duration_to_days(phase.get("duration", ""))
        phase_days.append(days)
    
    total_original_days = sum(phase_days)
    
    # 解析截止日期
    deadline_date = None
    if deadline_str:
        try:
            deadline_date = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
        except:
            pass
    
    # 计算实际总天数
    if deadline_date and deadline_date > created_at:
        actual_total_days = (deadline_date - created_at).days
    else:
        actual_total_days = total_original_days
        deadline_date = created_at + timedelta(days=total_original_days)
    
    # 按比例分配每个阶段的实际天数
    if total_original_days > 0:
        actual_phase_days = [
            max(1, round((d / total_original_days) * actual_total_days))
            for d in phase_days
        ]
    else:
        actual_phase_days = phase_days
    
    # 计算每个阶段的起止日期并更新 duration
    current_date = created_at
    updated_phases = []
    
    for i, phase in enumerate(phases):
        phase_start = current_date
        phase_end = phase_start + timedelta(days=actual_phase_days[i])
        
        # 格式化日期范围
        start_str = f"{phase_start.year}年{phase_start.month}月"
        end_str = f"{phase_end.year}年{phase_end.month}月"
        duration_text = _days_to_readable(actual_phase_days[i])
        
        # 更新阶段信息
        updated_phase = {**phase}
        updated_phase["duration"] = f"{duration_text} ({start_str}-{end_str})"
        updated_phase["startDate"] = phase_start.isoformat()
        updated_phase["endDate"] = phase_end.isoformat()
        updated_phases.append(updated_phase)
        
        current_date = phase_end
    
    # 计算总时长字符串
    plan_start = created_at
    plan_end = deadline_date if deadline_date else current_date
    total_duration_text = _days_to_readable(actual_total_days)
    total_duration = f"约{total_duration_text}（从{plan_start.year}年{plan_start.month}月至{plan_end.year}年{plan_end.month}月）"
    
    return updated_phases, total_duration


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
    
    # 修复 domainName 显示（将 domain ID 转换为中文名称）
    plan = _fix_domain_name(plan)

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
    personalization = body.get("personalization") or body.get("preferences") or plan_data.get("personalization") or plan_data.get("preferences") or None

    # 获取领域中文名称
    domain_name = DOMAIN_NAMES.get(domain, domain)

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

    now = datetime.now(timezone.utc)
    now_str = now.isoformat()
    
    # 根据创建时间和截止日期计算每个阶段的具体时间范围
    phases_with_dates, total_duration = _calculate_phases_with_dates(phases, now, deadline)

    new_plan = {
        "openid": openid,
        "goal": goal,
        "domain": domain,
        "domainName": domain_name,
        "deadline": deadline,
        "dailyHours": daily_hours,
        "currentLevel": current_level,
        # 用于"更强个性化画像/计划强度节奏"
        "personalization": personalization if isinstance(personalization, dict) else {},
        "status": "active",
        "progress": 0,
        "todayProgress": 0,
        "completedDays": 0,
        "phases": phases_with_dates,  # 使用计算后的阶段（包含具体日期）
        "totalDuration": total_duration,  # 使用计算后的总时长
        "dailySchedule": plan_data.get("daily_schedule") or plan_data.get("dailySchedule", []),
        "tips": plan_data.get("tips", []),
        "createdAt": {"$date": now_str},
        "updatedAt": {"$date": now_str},
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
        """使用 JSON 模式生成阶段详情（更可靠）"""
        try:
            yield f"data: {json.dumps({'type': 'progress', 'message': '正在分析阶段目标...'})}\n\n"
            
            yield f"data: {json.dumps({'type': 'progress', 'message': '正在生成阶段详情（约需30-60秒）...'})}\n\n"
            
            # 使用 JSON 模式调用 AI（非流式，但更可靠）
            result = await PlanService.generate_phase_detail(
                phase_name=phase.get("name", ""),
                phase_goals=phase.get("goals", []),
                domain=plan.get("domainName") or plan.get("domain", ""),
                duration=phase.get("duration", "1周"),
            )
            
            if result.get("success") and result.get("detail"):
                detail = result["detail"]
                
                yield f"data: {json.dumps({'type': 'progress', 'message': '正在保存阶段详情...'})}\n\n"
                
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
                try:
                    phases[phase_index] = updated_phase
                    await db.update_by_id("study_plans", plan_id, {"phases": phases})
                    logger.info(f"[phase-detail/stream] 阶段 {phase_id} 详情已保存")
                except Exception as db_err:
                    logger.error(f"[phase-detail/stream] 数据库更新失败: {db_err}")
                
                yield f"data: {json.dumps({'type': 'result', 'success': True, 'phaseDetail': updated_phase})}\n\n"
            else:
                # AI 调用失败，返回基本阶段信息
                error_msg = result.get("error", "生成失败")
                logger.error(f"[phase-detail/stream] AI 生成失败: {error_msg}")
                
                fallback_phase = {
                    **phase,
                    "status": "completed",
                    "keyPoints": [],
                    "resources": [],
                    "milestone": "",
                }
                yield f"data: {json.dumps({'type': 'result', 'success': True, 'phaseDetail': fallback_phase, 'warning': error_msg})}\n\n"
                
        except Exception as e:
            logger.error(f"[phase-detail/stream] 异常: {type(e).__name__}: {str(e)}", exc_info=True)
            # 即使出错也返回基本结果，不阻塞流程
            fallback_phase = {
                **phase,
                "status": "completed",
                "keyPoints": [],
                "resources": [],
                "milestone": "",
            }
            yield f"data: {json.dumps({'type': 'result', 'success': True, 'phaseDetail': fallback_phase, 'warning': str(e)})}\n\n"
        
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

    # 计算阶段进度（已完成阶段数 / 总阶段数）
    current_phase = _get_current_phase(plan)
    phases = plan.get("phases") or []
    phase_progress = 0
    if current_phase and phases:
        # phase_index 表示当前在第几阶段（从1开始），已完成的是 phase_index - 1
        phase_index = current_phase.get("index", 1)
        completed_phases = phase_index - 1
        phase_progress = int(round((completed_phases / len(phases)) * 100))

    # 计算学习活跃度（有完成任务的天数 / 7）
    # 只统计有任务被完成的天数，而不是有任务创建的天数
    completed_tasks = [t for t in all_tasks if t.get("completed")]
    active_days = len(set(t.get("dateStr") or "" for t in completed_tasks if t.get("dateStr")))
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


@router.get("/dashboard")
async def get_dashboard(request: Request):
    """
    学习“变强仪表盘”数据：
    - 知识点掌握度（基于错题 tags/掌握状态）
    - 稳定性（最近3条错题是否已掌握的比例，近似口径）
    - 投入时间（focus_records）
    - 完成率（plan_tasks）
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    plan_repo = PlanRepository(db)

    plan = await plan_repo.get_active_plan(openid)
    if not plan:
        return {"success": True, "data": {"hasActivePlan": False}}

    raw_id = plan.get("_id") or plan.get("id")
    plan_id = str(raw_id) if raw_id else None
    if not plan_id:
        raise HTTPException(status_code=500, detail="学习计划缺少 _id")

    today_start, _ = _beijing_day_range(0)
    week_start = today_start - timedelta(days=7)
    tomorrow_start, _ = _beijing_day_range(1)

    def _datestr_from_date_field(date_val: Any) -> Optional[str]:
        try:
            dt = None
            if isinstance(date_val, dict) and "$date" in date_val:
                dt = datetime.fromisoformat(str(date_val["$date"]).replace("Z", "+00:00"))
            elif isinstance(date_val, str):
                dt = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
            elif isinstance(date_val, datetime):
                dt = date_val
            if not dt:
                return None
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            bj = dt.astimezone(timezone.utc) + timedelta(hours=8)
            return bj.date().isoformat()
        except Exception:
            return None

    # ====== 任务完成率（近7天）======
    tasks = await db.query(
        "plan_tasks",
        {
            "openid": openid,
            "planId": plan_id,
            "date": {"$gte": {"$date": week_start.isoformat()}, "$lt": {"$date": tomorrow_start.isoformat()}},
        },
        limit=2000,
        order_by="date",
        order_type="asc",
    )
    daily_task = {}
    for t in tasks:
        d = t.get("dateStr") or _datestr_from_date_field(t.get("date"))
        if not d:
            continue
        if d not in daily_task:
            daily_task[d] = {"dateStr": d, "total": 0, "completed": 0, "minutesPlanned": 0}
        daily_task[d]["total"] += 1
        daily_task[d]["minutesPlanned"] += int(t.get("duration") or 0)
        if t.get("completed"):
            daily_task[d]["completed"] += 1
    daily_task_list = sorted(daily_task.values(), key=lambda x: x["dateStr"])
    for x in daily_task_list:
        x["completionRate"] = int(round((x["completed"] / x["total"]) * 100)) if x["total"] else 0

    today_key = _beijing_date_str(0)
    today_row = daily_task.get(today_key, {"dateStr": today_key, "total": 0, "completed": 0, "minutesPlanned": 0, "completionRate": 0})
    total_7 = sum(x["total"] for x in daily_task_list)
    completed_7 = sum(x["completed"] for x in daily_task_list)
    completion_7 = int(round((completed_7 / total_7) * 100)) if total_7 else 0

    # ====== 投入时间（focus_records 近7天）======
    focus_records = await db.query(
        "focus_records",
        {"openid": openid, "date": {"$gte": {"$date": week_start.isoformat()}, "$lt": {"$date": tomorrow_start.isoformat()}}},
        limit=2000,
        order_by="date",
        order_type="asc",
    )
    daily_focus = {}
    for r in focus_records:
        d = _datestr_from_date_field(r.get("date"))
        if not d:
            continue
        if d not in daily_focus:
            daily_focus[d] = {"dateStr": d, "minutes": 0, "count": 0}
        daily_focus[d]["minutes"] += int(r.get("duration") or 0)
        daily_focus[d]["count"] += 1
    daily_focus_list = sorted(daily_focus.values(), key=lambda x: x["dateStr"])
    today_focus = daily_focus.get(today_key, {"minutes": 0, "count": 0})
    week_focus_minutes = sum(x["minutes"] for x in daily_focus_list)

    # ====== 知识点掌握度（错题 tags 近似）======
    mistakes = await db.query(
        "mistakes",
        {"openid": openid},
        limit=1000,
        order_by="createdAt",
        order_type="desc",
    )
    by_tag: Dict[str, List[Dict[str, Any]]] = {}
    for m in mistakes:
        tags = m.get("tags") or []
        if not isinstance(tags, list) or not tags:
            # fallback：用 category 作为弱标签
            cat = str(m.get("category") or "").strip()
            tags = [cat] if cat else []
        for t in tags:
            tag = str(t).strip()
            if not tag:
                continue
            by_tag.setdefault(tag, []).append(m)

    tag_rows = []
    for tag, ms in by_tag.items():
        total = len(ms)
        mastered = len([x for x in ms if x.get("mastered")])
        last3 = ms[:3]
        stability = (len([x for x in last3 if x.get("mastered")]) / 3.0) if len(last3) >= 3 else (mastered / total if total else 0.0)
        tag_rows.append(
            {
                "tag": tag,
                "total": total,
                "mastered": mastered,
                "mastery": round(mastered / total, 3) if total else 0.0,
                "stability": round(stability, 3),
            }
        )
    # 选：先看未掌握多的，再看总量
    tag_rows.sort(key=lambda x: (-(x["total"] - x["mastered"]), -x["total"]))
    top_tags = tag_rows[:8]
    overall_total = sum(x["total"] for x in tag_rows)
    overall_mastered = sum(x["mastered"] for x in tag_rows)
    overall_mastery = round(overall_mastered / overall_total, 3) if overall_total else 0.0

    return {
        "success": True,
        "data": {
            "hasActivePlan": True,
            "planId": plan_id,
            "dateStr": today_key,
            "tasks": {
                "today": today_row,
                "last7CompletionRate": completion_7,
                "daily": daily_task_list,
            },
            "focus": {
                "todayMinutes": int(today_focus.get("minutes") or 0),
                "todayCount": int(today_focus.get("count") or 0),
                "last7Minutes": int(week_focus_minutes),
                "daily": daily_focus_list,
            },
            "knowledge": {
                "overallMastery": overall_mastery,
                "top": top_tags,
            },
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

    # ========= 动态重排：把今日未完成任务自动搬到明天 =========
    total_minutes = max(20, int(float(plan.get("dailyHours") or 2) * 60))
    carry_max_minutes = int(total_minutes * 0.6)
    carry_max_count = 3

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

    # 组装 learning_context（错题 + 续做 + 个性化偏好 + 节奏）
    mistakes = await db.query(
        "mistakes",
        {"openid": openid, "mastered": False},
        limit=5,
        order_by="createdAt",
        order_type="desc",
    )
    simplified_mistakes = []
    for m in mistakes:
        simplified_mistakes.append(
            {
                "id": m.get("_id") or m.get("id"),
                "topic": (m.get("category") or "") if m.get("category") else None,
                "question": m.get("question") or "",
                "tags": m.get("tags") or [],
            }
        )
    personalization = plan.get("personalization") if isinstance(plan, dict) else {}
    learning_context = {
        "carryover": {"uncompletedTitles": [t.get("title") for t in pending_today[:5] if t.get("title")]},
        "mistakes": simplified_mistakes,
        "preferences": personalization if isinstance(personalization, dict) else {},
        "pace": {
            "carryoverMinutes": carry_minutes,
            "missedDays": 1 if (completion_rate == 0 and today_total > 0) else 0,
            "highCompletionStreak": 1 if (completion_rate >= 95 and today_total > 0) else 0,
        },
    }

    # 获取当前阶段
    current_phase = _get_current_phase(plan)

    # 生成任务（先写入搬运任务，再用剩余时间生成新任务）
    domain = plan.get("domainName") or plan.get("domain", "")

    saved_tasks: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    order_cursor = 0

    if carry_tasks:
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
                "generatedBy": "carryover",
                "carriedFromDateStr": today_str,
                "originTaskId": str(t.get("_id") or t.get("id") or ""),
            }
            new_id = await db.add("plan_tasks", doc)
            doc["_id"] = new_id
            saved_tasks.append(doc)
            order_cursor += 1

            origin_id = t.get("_id") or t.get("id")
            if origin_id:
                await db.update_by_id("plan_tasks", str(origin_id), {"carriedToDateStr": tomorrow_str, "carriedAt": {"$date": now}})

    remaining_minutes = max(0, total_minutes - carry_minutes)
    adjusted_daily_hours = max(0.3, remaining_minutes / 60.0) if remaining_minutes else 0.3

    tasks = await PlanService.generate_daily_tasks(
        domain=domain,
        daily_hours=adjusted_daily_hours,
        current_phase=current_phase,
        learning_history={"avgCompletionRate": completion_rate},
        today_stats={"completionRate": completion_rate},
        learning_context=learning_context,
    )

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

    # ========= 动态重排：把今日未完成任务自动搬到明天（流式版也一致） =========
    total_minutes = max(20, int(float(plan.get("dailyHours") or 2) * 60))
    carry_max_minutes = int(total_minutes * 0.6)
    carry_max_count = 3

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

    # learning_context（错题 + 续做 + 个性化偏好 + 节奏）
    mistakes = await db.query(
        "mistakes",
        {"openid": openid, "mastered": False},
        limit=5,
        order_by="createdAt",
        order_type="desc",
    )
    simplified_mistakes = []
    for m in mistakes:
        simplified_mistakes.append(
            {
                "id": m.get("_id") or m.get("id"),
                "topic": (m.get("category") or "") if m.get("category") else None,
                "question": m.get("question") or "",
                "tags": m.get("tags") or [],
            }
        )
    personalization = plan.get("personalization") if isinstance(plan, dict) else {}
    learning_context = {
        "carryover": {"uncompletedTitles": [t.get("title") for t in pending_today[:5] if t.get("title")]},
        "mistakes": simplified_mistakes,
        "preferences": personalization if isinstance(personalization, dict) else {},
        "pace": {
            "carryoverMinutes": carry_minutes,
            "missedDays": 1 if (completion_rate == 0 and today_total > 0) else 0,
            "highCompletionStreak": 1 if (completion_rate >= 95 and today_total > 0) else 0,
        },
    }

    # 获取当前阶段（流式版需要在搬运任务写入前可用）
    current_phase = _get_current_phase(plan)

    carry_saved_tasks: List[Dict[str, Any]] = []
    order_offset = 0
    now = datetime.now(timezone.utc).isoformat()
    if carry_tasks:
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
                "order": order_offset,
                "date": {"$date": tomorrow_start.isoformat()},
                "dateStr": tomorrow_str,
                "createdAt": {"$date": now},
                "generatedBy": "carryover",
                "carriedFromDateStr": today_str,
                "originTaskId": str(t.get("_id") or t.get("id") or ""),
            }
            new_id = await db.add("plan_tasks", doc)
            doc["_id"] = new_id
            carry_saved_tasks.append(doc)
            order_offset += 1

            origin_id = t.get("_id") or t.get("id")
            if origin_id:
                await db.update_by_id("plan_tasks", str(origin_id), {"carriedToDateStr": tomorrow_str, "carriedAt": {"$date": now}})

    remaining_minutes = max(0, total_minutes - carry_minutes)
    adjusted_daily_hours = max(0.3, remaining_minutes / 60.0) if remaining_minutes else 0.3

    # 生成任务参数
    domain = plan.get("domainName") or plan.get("domain", "")
    daily_hours = adjusted_daily_hours

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
                learning_context=learning_context,
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
                    saved_tasks: List[Dict[str, Any]] = list(carry_saved_tasks)
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
                            "order": order_offset + i,
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


@router.post("/analyze-mistake/stream")
async def analyze_mistake_stream(request: AnalyzeMistakeRequest):
    """
    错题分析（流式响应 SSE）

    返回格式：
    - data: {"content": "..."}  (多次)
    - data: [DONE]
    """
    try:
        async def generate():
            try:
                async for chunk in AIService.analyze_mistake_text_stream(
                    question=request.question,
                    user_answer=request.user_answer,
                    correct_answer=request.correct_answer,
                    subject=request.subject,
                    image_url=request.image_url,
                ):
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