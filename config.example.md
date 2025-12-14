# AI Learning Coach API 配置说明

## 环境变量配置

在部署前，需要配置以下环境变量：

### AI 模型配置

```bash
# DeepSeek API（文本模型）
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat

# 视觉模型 API
VISION_API_KEY=sk-your-vision-api-key
VISION_BASE_URL=https://api.openai.com/v1
VISION_MODEL=gpt-5.1
```

### 搜索配置

```bash
# Tavily 搜索 API
TAVILY_API_KEY=tvly-your-tavily-api-key
TAVILY_BASE_URL=https://api.tavily.com
```

### 腾讯云 COS 配置（用于 PDF 处理）

```bash
COS_SECRET_ID=your-cos-secret-id
COS_SECRET_KEY=your-cos-secret-key
COS_BUCKET=your-bucket-name
COS_REGION=ap-shanghai
```

### 应用配置

```bash
DEBUG=false
```

### 微信云开发 / 云托管数据库配置（用于 Agent 统计、打卡、任务等）

> 说明：后端通过微信云开发 HTTP API 访问数据库（`tcb/databasequery` 等）。
> 在云托管环境中，平台通常会注入 `WX_API_TOKEN`，后端会优先使用它；
> 如果未注入，则需要提供 `WX_APPID/WX_SECRET` 以换取 `access_token`。

```bash
# 云开发环境 ID（必须与小程序云开发环境一致）
TCB_ENV=prod-xxxxxxxxxxxxxxxx

# 方式 A：云托管环境（推荐）
WX_API_TOKEN=your-cloudrun-openapi-token
WX_API_TOKEN_EXPIRETIME=1730000000

# 方式 B：非云托管/本地开发（备用）
WX_APPID=wxxxxxxxxxxxxxxxxx
WX_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## 本地开发

1. 创建 `.env` 文件，填入上述配置
2. 安装依赖：`pip install -r requirements.txt`
3. 启动服务：`python main.py` 或 `uvicorn main:app --reload --port 8000`

## 云托管部署

1. 在云托管控制台设置环境变量
2. 或在 `app/config.py` 中直接修改默认值

