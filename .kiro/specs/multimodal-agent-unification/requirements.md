# Requirements Document

## Introduction

统一多模态消息处理架构，让所有消息（文本、图片、语音）都通过 LangChain Agent 处理，支持工具调用能力。同时清理冗余代码，简化架构。

## Glossary

- **Agent**: 基于 LangChain/LangGraph 的智能代理，支持工具调用
- **Multimodal_Message**: 包含文本、图片、语音等多种类型的消息
- **Tool_Calling**: Agent 根据用户意图自动调用工具（如搜索、打卡、错题分析等）

## Requirements

### Requirement 1: 统一消息入口

**User Story:** 作为用户，我希望发送任何类型的消息（文本/图片/语音）都能获得一致的 AI 响应体验，包括工具调用能力。

#### Acceptance Criteria

1. WHEN 用户发送文本消息 THEN Agent SHALL 处理消息并支持工具调用
2. WHEN 用户发送图片消息 THEN Agent SHALL 理解图片内容并支持工具调用
3. WHEN 用户发送语音消息 THEN Agent SHALL 理解语音内容并支持工具调用
4. WHEN 用户发送文本+图片组合消息 THEN Agent SHALL 同时理解文本和图片并支持工具调用

### Requirement 2: Agent 多模态支持

**User Story:** 作为开发者，我希望 LearningAgent 能够处理多模态输入，而不仅仅是纯文本。

#### Acceptance Criteria

1. THE LearningAgent SHALL 接受包含图片 URL 的消息
2. THE LearningAgent SHALL 接受包含语音 URL 的消息
3. WHEN 消息包含图片 THEN LearningAgent SHALL 将图片转换为 LangChain 多模态格式
4. WHEN 消息包含语音 THEN LearningAgent SHALL 先转录语音再处理，或使用支持音频的模型

### Requirement 3: API 简化

**User Story:** 作为开发者，我希望 API 接口简洁统一，减少维护成本。

#### Acceptance Criteria

1. THE System SHALL 提供统一的 `/api/agent/chat/stream` 接口处理所有消息类型
2. THE System SHALL 废弃或移除 `/api/chat/multimodal` 接口
3. THE System SHALL 废弃或移除 `ModelRouter` 相关代码（如不再需要）

### Requirement 4: 前端适配

**User Story:** 作为前端开发者，我希望调用方式简单统一。

#### Acceptance Criteria

1. THE Frontend SHALL 统一使用 Agent 接口发送所有类型消息
2. THE Frontend SHALL 移除对 `/api/chat/multimodal` 的调用
3. WHEN 发送多模态消息 THEN Frontend SHALL 使用统一的消息格式

### Requirement 5: 代码清理

**User Story:** 作为开发者，我希望代码库保持整洁，移除不再使用的代码。

#### Acceptance Criteria

1. IF `/api/chat/multimodal` 不再使用 THEN System SHALL 移除 `chat_multimodal.py`
2. IF `ModelRouter` 不再使用 THEN System SHALL 移除 `model_router.py`
3. THE System SHALL 保留 `model_dispatchers` 模块供 Agent 内部使用（如需要）
