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

## 本地开发

1. 创建 `.env` 文件，填入上述配置
2. 安装依赖：`pip install -r requirements.txt`
3. 启动服务：`python main.py` 或 `uvicorn main:app --reload --port 8000`

## 云托管部署

1. 在云托管控制台设置环境变量
2. 或在 `app/config.py` 中直接修改默认值

