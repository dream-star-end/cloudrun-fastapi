"""
AI Learning Coach - Cloud Run API Service
微信小程序云托管 FastAPI 服务

API 端点：
- /api/chat       - AI 对话（支持流式响应）
- /api/recognize  - 图片识别 / OCR
- /api/search     - 联网搜索
- /api/plan       - 学习计划生成 & 错题分析
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.routers.chat import router as chat_router
from app.routers.recognize import router as recognize_router
from app.routers.search import router as search_router
from app.routers.plan import router as plan_router
from app.routers.tasks import router as tasks_router
from app.routers.agent import router as agent_router
from app.routers.mistakes import router as mistakes_router
from app.routers.community import router as community_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    print(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} 启动中...")
    print("📍 API 文档地址: /docs")
    yield
    # 关闭时
    print("👋 服务已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## AI 学习教练云托管 API 服务

为微信小程序提供以下 AI 能力：

### 🤖 AI 对话
- 支持流式响应 (SSE)
- 多模型支持（文本/视觉/长文本）
- 学习教练专属 prompt

### 🖼️ 图片识别
- OCR 文字识别
- 图片内容解释
- 数学公式识别

### 🔍 联网搜索
- 学习资源搜索
- AI 摘要生成

### 📋 学习计划
- AI 生成个性化学习计划
- 每日任务智能生成
- 错题分析与建议
""",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(chat_router)
app.include_router(recognize_router)
app.include_router(search_router)
app.include_router(plan_router)
app.include_router(tasks_router)
app.include_router(agent_router)  # AI Agent 路由
app.include_router(mistakes_router)  # 错题本 CRUD（替代云函数）
app.include_router(community_router)  # 学习社区路由


# ==================== 基础端点 ====================

@app.get("/")
async def root():
    """根路径 - 服务状态检查"""
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "message": "欢迎使用 AI 学习教练云托管服务",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """健康检查端点（用于云托管探活）"""
    return {"status": "healthy"}


@app.get("/api")
async def api_info():
    """API 信息"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "endpoints": {
            # AI Agent（推荐使用）
            "agent_chat": {
                "path": "/api/agent/chat",
                "methods": ["POST"],
                "description": "AI Agent 对话（非流式）- 支持工具调用和自主决策",
            },
            "agent_chat_stream": {
                "path": "/api/agent/chat/stream",
                "methods": ["POST"],
                "description": "AI Agent 对话（流式）- 实时返回思考过程和回复",
            },
            "agent_profile": {
                "path": "/api/agent/profile/{user_id}",
                "methods": ["GET"],
                "description": "获取用户画像 - Agent 根据对话自动更新",
            },
            "agent_suggestions": {
                "path": "/api/agent/suggestions/{user_id}",
                "methods": ["GET"],
                "description": "获取个性化建议 - 基于用户画像生成",
            },
            # 原有 API（保持兼容）
            "chat": {
                "path": "/api/chat",
                "methods": ["POST"],
                "description": "AI 对话（非流式）",
            },
            "chat_stream": {
                "path": "/api/chat/stream",
                "methods": ["POST"],
                "description": "AI 对话（流式 SSE）",
            },
            "recognize": {
                "path": "/api/recognize",
                "methods": ["POST"],
                "description": "图片识别（OCR/解释/公式）",
            },
            "search": {
                "path": "/api/search",
                "methods": ["POST"],
                "description": "联网搜索",
            },
            "search_resources": {
                "path": "/api/search/learning-resources",
                "methods": ["GET"],
                "description": "搜索学习资源",
            },
            "generate_plan": {
                "path": "/api/plan/generate",
                "methods": ["POST"],
                "description": "生成学习计划",
            },
            "generate_tasks": {
                "path": "/api/plan/generate-tasks",
                "methods": ["POST"],
                "description": "生成每日任务",
            },
            "ensure_today_tasks": {
                "path": "/api/tasks/today/ensure",
                "methods": ["POST"],
                "description": "确保今日任务存在（如不存在则在云托管侧生成并写入数据库）",
            },
            "analyze_mistake": {
                "path": "/api/plan/analyze-mistake",
                "methods": ["POST"],
                "description": "错题分析",
            },
            # 错题本（云托管替代云函数）
            "mistakes_list": {
                "path": "/api/mistakes/list",
                "methods": ["POST"],
                "description": "错题列表（分页/筛选）",
            },
            "mistakes_stats": {
                "path": "/api/mistakes/stats",
                "methods": ["GET"],
                "description": "错题统计（总数/待复习/已掌握）",
            },
            "mistakes_add": {
                "path": "/api/mistakes/add",
                "methods": ["POST"],
                "description": "添加错题（含自动标签）",
            },
            "mistakes_update": {
                "path": "/api/mistakes/update",
                "methods": ["POST"],
                "description": "更新错题（含复习+1/标记掌握）",
            },
            "mistakes_delete": {
                "path": "/api/mistakes/delete",
                "methods": ["POST"],
                "description": "删除错题",
            },
            "mistakes_review": {
                "path": "/api/mistakes/review",
                "methods": ["POST"],
                "description": "生成错题复习题目",
            },
            # 学习社区
            "community_stats": {
                "path": "/api/community/stats",
                "methods": ["GET"],
                "description": "社区统计数据",
            },
            "community_plans": {
                "path": "/api/community/plans/list",
                "methods": ["POST"],
                "description": "社区计划列表（热门/最新/我的分享）",
            },
            "community_share": {
                "path": "/api/community/share",
                "methods": ["POST"],
                "description": "分享学习计划到社区",
            },
            "community_like": {
                "path": "/api/community/like",
                "methods": ["POST"],
                "description": "点赞/取消点赞",
            },
            "community_comment": {
                "path": "/api/community/comment",
                "methods": ["POST"],
                "description": "添加评论",
            },
            "community_use": {
                "path": "/api/community/use",
                "methods": ["POST"],
                "description": "使用（复制）社区计划",
            },
        },
    }


# ==================== 启动配置 ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=80,
        reload=settings.DEBUG,
    )
