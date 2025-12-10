"""
数据模型定义
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum


# ==================== 通用模型 ====================

class ResponseBase(BaseModel):
    """基础响应模型"""
    success: bool = True
    message: str = ""
    data: Optional[Any] = None


# ==================== AI 对话模型 ====================

class ChatMessage(BaseModel):
    """聊天消息"""
    role: str = Field(..., description="角色: user/assistant/system")
    content: str = Field(..., description="消息内容")


class ChatRequest(BaseModel):
    """AI 对话请求"""
    messages: List[ChatMessage] = Field(..., description="对话历史")
    stream: bool = Field(default=True, description="是否使用流式响应")
    model_type: str = Field(default="text", description="模型类型: text/vision/longtext")
    temperature: float = Field(default=0.7, ge=0, le=2, description="生成温度")
    max_tokens: int = Field(default=2000, ge=1, le=8000, description="最大生成长度")
    
    # 学习教练专用字段
    user_memory: Optional[Dict] = Field(default=None, description="用户记忆/画像")
    enable_tools: bool = Field(default=False, description="是否启用 AI 工具")


class ChatResponse(BaseModel):
    """AI 对话响应"""
    success: bool = True
    content: str = ""
    usage: Optional[Dict] = None


# ==================== 图片识别模型 ====================

class RecognizeType(str, Enum):
    """识别类型"""
    OCR = "ocr"
    EXPLAIN = "explain"
    SUMMARY = "summary"
    FORMULA = "formula"


class RecognizeRequest(BaseModel):
    """图片识别请求"""
    image_url: str = Field(..., description="图片 URL")
    recognize_type: RecognizeType = Field(default=RecognizeType.OCR, description="识别类型")
    custom_prompt: Optional[str] = Field(default=None, description="自定义提示词")


class RecognizeResponse(BaseModel):
    """图片识别响应"""
    success: bool = True
    result: str = ""
    recognize_type: str = ""


# ==================== 联网搜索模型 ====================

class SearchDepth(str, Enum):
    """搜索深度"""
    BASIC = "basic"
    ADVANCED = "advanced"


class SearchRequest(BaseModel):
    """联网搜索请求"""
    query: str = Field(..., description="搜索关键词")
    search_depth: SearchDepth = Field(default=SearchDepth.BASIC, description="搜索深度")
    max_results: int = Field(default=5, ge=1, le=20, description="最大结果数")
    include_domains: List[str] = Field(default=[], description="限定搜索域名")


class SearchResult(BaseModel):
    """单个搜索结果"""
    index: int
    title: str
    url: str
    content: str
    score: Optional[float] = None


class SearchResponse(BaseModel):
    """联网搜索响应"""
    success: bool = True
    query: str = ""
    answer: Optional[str] = None
    results: List[SearchResult] = []


# ==================== 学习计划生成模型 ====================

class GeneratePlanRequest(BaseModel):
    """学习计划生成请求"""
    goal: str = Field(..., description="学习目标")
    domain: str = Field(..., description="学习领域")
    daily_hours: float = Field(default=2, ge=0.5, le=12, description="每日学习时长（小时）")
    deadline: Optional[str] = Field(default=None, description="目标截止日期 YYYY-MM-DD")
    current_level: str = Field(default="beginner", description="当前水平: beginner/intermediate/advanced")
    preferences: Optional[Dict] = Field(default=None, description="学习偏好")


class StudyPhase(BaseModel):
    """学习阶段"""
    name: str
    duration: str
    goals: List[str]
    key_points: List[str]


class StudyPlan(BaseModel):
    """学习计划"""
    goal: str
    domain: str
    total_duration: str
    phases: List[StudyPhase]
    daily_schedule: List[Dict]
    tips: List[str]


class GeneratePlanResponse(BaseModel):
    """学习计划生成响应"""
    success: bool = True
    plan: Optional[StudyPlan] = None


# ==================== 错题分析模型 ====================

class AnalyzeMistakeRequest(BaseModel):
    """错题分析请求"""
    question: str = Field(..., description="题目内容")
    user_answer: str = Field(..., description="用户的答案")
    correct_answer: Optional[str] = Field(default=None, description="正确答案（可选）")
    subject: str = Field(default="", description="学科")
    image_url: Optional[str] = Field(default=None, description="题目图片 URL")


class MistakeAnalysis(BaseModel):
    """错题分析结果"""
    error_type: str = ""
    error_reason: str = ""
    correct_solution: str = ""
    knowledge_points: List[str] = []
    similar_questions: List[str] = []
    study_suggestions: List[str] = []


class AnalyzeMistakeResponse(BaseModel):
    """错题分析响应"""
    success: bool = True
    analysis: Optional[MistakeAnalysis] = None


# ==================== 每日任务生成模型 ====================

class GenerateTasksRequest(BaseModel):
    """每日任务生成请求"""
    plan_id: str = Field(..., description="学习计划 ID")
    domain: str = Field(..., description="学习领域")
    daily_hours: float = Field(default=2, description="每日学习时长")
    current_phase: Optional[Dict] = Field(default=None, description="当前学习阶段")
    learning_history: Optional[Dict] = Field(default=None, description="学习历史统计")
    today_stats: Optional[Dict] = Field(default=None, description="今日任务统计")


class StudyTask(BaseModel):
    """学习任务"""
    title: str
    description: str
    duration: int  # 分钟
    priority: str  # high/medium/low
    type: str  # review/learn/practice/rest


class GenerateTasksResponse(BaseModel):
    """每日任务生成响应"""
    success: bool = True
    tasks: List[StudyTask] = []

