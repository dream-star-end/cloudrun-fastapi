# Implementation Plan: AIService 用户模型配置重构

## Overview

将 `AIService` 类中所有使用硬编码 `AI_MODELS` 配置的方法重构为使用用户模型配置（`ModelConfigService`）。

## Tasks

- [x] 1. 重构 AIService 核心方法
  - [x] 1.1 添加 `_get_model_config()` 辅助方法
    - 创建统一的配置获取方法
    - 接受 `openid` 和 `model_type` 参数
    - 调用 `ModelConfigService.get_model_for_type()`
    - 处理配置缺失的错误情况
    - _Requirements: 1.2, 1.3, 6.1_

  - [x] 1.2 重构 `chat()` 方法
    - 添加 `openid: Optional[str] = None` 参数
    - 使用 `_get_model_config()` 获取配置
    - 移除对 `AI_MODELS` 的直接引用
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 1.3 重构 `chat_json()` 方法
    - 添加 `openid: Optional[str] = None` 参数
    - 使用 `_get_model_config()` 获取配置
    - _Requirements: 1.4_

  - [x] 1.4 重构 `chat_stream()` 方法
    - 添加 `openid: Optional[str] = None` 参数
    - 使用 `_get_model_config()` 获取配置
    - _Requirements: 1.5_

- [x] 2. 重构 AIService 图片识别方法
  - [x] 2.1 重构 `recognize_image()` 方法
    - 添加 `openid: Optional[str] = None` 参数
    - 使用 `_get_model_config(openid, "multimodal")` 获取配置
    - _Requirements: 2.1, 2.2, 2.4_

  - [x] 2.2 重构 `recognize_image_stream()` 方法
    - 添加 `openid: Optional[str] = None` 参数
    - 使用 `_get_model_config(openid, "multimodal")` 获取配置
    - _Requirements: 2.3_

  - [x] 2.3 重构 `analyze_mistake()` 方法
    - 添加 `openid: Optional[str] = None` 参数
    - 根据是否有图片选择 "multimodal" 或 "text" 类型
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 3. Checkpoint - 验证 AIService 重构
  - 确保所有 AIService 方法都已添加 openid 参数
  - 确保所有方法都使用 _get_model_config() 获取配置
  - 如有问题请告知

- [x] 4. 重构 PlanService 方法
  - [x] 4.1 重构 `generate_study_plan()` 方法
    - 添加 `openid: Optional[str] = None` 参数
    - 传递 `openid` 到 `AIService.chat()`
    - _Requirements: 5.1_

  - [x] 4.2 重构 `generate_daily_tasks()` 方法
    - 添加 `openid: Optional[str] = None` 参数
    - 传递 `openid` 到 `AIService.chat()`
    - _Requirements: 5.2_

  - [x] 4.3 重构 `generate_daily_tasks_stream()` 方法
    - 添加 `openid: Optional[str] = None` 参数
    - 传递 `openid` 到 `AIService.chat_stream()`
    - _Requirements: 5.3_

  - [x] 4.4 重构 `generate_phase_detail()` 方法
    - 添加 `openid: Optional[str] = None` 参数
    - 传递 `openid` 到 `AIService.chat_json()`
    - _Requirements: 5.4_

- [x] 5. 更新 chat.py 路由
  - [x] 5.1 更新 `chat()` 路由
    - 传递 `openid` 到 `AIService.chat()`
    - _Requirements: 4.1_

  - [x] 5.2 更新 `chat_stream()` 路由
    - 传递 `openid` 到 `AIService.chat_stream()`
    - _Requirements: 4.2_

- [x] 6. 更新 recognize.py 路由
  - [x] 6.1 更新 `recognize_image()` 路由
    - 传递 `openid` 到 `AIService.recognize_image()`
    - _Requirements: 4.3_

  - [x] 6.2 更新 `recognize_image_stream()` 路由
    - 传递 `openid` 到 `AIService.recognize_image_stream()`
    - _Requirements: 4.4_

  - [x] 6.3 更新 `analyze_mistake_image()` 路由
    - 传递 `openid` 到 `AIService.recognize_image()` 和 `AIService.analyze_mistake()`
    - _Requirements: 4.3, 4.5_

- [x] 7. 更新 plan.py 路由
  - [x] 7.1 更新 `generate_plan()` 路由
    - 获取 `openid` 并传递到 `PlanService.generate_study_plan()`
    - _Requirements: 5.1_

  - [x] 7.2 更新 `generate_plan_stream()` 路由
    - 获取 `openid` 并传递到 `AIService.chat_stream()`
    - _Requirements: 4.2_

  - [x] 7.3 更新 `generate_phase_detail()` 路由
    - 传递 `openid` 到 `PlanService.generate_phase_detail()`
    - _Requirements: 5.4_

  - [x] 7.4 更新 `generate_phase_detail_stream()` 路由
    - 传递 `openid` 到 `PlanService.generate_phase_detail()`
    - _Requirements: 5.4_

  - [x] 7.5 更新 `generate_daily_tasks()` 路由
    - 传递 `openid` 到 `PlanService.generate_daily_tasks()`
    - _Requirements: 5.2_

  - [x] 7.6 更新 `analyze_mistake()` 路由
    - 传递 `openid` 到 `AIService.analyze_mistake()`
    - _Requirements: 4.5_

- [x] 8. Checkpoint - 验证所有路由更新
  - 确保所有路由都正确传递 openid
  - 如有问题请告知

- [x] 9. 清理未使用的代码
  - [x] 9.1 检查并移除 AIService 中对 AI_MODELS 的直接引用
    - 确保所有方法都通过 _get_model_config() 获取配置
    - 移除不再需要的 import
    - _Requirements: 1.2, 2.2_

- [x] 10. Final Checkpoint - 完成验证
  - 确保所有修改完成
  - 提醒用户部署云托管服务

## Notes

- 所有 `openid` 参数都设为可选（`Optional[str] = None`），保持向后兼容
- 当 `openid` 为 None 或用户未配置时，抛出明确的错误提示
- 修改完成后需要用户手动部署 cloudrun-fastapi 服务
