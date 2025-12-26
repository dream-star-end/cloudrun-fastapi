# Implementation Plan: 多模态 Agent 统一

## Overview

将所有消息类型（文本、图片、语音）统一通过 LangChain Agent 处理，实现工具调用能力的全面支持。

## Tasks

- [x] 1. 扩展 Agent API 请求模型
  - [x] 1.1 在 `agent.py` 中添加 `MultimodalMessage` 模型
    - 定义 text, image_url, image_base64, voice_url, voice_text 字段
    - _Requirements: 2.1, 2.2_
  - [x] 1.2 修改 `AgentChatRequest` 添加 `multimodal` 字段
    - 保持 `message` 字段向后兼容
    - _Requirements: 3.1_

- [x] 2. 实现 LearningAgent 多模态支持
  - [x] 2.1 在 `core.py` 中添加 `_build_multimodal_content` 方法
    - 将多模态消息转换为 LangChain 格式
    - 支持图片 URL 和 Base64
    - _Requirements: 2.3_
  - [x] 2.2 添加 `_transcribe_voice` 方法
    - 调用 OpenAI Whisper 转录语音
    - _Requirements: 2.4_
  - [x] 2.3 修改 `chat_stream` 方法支持多模态
    - 接受 multimodal 参数
    - 调用 `_build_multimodal_content` 构建消息
    - _Requirements: 1.2, 1.3, 1.4_
  - [x] 2.4 修改 `chat` 方法支持多模态
    - 与 `chat_stream` 保持一致
    - _Requirements: 1.1_
  - [ ]* 2.5 编写多模态内容构建的单元测试
    - 测试纯文本、图片、语音、组合输入
    - **Property 2: 多模态内容转换**
    - _Requirements: 2.3_

- [x] 3. 修改 Agent API 路由
  - [x] 3.1 修改 `/api/agent/chat/stream` 端点
    - 解析 multimodal 字段
    - 传递给 LearningAgent
    - _Requirements: 3.1_
  - [x] 3.2 修改 `/api/agent/chat` 端点
    - 同步支持多模态
    - _Requirements: 3.1_
  - [x] 3.3 添加语音转文本事件
    - 在流式响应中返回 transcription 事件
    - _Requirements: 2.4_

- [x] 4. Checkpoint - 后端多模态支持完成
  - 确保所有测试通过，如有问题请询问用户

- [x] 5. 前端适配
  - [x] 5.1 新增 `agent.js` 模块
    - 实现 `agentChatStream` 函数支持多模态
    - _Requirements: 4.1, 4.3_
  - [x] 5.2 修改 `chat/index.js` 使用 Agent 接口
    - 图片消息改用 `agentChatStream`
    - 语音消息改用 `agentChatStream`
    - _Requirements: 4.1_
  - [x] 5.3 修改 `docreader/index.js` 使用 Agent 接口
    - 文档伴读场景适配
    - _Requirements: 4.1_

- [x] 6. Checkpoint - 前端适配完成
  - 确保前端能正常发送多模态消息，如有问题请询问用户

- [x] 7. 代码清理
  - [x] 7.1 删除 `chat_multimodal.py`
    - 移除 `/api/chat/multimodal` 路由
    - _Requirements: 5.1_
  - [x] 7.2 删除 `model_router.py`
    - 移除 ModelRouter 类
    - _Requirements: 5.2_
  - [x] 7.3 更新 `main.py` 移除旧路由注册
    - 移除 chat_multimodal router
    - _Requirements: 3.2, 3.3_
  - [x] 7.4 清理前端 `chat.js` 中的旧函数
    - 移除 `chatMultimodal` 和 `chatMultimodalStream`
    - _Requirements: 4.2_

- [x] 8. Final Checkpoint - 验证完整功能
  - 确保所有测试通过，如有问题请询问用户

## Notes

- 任务标记 `*` 为可选测试任务
- 每个任务引用具体的需求条款
- Checkpoint 用于阶段性验证
- 保持向后兼容，纯文本消息仍可使用 `message` 字段
