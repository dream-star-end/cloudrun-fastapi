# Requirements Document

## Introduction

本文档定义了将 `AIService` 类中所有使用硬编码 `AI_MODELS` 配置的方法重构为使用用户模型配置（`ModelConfigService`）的需求。

当前问题：`AIService` 中的多个方法（如 `chat()`、`chat_json()`、`chat_stream()`、`recognize_image()` 等）直接使用 `config.py` 中的 `AI_MODELS` 字典获取模型配置，但该字典不包含 API Key（API Key 现在存储在用户的数据库配置中）。这导致这些方法在调用时会因缺少 API Key 而失败。

## Glossary

- **AIService**: AI 服务类，提供文本对话、图片识别、错题分析等 AI 功能
- **ModelConfigService**: 模型配置服务，负责从云数据库读取用户配置的模型信息
- **AI_MODELS**: `config.py` 中的硬编码模型配置字典，不包含 API Key
- **openid**: 微信用户的唯一标识符，用于关联用户的模型配置
- **model_type**: 模型类型，包括 text（文本）、voice（语音）、multimodal（多模态/视觉）

## Requirements

### Requirement 1: 文本对话方法支持用户配置

**User Story:** As a 用户, I want AI 对话功能使用我配置的模型, so that 我可以使用自己的 API Key 进行对话。

#### Acceptance Criteria

1. WHEN `AIService.chat()` 被调用时, THE AIService SHALL 接受 `openid` 参数
2. WHEN `openid` 参数存在时, THE AIService SHALL 使用 `ModelConfigService.get_model_for_type()` 获取用户配置的模型
3. IF 用户未配置模型或配置无效, THEN THE AIService SHALL 返回明确的错误提示，引导用户配置模型
4. WHEN `AIService.chat_json()` 被调用时, THE AIService SHALL 接受 `openid` 参数并使用用户配置
5. WHEN `AIService.chat_stream()` 被调用时, THE AIService SHALL 接受 `openid` 参数并使用用户配置

### Requirement 2: 图片识别方法支持用户配置

**User Story:** As a 用户, I want 图片识别功能使用我配置的多模态模型, so that 我可以使用自己的 API Key 进行图片识别。

#### Acceptance Criteria

1. WHEN `AIService.recognize_image()` 被调用时, THE AIService SHALL 接受 `openid` 参数
2. WHEN `openid` 参数存在时, THE AIService SHALL 使用 `ModelConfigService.get_model_for_type(openid, "multimodal")` 获取用户配置
3. WHEN `AIService.recognize_image_stream()` 被调用时, THE AIService SHALL 接受 `openid` 参数并使用用户配置
4. IF 用户未配置多模态模型, THEN THE AIService SHALL 返回明确的错误提示

### Requirement 3: 错题分析方法支持用户配置

**User Story:** As a 用户, I want 错题分析功能使用我配置的模型, so that 我可以使用自己的 API Key 进行错题分析。

#### Acceptance Criteria

1. WHEN `AIService.analyze_mistake()` 被调用时, THE AIService SHALL 接受 `openid` 参数
2. WHEN 分析包含图片时, THE AIService SHALL 使用用户配置的多模态模型
3. WHEN 分析不包含图片时, THE AIService SHALL 使用用户配置的文本模型
4. IF 用户未配置相应类型的模型, THEN THE AIService SHALL 返回明确的错误提示

### Requirement 4: 路由层传递用户身份

**User Story:** As a 开发者, I want 所有调用 AIService 的路由都能正确传递 openid, so that AIService 可以获取用户的模型配置。

#### Acceptance Criteria

1. WHEN `/api/chat` 路由调用 `AIService.chat()` 时, THE Router SHALL 传递从请求头获取的 `openid`
2. WHEN `/api/chat/stream` 路由调用 `AIService.chat_stream()` 时, THE Router SHALL 传递 `openid`
3. WHEN `/api/recognize` 路由调用 `AIService.recognize_image()` 时, THE Router SHALL 传递 `openid`
4. WHEN `/api/recognize/stream` 路由调用 `AIService.recognize_image_stream()` 时, THE Router SHALL 传递 `openid`
5. WHEN `/api/plan/analyze-mistake` 路由调用 `AIService.analyze_mistake()` 时, THE Router SHALL 传递 `openid`

### Requirement 5: 服务层传递用户身份

**User Story:** As a 开发者, I want PlanService 等服务层能正确传递 openid 到 AIService, so that 计划生成等功能可以使用用户配置的模型。

#### Acceptance Criteria

1. WHEN `PlanService.generate_study_plan()` 调用 `AIService.chat()` 时, THE PlanService SHALL 接受并传递 `openid` 参数
2. WHEN `PlanService.generate_daily_tasks()` 调用 `AIService.chat()` 时, THE PlanService SHALL 接受并传递 `openid` 参数
3. WHEN `PlanService.generate_daily_tasks_stream()` 调用 `AIService.chat_stream()` 时, THE PlanService SHALL 接受并传递 `openid` 参数
4. WHEN `PlanService.generate_phase_detail()` 调用 `AIService.chat_json()` 时, THE PlanService SHALL 接受并传递 `openid` 参数

### Requirement 6: 错误处理与用户提示

**User Story:** As a 用户, I want 在模型配置缺失时收到清晰的错误提示, so that 我知道需要去配置模型。

#### Acceptance Criteria

1. IF 用户未配置任何模型, THEN THE System SHALL 返回错误信息 "请先在「个人中心 → 模型配置」中配置 AI 模型的 API Key"
2. IF 用户配置的模型 API Key 无效, THEN THE System SHALL 返回包含具体错误原因的提示
3. WHEN 错误发生时, THE System SHALL 记录详细的错误日志以便排查
