# AI Learning Coach - 云托管 API 服务

微信小程序云托管 FastAPI 服务，为 AI 学习教练小程序提供后端 AI 能力支持。

## 🚀 功能特性

### 🤖 AI 对话
- 支持流式响应 (Server-Sent Events)
- 多模型支持（文本/视觉/长文本）
- 学习教练专属系统提示词
- 用户画像记忆集成

### 🖼️ 图片识别
- OCR 文字识别
- 图片内容解释
- 内容摘要生成
- 数学公式识别 (LaTeX)

### 🔍 联网搜索
- Tavily 搜索引擎集成
- AI 生成搜索摘要
- 学习资源专项搜索

### 📋 学习计划
- AI 生成个性化学习计划
- 每日任务智能生成
- 错题分析与学习建议
- 支持多种学习领域模板

## 📁 项目结构

```
cloudrun-fastapi/
├── app/
│   ├── __init__.py
│   ├── config.py          # 配置管理
│   ├── models.py          # 数据模型
│   ├── routers/           # API 路由
│   │   ├── chat.py        # AI 对话
│   │   ├── recognize.py   # 图片识别
│   │   ├── search.py      # 联网搜索
│   │   └── plan.py        # 学习计划
│   └── services/          # 业务服务
│       ├── ai_service.py  # AI 服务
│       ├── search_service.py
│       └── plan_service.py
├── main.py                # 应用入口
├── requirements.txt       # 依赖
├── Dockerfile            # 容器配置
└── README.md
```

## 🔧 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 服务状态 |
| `/health` | GET | 健康检查 |
| `/api` | GET | API 信息 |
| `/api/chat` | POST | AI 对话（非流式） |
| `/api/chat/stream` | POST | AI 对话（流式 SSE） |
| `/api/recognize` | POST | 图片识别 |
| `/api/search` | POST | 联网搜索 |
| `/api/search/learning-resources` | GET | 搜索学习资源 |
| `/api/plan/generate` | POST | 生成学习计划 |
| `/api/plan/generate-tasks` | POST | 生成每日任务 |
| `/api/plan/analyze-mistake` | POST | 错题分析 |

## 🛠️ 本地开发

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

在 `app/config.py` 中配置以下内容：

```python
# DeepSeek API
DEEPSEEK_API_KEY = "your-api-key"

# 视觉模型 API
VISION_API_KEY = "your-vision-api-key"

# Tavily 搜索 API
TAVILY_API_KEY = "your-tavily-api-key"
```

### 3. 启动服务

```bash
# 开发模式
uvicorn main:app --reload --port 8000

# 或直接运行
python main.py
```

### 4. 访问 API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 🐳 Docker 部署

### 构建镜像

```bash
docker build -t ai-coach-api .
```

### 运行容器

```bash
docker run -d -p 80:80 ai-coach-api
```

## ☁️ 云托管部署

### 腾讯云云托管

1. 在云托管控制台创建服务
2. 选择「使用本地代码」或「连接代码仓库」
3. 配置环境变量（在控制台设置）
4. 部署并获取公网域名

### 配置微信小程序

1. 在小程序管理后台添加请求域名白名单
2. 更新小程序中的 `CLOUDRUN_BASE_URL`

## 📝 API 使用示例

### AI 对话（非流式）

```javascript
const res = await wx.request({
  url: 'https://your-domain/api/chat',
  method: 'POST',
  data: {
    messages: [
      { role: 'user', content: '你好，帮我解释一下勾股定理' }
    ],
    model_type: 'text',
    temperature: 0.7,
    max_tokens: 2000
  }
});
```

### 图片识别

```javascript
const res = await wx.request({
  url: 'https://your-domain/api/recognize',
  method: 'POST',
  data: {
    image_url: 'https://example.com/image.jpg',
    recognize_type: 'ocr'
  }
});
```

### 联网搜索

```javascript
const res = await wx.request({
  url: 'https://your-domain/api/search',
  method: 'POST',
  data: {
    query: 'Python 入门教程',
    max_results: 5
  }
});
```

### 生成学习计划

```javascript
const res = await wx.request({
  url: 'https://your-domain/api/plan/generate',
  method: 'POST',
  data: {
    goal: '掌握 Python 编程基础',
    domain: '编程技术',
    daily_hours: 2,
    current_level: 'beginner'
  }
});
```

## 📄 License

MIT License
