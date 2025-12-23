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


# ==================== 学友系统相关模型 ====================

class Friendship(BaseModel):
    """学友关系 - 对应 friendships 集合"""
    _id: Optional[str] = None
    openid: str  # 发起者 openid
    friendOpenid: str  # 学友 openid
    status: str = "pending"  # pending（待确认）, accepted（已接受）, rejected（已拒绝）, blocked（已屏蔽）
    # 双方用户信息快照
    userInfo: Optional[Dict[str, Any]] = None  # 发起者信息
    friendInfo: Optional[Dict[str, Any]] = None  # 学友信息
    remark: str = ""  # 备注名
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    acceptedAt: Optional[datetime] = None


class StudyBuddy(BaseModel):
    """学伴关系 - 对应 study_buddies 集合
    表示两个用户共同学习同一个计划
    """
    _id: Optional[str] = None
    planId: str  # 学习计划 ID
    planOwnerOpenid: str  # 计划发起者 openid
    buddyOpenid: str  # 学伴 openid
    status: str = "pending"  # pending, accepted, rejected, left
    # 用户信息快照
    planOwnerInfo: Optional[Dict[str, Any]] = None
    buddyInfo: Optional[Dict[str, Any]] = None
    inviteMessage: str = ""  # 邀请消息
    createdAt: Optional[datetime] = None
    acceptedAt: Optional[datetime] = None


class StudySupervisor(BaseModel):
    """监督者关系 - 对应 study_supervisors 集合
    监督者可以查看被监督者的学习进度并发送提醒
    """
    _id: Optional[str] = None
    supervisorOpenid: str  # 监督者 openid
    supervisedOpenid: str  # 被监督者 openid
    planId: Optional[str] = None  # 监督的计划 ID（可选，为空表示监督所有计划）
    status: str = "pending"  # pending, accepted, rejected, ended
    # 用户信息快照
    supervisorInfo: Optional[Dict[str, Any]] = None
    supervisedInfo: Optional[Dict[str, Any]] = None
    # 监督设置
    settings: Dict[str, Any] = {}  # 监督设置（如提醒频率、提醒时间等）
    inviteMessage: str = ""  # 邀请消息
    createdAt: Optional[datetime] = None
    acceptedAt: Optional[datetime] = None


class PrivateChat(BaseModel):
    """私聊会话 - 对应 private_chats 集合"""
    _id: Optional[str] = None
    # 参与者（按 openid 排序存储，便于查询）
    participants: List[str]  # [openid1, openid2]
    # 最新消息预览
    lastMessage: Optional[Dict[str, Any]] = None
    lastMessageAt: Optional[datetime] = None
    # 各方未读数
    unreadCount: Dict[str, int] = {}  # {openid: count}
    # 各方用户信息快照
    participantInfos: Dict[str, Dict[str, Any]] = {}  # {openid: userInfo}
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class PrivateMessage(BaseModel):
    """私聊消息 - 对应 private_messages 集合"""
    _id: Optional[str] = None
    chatId: str  # 会话 ID (private_chats._id)
    senderOpenid: str  # 发送者 openid
    receiverOpenid: str  # 接收者 openid
    content: str  # 消息内容
    messageType: str = "text"  # text, image, system（系统消息）
    # 关联内容（用于分享学习进度等）
    reference: Optional[Dict[str, Any]] = None  # {type: 'progress'|'plan'|'task', data: {...}}
    isRead: bool = False
    readAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None


class SupervisorReminder(BaseModel):
    """监督者提醒记录 - 对应 supervisor_reminders 集合"""
    _id: Optional[str] = None
    supervisorOpenid: str  # 监督者 openid
    supervisedOpenid: str  # 被监督者 openid
    relationId: str  # 监督关系 ID (study_supervisors._id)
    reminderType: str  # daily_checkin（每日打卡）, task_progress（任务进度）, encouragement（鼓励）
    content: str  # 提醒内容
    isRead: bool = False
    createdAt: Optional[datetime] = None