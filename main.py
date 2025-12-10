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
from app.routers import chat_router, recognize_router, search_router, plan_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    print(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} 启动中...")
    print(f"📍 API 文档地址: /docs")
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
            "analyze_mistake": {
                "path": "/api/plan/analyze-mistake",
                "methods": ["POST"],
                "description": "错题分析",
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
