"""
数据库模型定义
与小程序云开发数据库结构对应
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    """用户画像"""
    name: str = ""
    grade: str = ""
    learningGoals: List[str] = []
    subjects: List[str] = []
    learningStyle: str = ""
    weakPoints: List[str] = []
    strongPoints: List[str] = []
    schedulePreference: str = ""


class UserPreferences(BaseModel):
    """用户偏好设置"""
    communicationStyle: str = "friendly"
    explanationDepth: str = "detailed"
    encouragementLevel: str = "high"


class User(BaseModel):
    """用户基本信息 - 对应 users 集合"""
    _id: Optional[str] = None
    openid: str
    nickName: str = ""
    avatarUrl: str = ""
    isVip: bool = False
    vipExpireDate: Optional[str] = None
    hasOnboarded: bool = False
    currentPlan: Optional[str] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class UserStats(BaseModel):
    """用户统计数据 - 对应 user_stats 集合"""
    _id: Optional[str] = None
    openid: str
    studyDays: int = 0
    totalMinutes: int = 0
    currentStreak: int = 0
    longestStreak: int = 0
    todayMinutes: int = 0
    todayChecked: bool = False
    thisWeekDays: int = 0
    thisMonthDays: int = 0
    lastCheckinDate: Optional[str] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class UserMemory(BaseModel):
    """用户记忆 - 对应 user_memory 集合"""
    _id: Optional[str] = None
    openid: str
    profile: UserProfile = Field(default_factory=UserProfile)
    facts: List[Dict[str, Any]] = []
    preferences: UserPreferences = Field(default_factory=UserPreferences)
    recentTopics: List[str] = []
    importantDates: List[Dict[str, Any]] = []
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class CheckinRecord(BaseModel):
    """打卡记录 - 对应 checkin_records 集合"""
    _id: Optional[str] = None
    openid: str
    date: str  # YYYY-MM-DD
    time: Optional[str] = None  # HH:MM
    streak: int = 1
    createdAt: Optional[datetime] = None


class FocusRecord(BaseModel):
    """专注记录 - 对应 focus_records 集合"""
    _id: Optional[str] = None
    openid: str
    date: datetime
    duration: int  # 分钟
    task: str = ""
    completed: bool = True
    createdAt: Optional[datetime] = None


class Phase(BaseModel):
    """学习计划阶段"""
    id: str
    name: str
    duration: str
    objectives: List[str] = []
    key_tasks: List[str] = []
    resources: List[str] = []
    status: str = "pending"  # pending, generating, completed


class StudyPlan(BaseModel):
    """学习计划 - 对应 study_plans 集合"""
    _id: Optional[str] = None
    openid: str
    goal: str
    domain: str
    dailyHours: float = 2.0
    currentLevel: str = "beginner"
    deadline: Optional[str] = None
    status: str = "active"  # active, completed, cancelled
    phases: List[Phase] = []
    totalDuration: str = ""
    progress: float = 0.0
    todayProgress: float = 0.0
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class PlanTask(BaseModel):
    """计划任务 - 对应 plan_tasks 集合"""
    _id: Optional[str] = None
    openid: str
    planId: str
    phaseId: Optional[str] = None
    title: str
    description: str = ""
    duration: int = 30  # 分钟
    # 云开发侧通常用 Date 类型字段（可能以 {"$date": "..."} 形式传输）
    date: Optional[datetime] = None
    # 与日历绑定的“自然日”（北京时间）字符串：YYYY-MM-DD
    dateStr: Optional[str] = None
    calendarDate: Optional[str] = None
    completed: bool = False
    completedAt: Optional[datetime] = None
    order: int = 0
    createdAt: Optional[datetime] = None


class Mistake(BaseModel):
    """错题 - 对应 mistakes 集合"""
    _id: Optional[str] = None
    openid: str
    question: str
    answer: str = ""
    correctAnswer: str = ""
    # 兼容字段：历史版本使用预置分类；新版本推荐使用 tags
    category: str = "other"  # legacy
    tags: List[str] = []
    source: str = ""
    analysis: str = ""
    aiAnalysis: str = ""
    imageUrl: str = ""
    mastered: bool = False
    masteredAt: Optional[datetime] = None
    reviewCount: int = 0
    lastReviewAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class ChatHistory(BaseModel):
    """聊天历史 - 对应 chat_history 集合"""
    _id: Optional[str] = None
    openid: str
    role: str  # user, assistant
    content: str
    timestamp: Optional[datetime] = None


class Document(BaseModel):
    """文档 - 对应 documents 集合"""
    _id: Optional[str] = None
    openid: str
    name: str
    type: str  # pdf, image, etc.
    cloudFileId: str = ""
    pages: int = 0
    status: str = "pending"  # pending, processing, ready, error
    summary: str = ""
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


# ==================== 学习社区相关模型 ====================

class SharedPlanAuthor(BaseModel):
    """分享计划的作者信息"""
    openid: str
    nickName: str = ""
    avatarUrl: str = ""


class SharedPlan(BaseModel):
    """分享的学习计划 - 对应 shared_plans 集合"""
    _id: Optional[str] = None
    openid: str  # 分享者的 openid
    originalPlanId: str  # 原计划 ID
    title: str  # 分享标题
    description: str = ""  # 分享说明
    # 计划快照（复制时使用）
    goal: str = ""
    domain: str = ""
    domainName: str = ""
    dailyHours: float = 2.0
    currentLevel: str = "beginner"
    totalDuration: str = ""
    phases: List[Dict[str, Any]] = []
    # 作者信息快照
    author: SharedPlanAuthor = None
    # 统计数据
    likeCount: int = 0
    commentCount: int = 0
    useCount: int = 0  # 被使用次数
    viewCount: int = 0  # 查看次数
    # 状态
    status: str = "active"  # active, hidden, deleted
    publishedAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class CommunityComment(BaseModel):
    """社区评论 - 对应 community_comments 集合"""
    _id: Optional[str] = None
    planId: str  # 分享计划 ID (shared_plans._id)
    openid: str  # 评论者 openid
    content: str
    # 作者信息快照
    author: SharedPlanAuthor = None
    # 回复相关（可选，支持楼中楼）
    replyTo: Optional[str] = None  # 回复的评论 ID
    replyToUser: Optional[str] = None  # 回复的用户 openid
    # 状态
    status: str = "active"  # active, hidden, deleted
    createdAt: Optional[datetime] = None


class CommunityLike(BaseModel):
    """社区点赞 - 对应 community_likes 集合"""
    _id: Optional[str] = None
    planId: str  # 分享计划 ID (shared_plans._id)
    openid: str  # 点赞者 openid
    createdAt: Optional[datetime] = None
