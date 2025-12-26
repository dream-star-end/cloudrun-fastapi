# Implementation Plan: Model Dispatcher Refactor

## Overview

将 `model_dispatchers.py`（1270 行）重构为模块化的 `dispatchers/` 包。采用渐进式迁移策略，确保向后兼容性。

## Tasks

- [x] 1. 创建包结构和工具模块
  - [x] 1.1 创建 `dispatchers/` 包目录结构
    - 创建 `app/services/dispatchers/` 目录
    - 创建 `app/services/dispatchers/utils/` 子目录
    - 创建各模块的 `__init__.py` 文件
    - _Requirements: 1.1, 1.3_

  - [x] 1.2 实现 `audio_utils.py` 音频工具模块
    - 实现 `AudioUtils` 类
    - 包含 `download_audio()`, `get_mime_type()`, `to_base64()`, `validate_audio()` 方法
    - 提取现有代码中的 MIME 类型映射和音频签名常量
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 1.3 编写 `audio_utils.py` 属性测试
    - **Property 4: Audio MIME Type Inference**
    - **Property 5: Audio Validation**
    - **Property 6: Base64 Round-Trip**
    - **Validates: Requirements 4.2, 4.3, 4.4**

  - [x] 1.4 实现 `message_converter.py` 消息转换模块
    - 实现 `MessageConverter` 类
    - 包含 `to_gemini_format()`, `to_openrouter_audio_format()`, `extract_system_instruction()` 方法
    - 提取现有的消息格式转换逻辑
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 1.5 编写 `message_converter.py` 属性测试
    - **Property 7: Multimodal Message Conversion**
    - **Property 8: System Instruction Extraction**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**

  - [x] 1.6 实现 `stream_handler.py` 流处理模块
    - 实现 `StreamHandler` 类
    - 包含 `handle_openai_stream()`, `handle_gemini_stream()`, `handle_stream_error()` 方法
    - 提取现有的 SSE 解析和错误恢复逻辑
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ]* 1.7 编写 `stream_handler.py` 属性测试
    - **Property 2: Stream Error Handling with Partial Recovery**
    - **Property 3: SSE Format Parsing**
    - **Validates: Requirements 3.2, 3.3, 3.4, 3.5**

- [x] 2. Checkpoint - 确保工具模块测试通过
  - 运行所有工具模块测试
  - 确保所有属性测试通过
  - 如有问题，询问用户

- [x] 3. 实现基类和注册表
  - [x] 3.1 实现 `base.py` 基类模块
    - 实现 `ModelDispatcher` 抽象基类
    - 定义 `call()`, `supports()`, `priority()` 方法
    - 定义响应事件类型（TypedDict）
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 3.2 实现 `DispatcherRegistry` 注册表
    - 实现 `register()` 装饰器方法
    - 实现 `get_dispatcher()` 选择方法
    - 支持优先级排序
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ]* 3.3 编写注册表属性测试
    - **Property 1: Registry Registration and Selection**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

- [x] 4. 实现各分发器模块
  - [x] 4.1 实现 `openai_compatible.py`
    - 迁移 `OpenAICompatibleDispatcher` 类
    - 使用 `StreamHandler` 处理流式响应
    - 实现 `supports()` 方法
    - 使用 `@DispatcherRegistry.register` 装饰器注册
    - _Requirements: 6.4, 7.1, 7.4_

  - [x] 4.2 实现 `gemini.py`
    - 迁移 `GeminiDispatcher` 类
    - 使用 `MessageConverter` 转换消息格式
    - 使用 `StreamHandler` 处理流式响应
    - 实现 `supports()` 方法
    - _Requirements: 6.4, 7.1, 7.4_

  - [x] 4.3 实现 `gemini_audio.py`
    - 迁移 `GeminiAudioDispatcher` 类
    - 使用 `AudioUtils` 处理音频
    - 使用 `MessageConverter` 构建音频消息
    - 实现 `supports()` 方法，优先级高于 `GeminiDispatcher`
    - _Requirements: 6.4, 7.1, 7.4_

  - [x] 4.4 实现 `openai_stt.py`
    - 迁移 `OpenAISTTDispatcher` 类
    - 使用 `AudioUtils` 下载和处理音频
    - 实现 `supports()` 方法
    - _Requirements: 6.4, 7.1, 7.4_

- [x] 5. Checkpoint - 确保分发器模块正常工作
  - 运行所有分发器测试
  - 验证分发器注册和选择逻辑
  - 如有问题，询问用户

- [x] 6. 配置导出和向后兼容
  - [x] 6.1 配置 `dispatchers/__init__.py` 导出
    - 导出所有公共类：`ModelDispatcher`, `DispatcherRegistry`, 各分发器类
    - 导出工具类：`StreamHandler`, `AudioUtils`, `MessageConverter`
    - 导出 `get_dispatcher` 便捷函数
    - _Requirements: 1.4_

  - [x] 6.2 更新原 `model_dispatchers.py` 为重导出模块
    - 从 `dispatchers` 包重新导出所有类
    - 保持原有的 `ModelDispatcher.get_dispatcher()` 静态方法可用
    - _Requirements: 1.4_

  - [ ]* 6.3 编写向后兼容性测试
    - **Property 9: Backward Compatibility**
    - 验证原有导入路径仍然有效
    - **Validates: Requirements 1.4**

- [x] 7. 最终验证
  - [x] 7.1 运行完整测试套件
    - 运行所有属性测试
    - 运行所有单元测试
    - 确保无回归
    - _Requirements: All_

  - [x] 7.2 验证现有功能
    - 确保 `model_router.py` 等依赖模块正常工作
    - 验证 API 端点正常响应
    - _Requirements: 1.4_

- [x] 8. Final Checkpoint - 确保所有测试通过
  - 确保所有测试通过
  - 如有问题，询问用户

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- 迁移过程中保持原文件不变，直到新模块完全就绪
- 使用 `hypothesis` 库进行属性测试

