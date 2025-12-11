"""
数据库访问模块
支持微信云开发数据库直连
"""

from .wxcloud import WxCloudDB, get_db
from .models import (
    User,
    UserStats,
    UserMemory,
    CheckinRecord,
    FocusRecord,
    StudyPlan,
    PlanTask,
    Mistake,
)

__all__ = [
    "WxCloudDB",
    "get_db",
    "User",
    "UserStats",
    "UserMemory",
    "CheckinRecord",
    "FocusRecord",
    "StudyPlan",
    "PlanTask",
    "Mistake",
]

