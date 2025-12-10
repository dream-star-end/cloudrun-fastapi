FROM python:3-alpine

# 设定当前的工作目录
WORKDIR /app

# 拷贝当前项目到容器中
COPY . .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 启动服务
CMD ["hypercorn", "main:app", "--bind", "0.0.0.0:80"]
