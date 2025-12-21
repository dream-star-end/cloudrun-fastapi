"""
学习计划 API 路由
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request
from ..models import (
    GeneratePlanRequest, GeneratePlanResponse,
    GenerateTasksRequest, GenerateTasksResponse,
    AnalyzeMistakeRequest, AnalyzeMistakeResponse,
)
from ..services.plan_service import PlanService
from ..services.ai_service import AIService
from ..db.wxcloud import get_db, PlanRepository

router = APIRouter(prefix="/api/plan", tags=["学习计划"])


def _get_openid_from_request(request: Request) -> str:
    openid = request.headers.get("x-wx-openid") or request.headers.get("X-WX-OPENID")
    if not openid:
        raise HTTPException(status_code=401, detail="缺少用户身份（X-WX-OPENID），请使用 wx.cloud.callContainer 内网调用")
    return openid


def _beijing_day_range(days_offset: int = 0):
    now_utc = datetime.now(timezone.utc)
    beijing_now = now_utc + timedelta(hours=8)
    beijing_day = (beijing_now.date() + timedelta(days=days_offset))
    day_start_utc = datetime(beijing_day.year, beijing_day.month, beijing_day.day, tzinfo=timezone.utc) - timedelta(hours=8)
    day_end_utc = day_start_utc + timedelta(days=1)
    return day_start_utc, day_end_utc


@router.post("/generate", response_model=GeneratePlanResponse)
async def generate_plan(request: GeneratePlanRequest):
    """
    生成学习计划
    
    - **goal**: 学习目标
    - **domain**: 学习领域（如：考研、英语学习、编程技术）
    - **daily_hours**: 每日学习时长（小时）
    - **deadline**: 目标截止日期（可选，格式：YYYY-MM-DD）
    - **current_level**: 当前水平 (beginner/intermediate/advanced)
    - **preferences**: 学习偏好（可选）
    """
    try:
        result = await PlanService.generate_study_plan(
            goal=request.goal,
            domain=request.domain,
            daily_hours=request.daily_hours,
            deadline=request.deadline,
            current_level=request.current_level,
            preferences=request.preferences,
        )
        
        if result.get("success"):
            return GeneratePlanResponse(success=True, plan=result.get("plan"))
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "生成失败"))
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active")
async def get_active_plan(request: Request):
    """
    获取当前活跃计划 + 今日任务（用于替代云函数 getPlan，减少中间链条）
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    plan_repo = PlanRepository(db)

    plan = await plan_repo.get_active_plan(openid)
    if not plan:
        return {"success": True, "hasActivePlan": False, "plan": None, "todayTasks": []}

    plan_id = plan.get("_id") or plan.get("id")
    if not plan_id:
        raise HTTPException(status_code=500, detail="学习计划缺少 _id")

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

    return {"success": True, "hasActivePlan": True, "plan": plan, "todayTasks": tasks, "dateStr": today_str}


@router.post("/generate-tasks", response_model=GenerateTasksResponse)
async def generate_daily_tasks(request: GenerateTasksRequest):
    """
    生成每日学习任务
    
    - **plan_id**: 学习计划 ID
    - **domain**: 学习领域
    - **daily_hours**: 每日学习时长
    - **current_phase**: 当前学习阶段（可选）
    - **learning_history**: 学习历史统计（可选）
    - **today_stats**: 今日任务统计（可选）
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


@router.post("/phase-detail")
async def generate_phase_detail(
    phase_name: str,
    phase_goals: list,
    domain: str,
    duration: str,
):
    """
    生成学习阶段详情
    
    - **phase_name**: 阶段名称
    - **phase_goals**: 阶段目标列表
    - **domain**: 学习领域
    - **duration**: 阶段时长
    """
    try:
        result = await PlanService.generate_phase_detail(
            phase_name=phase_name,
            phase_goals=phase_goals,
            domain=domain,
            duration=duration,
        )
        
        if result.get("success"):
            return {"success": True, "detail": result.get("detail")}
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "生成失败"))
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-mistake", response_model=AnalyzeMistakeResponse)
async def analyze_mistake(request: AnalyzeMistakeRequest):
    """
    错题分析
    
    - **question**: 题目内容
    - **user_answer**: 用户的答案
    - **correct_answer**: 正确答案（可选）
    - **subject**: 学科（可选）
    - **image_url**: 题目图片 URL（可选）
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

