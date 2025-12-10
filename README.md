# 快速部署 FastAPI 应用

本篇文章为您介绍应用控制台的部署方案, 您可以通过以下操作完成部署。

## 模版部署 FastAPI 应用

1、登录 [腾讯云托管控制台](https://tcb.cloud.tencent.com/dev#/platform-run/service/create?type=image)

2、点击通过模版部署，选择 ```FastAPI 模版```

3、输入自定义服务名称，点击部署

4、等待部署完成之后，点击左上角箭头，返回到服务详情页

5、点击概述，获取默认域名并访问，会显示云托管默认首页

## 自定义部署 FastAPI 应用

### 创建一个 FastAPI 应用

1、新建一个 fastapi-app 目录

2、在 fastapi-app 目录中，新建一个 app.py 文件，内容如下：

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def root():
    return {"greeting": "Hello, World!", "message": "Welcome to FastAPI!"}
```

这个 app.py 文件定义了一个 FastAPI 应用，它包含一个根路径（"/"）和一个 GET 请求处理函数（root）。当用户访问根路径时，应用会返回一个包含问候语和欢迎信息的 JSON 响应。

3、在 fastapi-app 目录中，新建一个 requirements.txt 文件，内容如下：

```
fastapi==0.100.0
hypercorn==0.14.4
```

这个 requirements.txt 文件定义了 FastAPI 应用所需的依赖项。其中 [hypercorn](https://github.com/pgjones/hypercorn) 是 FastAPI 运行时需要的 ASGI 服务器。

4、安装依赖启动服务

使用 pip 安装依赖：

```bash
pip install -r requirements.txt
```

推荐使用虚拟环境安装依赖：

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

安装完成后，使用 hypercorn 启动服务：

```bash
hypercorn main:app --bind 0.0.0.0:80
```

访问`http://127.0.0.1:80`即可返回相应结果。

### 部署到云托管

1、在cloudrun-fastapi目录下创建一个名称为Dockerfile的新文件,内容如下:

```
FROM python:3-alpine

# 设定当前的工作目录
WORKDIR /app

# 拷贝当前项目到容器中
COPY . .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 启动服务
CMD ["hypercorn", "main:app", "--bind", "0.0.0.0:80"]
```

2、进入 [腾讯云托管](https://tcb.cloud.tencent.com/dev#/platform-run/service/create?type=package),

3、选择 ```通过本地代码``` 部署，

4、填写配置信息:

  * 代码包类型: 选择文件夹
  * 代码包: 点击选择 cloudrun-fastapi 目录，并上传目录文件
  * 服务名称: 填写服务名称
  * 部署类型: 选择容器服务型
  * 端口: 默认填写 80
  * 目标目录: 默认为空
  * Dockerfile 名称: Dockerfile
  * 环境变量: 如果有按需要填写
  * 公网访问: 默认打开
  * 内网访问: 默认关闭

5、配置填写完成之后，点击部署等待部署完成，

6、部署完成之后，跳转到服务概述页面，点击默认域名进行公网访问及测试。
