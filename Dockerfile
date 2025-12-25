# AI Learning Coach Cloud Run API Service
# 微信小程序云托管 Dockerfile

FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 暴露端口（云托管使用 80 端口）
EXPOSE 80

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:80/health || exit 1

# 启动命令
# 使用 uvicorn 直接启动，更好地支持 WebSocket 长连接
# gunicorn 的 timeout 设置可能会中断 WebSocket 连接
CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "80", \
     "--workers", "2", \
     "--timeout-keep-alive", "120", \
     "--ws-ping-interval", "20", \
     "--ws-ping-timeout", "20"]
