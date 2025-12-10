"""
学习计划 API 路由
"""
from fastapi import APIRouter, HTTPException
from ..models import (
    GeneratePlanRequest, GeneratePlanResponse,
    GenerateTasksRequest, GenerateTasksResponse,
    AnalyzeMistakeRequest, AnalyzeMistakeResponse,
)
from ..services.plan_service import PlanService
from ..services.ai_service import AIService

router = APIRouter(prefix="/api/plan", tags=["学习计划"])


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

