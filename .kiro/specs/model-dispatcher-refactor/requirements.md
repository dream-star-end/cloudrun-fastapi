# Requirements Document

## Introduction

重构 `model_dispatchers.py` 模块，将当前 1270 行的单一文件拆分为多个职责清晰的模块。当前文件包含 5 个分发器类（ModelDispatcher、OpenAICompatibleDispatcher、GeminiDispatcher、GeminiAudioDispatcher、OpenAISTTDispatcher），存在以下问题：

1. 单文件过大，难以维护
2. 各分发器之间存在重复代码（如流式请求处理、错误处理）
3. 工具函数（如 MIME 类型推断、音频下载）与业务逻辑混杂
4. 扩展新平台需要修改核心文件

## Glossary

- **Dispatcher**: 模型调用分发器，负责将请求路由到对应的 AI 模型 API
- **Dispatcher_Registry**: 分发器注册表，管理所有可用分发器的注册和获取
- **Stream_Handler**: 流式响应处理器，处理 SSE 流式响应的解析和错误恢复
- **Audio_Utils**: 音频工具模块，提供音频下载、格式转换、MIME 类型推断等功能
- **Message_Converter**: 消息格式转换器，在不同 API 格式之间转换消息

## Requirements

### Requirement 1: 模块化拆分

**User Story:** As a developer, I want the dispatcher code to be organized into separate modules, so that I can easily locate and modify specific functionality.

#### Acceptance Criteria

1. THE Refactored_System SHALL organize dispatchers into a `dispatchers/` package directory
2. THE Refactored_System SHALL create separate files for each dispatcher type (openai.py, gemini.py, audio.py)
3. THE Refactored_System SHALL extract common utilities into a `utils/` subdirectory
4. THE Refactored_System SHALL maintain backward compatibility with existing import paths through `__init__.py` re-exports

### Requirement 2: 分发器注册机制

**User Story:** As a developer, I want a registry pattern for dispatchers, so that I can add new platform support without modifying core code.

#### Acceptance Criteria

1. THE Dispatcher_Registry SHALL provide a `register()` method to register new dispatcher classes
2. THE Dispatcher_Registry SHALL provide a `get_dispatcher()` method that returns the appropriate dispatcher based on platform and model
3. WHEN a new dispatcher is registered, THE Dispatcher_Registry SHALL make it available for routing without code changes to the registry
4. THE Dispatcher_Registry SHALL support priority-based dispatcher selection when multiple dispatchers match

### Requirement 3: 流式响应处理抽象

**User Story:** As a developer, I want stream handling logic to be reusable, so that I can avoid duplicating error recovery code across dispatchers.

#### Acceptance Criteria

1. THE Stream_Handler SHALL provide a common interface for processing SSE streams
2. THE Stream_Handler SHALL handle timeout errors with partial content recovery
3. THE Stream_Handler SHALL handle connection errors with graceful degradation
4. WHEN a stream is interrupted, THE Stream_Handler SHALL yield a `stream_interrupted` event with partial content length
5. THE Stream_Handler SHALL support both OpenAI-style and Gemini-style SSE formats

### Requirement 4: 音频处理工具模块

**User Story:** As a developer, I want audio utilities to be centralized, so that all dispatchers can share audio processing logic.

#### Acceptance Criteria

1. THE Audio_Utils SHALL provide a function to download audio from URL
2. THE Audio_Utils SHALL provide a function to infer MIME type from URL or content
3. THE Audio_Utils SHALL provide a function to convert audio to base64 format
4. THE Audio_Utils SHALL provide a function to validate audio file headers
5. WHEN audio download fails, THE Audio_Utils SHALL return a descriptive error

### Requirement 5: 消息格式转换

**User Story:** As a developer, I want message conversion logic to be separate from dispatchers, so that format transformations are testable and reusable.

#### Acceptance Criteria

1. THE Message_Converter SHALL convert OpenAI format messages to Gemini format
2. THE Message_Converter SHALL convert OpenAI format messages to include audio content
3. THE Message_Converter SHALL handle multimodal content (text, images, audio)
4. THE Message_Converter SHALL extract system instructions from message lists
5. FOR ALL valid OpenAI format messages, converting to Gemini format and back SHALL preserve semantic content (round-trip property)

### Requirement 6: 基类抽象优化

**User Story:** As a developer, I want a well-defined base class, so that implementing new dispatchers follows a consistent pattern.

#### Acceptance Criteria

1. THE ModelDispatcher base class SHALL define abstract methods for `call()` and `supports()`
2. THE ModelDispatcher base class SHALL provide default implementations for common operations
3. THE ModelDispatcher base class SHALL define a standard response event format
4. WHEN implementing a new dispatcher, THE developer SHALL only need to implement platform-specific logic

### Requirement 7: 配置与依赖注入

**User Story:** As a developer, I want dispatchers to receive configuration through injection, so that they are easier to test and configure.

#### Acceptance Criteria

1. THE Dispatcher SHALL accept HTTP client configuration through constructor or method parameters
2. THE Dispatcher SHALL not directly import global settings within business logic
3. WHEN testing a dispatcher, THE test code SHALL be able to inject mock configurations
4. THE Dispatcher SHALL support custom timeout configurations per request type

