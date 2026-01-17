"""
Lightweight Agent tools API for MCP bridge.
Provides check-in and learning stats endpoints using existing repositories.
"""

from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Request

from ..db.wxcloud import CheckinRepository, FocusRepository, TaskRepository, UserRepository

router = APIRouter(prefix="/api/agent-tools", tags=["Agent Tools"])


def _get_openid_from_request(request: Request) -> str:
    openid = request.headers.get("x-wx-openid") or request.headers.get("X-WX-OPENID")
    if not openid:
        raise HTTPException(
            status_code=401,
            detail="Missing user identity (X-WX-OPENID). Use wx.cloud.callContainer.",
        )
    return openid


@router.post("/checkin")
async def do_checkin(request: Request):
    """
    Perform daily check-in.
    """
    openid = _get_openid_from_request(request)
    repo = CheckinRepository()
    result = await repo.do_checkin(openid)
    return {"success": result.get("success", False), "data": result}


@router.get("/checkin/status")
async def get_checkin_status(request: Request):
    """
    Get check-in stats for user.
    """
    openid = _get_openid_from_request(request)
    repo = CheckinRepository()
    stats = await repo.get_checkin_stats(openid)
    return {"success": True, "data": stats}


@router.get("/stats")
async def get_learning_stats(request: Request, period: str = "today"):
    """
    Get learning stats summary for a period: today/week/month/all.
    """
    openid = _get_openid_from_request(request)
    period = (period or "today").lower()
    if period not in ("today", "week", "month", "all"):
        raise HTTPException(status_code=400, detail="Invalid period")

    user_repo = UserRepository()
    checkin_repo = CheckinRepository()
    focus_repo = FocusRepository()
    task_repo = TaskRepository()

    stats = await user_repo.get_stats(openid) or {}
    checkin_stats = await checkin_repo.get_checkin_stats(openid)
    focus_stats = await focus_repo.get_today_stats(openid)
    task_progress = await task_repo.get_task_progress(openid)

    data: Dict[str, Any] = {
        "period": period,
        "checkin": checkin_stats,
    }

    if period == "today":
        data.update(
            {
                "focus": {
                    "todayMinutes": focus_stats.get("todayMinutes", 0),
                    "todayCount": focus_stats.get("todayCount", 0),
                },
                "tasks": {
                    "completed": task_progress.get("completed", 0),
                    "total": task_progress.get("total", 0),
                    "progress": task_progress.get("progress", 0),
                },
            }
        )
    elif period == "week":
        data.update(
            {
                "thisWeekDays": checkin_stats.get("thisWeekDays", stats.get("thisWeekDays", 0)),
            }
        )
    elif period == "month":
        data.update(
            {
                "thisMonthDays": checkin_stats.get("thisMonthDays", 0),
            }
        )
    else:
        total_minutes = stats.get("totalMinutes", 0)
        data.update(
            {
                "studyDays": stats.get("studyDays", 0),
                "totalMinutes": total_minutes,
                "totalHours": total_minutes // 60,
                "longestStreak": checkin_stats.get("longestStreak", 0),
            }
        )

    return {"success": True, "data": data}
