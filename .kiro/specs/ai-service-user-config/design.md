# Design Document: AIService 用户模型配置重构

## Overview

本设计文档描述如何将 `AIService` 类中所有使用硬编码 `AI_MODELS` 配置的方法重构为使用用户模型配置（`ModelConfigService`）。

核心变更：
1. 为所有 `AIService` 方法添加 `openid` 参数
2. 使用 `ModelConfigService.get_model_for_type()` 获取用户配置
3. 更新所有调用方（路由层、服务层）传递 `openid`
4. 统一错误处理，提供清晰的配置引导

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Router Layer                             │
│  (chat.py, recognize.py, plan.py)                               │
│  - 从请求头获取 openid                                           │
│  - 传递 openid 到 Service/AIService                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Service Layer                             │
│  (plan_service.py)                                              │
│  - 接受 openid 参数                                              │
│  - 传递 openid 到 AIService                                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         AIService                                │
│  - 接受 openid 参数                                              │
│  - 调用 ModelConfigService.get_model_for_type(openid, type)     │
│  - 使用返回的配置（base_url, api_key, model）调用 AI API         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     ModelConfigService                           │
│  - 从数据库读取用户配置                                          │
│  - 内存缓存（5分钟TTL）                                          │
│  - 返回 {platform, model, base_url, api_key}                    │
└─────────────────────────────────────────────────────────────────┘
```

## Components and Interfaces

### AIService 方法签名变更

```python
# 变更前
async def chat(
    cls,
    messages: List[Dict],
    model_type: str = "text",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    user_memory: Optional[Dict] = None,
) -> str

# 变更后
async def chat(
    cls,
    messages: List[Dict],
    model_type: str = "text",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    user_memory: Optional[Dict] = None,
    openid: Optional[str] = None,  # 新增参数
) -> str
```

所有需要变更的方法：
- `chat()` - 添加 `openid` 参数
- `chat_json()` - 添加 `openid` 参数
- `chat_stream()` - 添加 `openid` 参数
- `recognize_image()` - 添加 `openid` 参数
- `recognize_image_stream()` - 添加 `openid` 参数
- `analyze_mistake()` - 添加 `openid` 参数

### 配置获取逻辑

```python
async def _get_model_config(cls, openid: Optional[str], model_type: str) -> Dict:
    """
    获取模型配置的统一方法
    
    Args:
        openid: 用户 openid，为 None 时使用系统默认
        model_type: 模型类型 (text/multimodal/vision)
    
    Returns:
        包含 base_url, api_key, model 的配置字典
    
    Raises:
        ValueError: 当配置无效或缺少 API Key 时
    """
    if openid:
        user_model = await ModelConfigService.get_model_for_type(openid, model_type)
        if user_model.get("api_key"):
            return {
                "base_url": user_model["base_url"],
                "api_key": user_model["api_key"],
                "model": user_model["model"],
            }
    
    # 用户未配置或配置无效
    raise ValueError("请先在「个人中心 → 模型配置」中配置 AI 模型的 API Key")
```

### PlanService 方法签名变更

```python
# 变更前
async def generate_study_plan(
    cls,
    goal: str,
    domain: str,
    daily_hours: float = 2,
    deadline: Optional[str] = None,
    current_level: str = "beginner",
    preferences: Optional[Dict] = None,
) -> Dict

# 变更后
async def generate_study_plan(
    cls,
    goal: str,
    domain: str,
    daily_hours: float = 2,
    deadline: Optional[str] = None,
    current_level: str = "beginner",
    preferences: Optional[Dict] = None,
    openid: Optional[str] = None,  # 新增参数
) -> Dict
```

所有需要变更的方法：
- `generate_study_plan()` - 添加 `openid` 参数
- `generate_daily_tasks()` - 添加 `openid` 参数
- `generate_daily_tasks_stream()` - 添加 `openid` 参数
- `generate_phase_detail()` - 添加 `openid` 参数

### Router 层变更

路由层需要从请求头获取 `openid` 并传递给服务层：

```python
# chat.py
@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, raw_request: Request):
    openid = _get_openid_from_request(raw_request)
    # ...
    content = await AIService.chat(
        messages=messages,
        model_type=request.model_type,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        user_memory=request.user_memory,
        openid=openid,  # 传递 openid
    )
```

## Data Models

无新增数据模型。使用现有的 `ModelConfigService` 返回的配置结构：

```python
{
    "platform": str,      # 平台标识，如 "deepseek"
    "model": str,         # 模型名称，如 "deepseek-chat"
    "model_name": str,    # 模型显示名称
    "base_url": str,      # API 基础 URL
    "api_key": str,       # API Key
    "is_user_config": bool,  # 是否为用户配置
    "model_types": List[str],  # 模型支持的输入类型
}
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: 模型配置获取正确性

*For any* AIService 方法调用，当提供有效的 `openid` 时，应使用 `ModelConfigService.get_model_for_type()` 获取配置，且传递的 `model_type` 应与方法的功能匹配（文本方法传 "text"，图片方法传 "multimodal"）。

**Validates: Requirements 1.2, 2.2, 3.2, 3.3**

### Property 2: 错误处理一致性

*For any* AIService 方法调用，当用户未配置模型或配置无效时，应抛出包含配置引导信息的 `ValueError`，错误信息应包含 "个人中心 → 模型配置"。

**Validates: Requirements 1.3, 2.4, 3.4, 6.1**

### Property 3: openid 参数传递完整性

*For any* 路由到 AIService 的调用链，`openid` 应从请求头正确提取并传递到最终的 AIService 方法调用。

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4**

## Error Handling

### 错误类型与处理

| 错误场景 | 错误类型 | 错误信息 | 处理方式 |
|---------|---------|---------|---------|
| 用户未配置模型 | ValueError | "请先在「个人中心 → 模型配置」中配置 AI 模型的 API Key" | 返回 400/500 错误 |
| API Key 无效 | ValueError | "AI API 错误 (401): ..." | 返回 500 错误 |
| API 调用超时 | ValueError | "AI 服务响应超时，请稍后重试" | 返回 500 错误 |
| 网络错误 | ValueError | "AI 服务网络错误: ..." | 返回 500 错误 |

### 日志记录

所有错误应记录详细日志：
```python
logger.error(f"[AIService] {method_name} 失败: openid={openid[:8] if openid else 'None'}***, error={error}")
```

## Testing Strategy

### 单元测试

1. **AIService 方法测试**
   - 测试各方法接受 `openid` 参数
   - 测试配置获取逻辑
   - 测试错误处理

2. **PlanService 方法测试**
   - 测试 `openid` 参数传递

### 属性测试

使用 `pytest` + `hypothesis` 进行属性测试：

1. **Property 1 测试**: 验证 ModelConfigService 被正确调用
2. **Property 2 测试**: 验证错误信息格式一致
3. **Property 3 测试**: 验证 openid 传递完整性

### 集成测试

1. **端到端测试**
   - 测试完整的请求流程（Router → Service → AIService → ModelConfigService）
   - 使用 mock 数据库配置

2. **错误场景测试**
   - 测试无配置用户的错误响应
   - 测试无效 API Key 的错误响应
