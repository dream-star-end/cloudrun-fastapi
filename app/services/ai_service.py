"""
AI 服务模块
支持多种 AI 模型调用，包括文本、视觉模型
"""
import httpx
import json
from typing import List, Dict, AsyncGenerator, Optional
from ..config import AI_MODELS, settings, get_http_client_kwargs
from .model_config_service import ModelConfigService


class AIService:
    """AI 服务类"""
    
    @classmethod
    async def _get_model_config(
        cls,
        openid: Optional[str],
        model_type: str,
    ) -> Dict:
        """
        获取模型配置的统一方法
        
        Args:
            openid: 用户 openid，为 None 时抛出错误
            model_type: 模型类型 (text/multimodal/vision)
        
        Returns:
            包含 base_url, api_key, model 的配置字典
        
        Raises:
            ValueError: 当配置无效或缺少 API Key 时
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not openid:
            raise ValueError("请先在「个人中心 → 模型配置」中配置 AI 模型的 API Key")
        
        try:
            user_model = await ModelConfigService.get_model_for_type(openid, model_type)
            if user_model.get("api_key"):
                logger.info(f"[AIService] 使用用户配置: openid={openid[:8]}***, type={model_type}, platform={user_model.get('platform')}, model={user_model.get('model')}")
                return {
                    "base_url": user_model["base_url"],
                    "api_key": user_model["api_key"],
                    "model": user_model["model"],
                }
        except Exception as e:
            logger.warning(f"[AIService] 获取用户模型配置失败: {e}")
        
        # 用户未配置或配置无效
        raise ValueError("请先在「个人中心 → 模型配置」中配置 AI 模型的 API Key")
    
    # 学习教练系统提示词
    COACH_SYSTEM_PROMPT = """你是一位专业、耐心、有爱心的AI学习教练。你的目标是帮助学生高效学习、解答疑惑、制定计划、监督进度。

你的特点：
1. 🎯 专注学习：所有回答都围绕学习和教育展开
2. 💡 因材施教：根据学生的水平和特点调整讲解方式
3. 🌟 积极鼓励：适时给予正面反馈和鼓励
4. 📚 知识丰富：能够解答各学科的问题
5. 📋 善于规划：帮助学生制定合理的学习计划

回复格式要求：
- 使用 Markdown 格式让回答更清晰
- 适当使用 emoji 增加亲和力
- 重要概念用粗体标注
- 复杂内容用列表或表格整理
- 公式使用 LaTeX 格式（$...$）

教练式对话要求：
1) 用户说“听不懂/卡住了/不会”时，先用 1-3 个追问定位卡点（概念/步骤/例子/术语/题意/报错），再对症解释。
2) 刷题/编程/推理类问题，优先苏格拉底式引导：先让用户说出已知、目标、思路与卡点，再给下一步提示；若用户明确要直接答案/赶时间，给答案但说明关键步骤。

可信度与风险边界：
- 对关键结论补充「依据」与「信心(高/中/低)」；信息不足先澄清，不要编造。
- 涉及医疗/法律/人身安全等敏感内容时，明确你不是专业人士，给一般性建议并建议寻求专业意见。

⚠️ 输出约束（非常重要）：
如果用户提示词明确要求“只返回JSON/只返回 JSON/只返回 JSON 数组/不要输出其他内容”，你必须严格只输出合法 JSON（不允许任何额外解释、标点或 Markdown）。"""
    
    @classmethod
    async def chat(
        cls,
        messages: List[Dict],
        model_type: str = "text",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        user_memory: Optional[Dict] = None,
        openid: Optional[str] = None,
    ) -> str:
        """
        非流式 AI 对话
        
        Args:
            messages: 对话历史
            model_type: 模型类型 (text/vision/longtext)
            temperature: 生成温度
            max_tokens: 最大生成长度
            user_memory: 用户记忆/画像
            openid: 用户 openid，用于获取用户配置的模型
        
        Returns:
            AI 回复内容
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # 获取用户配置的模型
        config = await cls._get_model_config(openid, model_type)
        
        # 构建完整的消息列表
        full_messages = cls._build_messages(messages, user_memory)
        
        logger.info(f"[AIService] 开始 AI 调用: model={config['model']}, max_tokens={max_tokens}")
        
        try:
            async with httpx.AsyncClient(**get_http_client_kwargs(120.0)) as client:
                response = await client.post(
                    f"{config['base_url']}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {config['api_key']}",
                    },
                    json={
                        "model": config["model"],
                        "messages": full_messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "stream": False,
                    },
                )
                
                logger.info(f"[AIService] AI 响应状态码: {response.status_code}")
                
                if response.status_code != 200:
                    error_text = response.text[:500] if response.text else "无响应内容"
                    logger.error(f"[AIService] AI API 错误: status={response.status_code}, body={error_text}")
                    raise ValueError(f"AI API 错误 ({response.status_code}): {error_text[:200]}")
                
                data = response.json()
                
                if data.get("choices") and data["choices"][0].get("message"):
                    content = data["choices"][0]["message"]["content"]
                    logger.info(f"[AIService] AI 调用成功, 响应长度: {len(content)}")
                    return content
                
                logger.error(f"[AIService] AI 返回格式异常: {json.dumps(data, ensure_ascii=False)[:500]}")
                raise ValueError("AI 返回格式错误")
                
        except httpx.TimeoutException as e:
            logger.error(f"[AIService] AI 调用超时: {e}")
            raise ValueError(f"AI 服务响应超时，请稍后重试")
        except httpx.RequestError as e:
            logger.error(f"[AIService] AI 网络请求错误: {type(e).__name__}: {e}")
            raise ValueError(f"AI 服务网络错误: {str(e)}")
    
    @classmethod
    async def chat_json(
        cls,
        messages: List[Dict],
        model_type: str = "text",
        temperature: float = 0.5,
        max_tokens: int = 2000,
        timeout: float = 180.0,
        openid: Optional[str] = None,
    ) -> Dict:
        """
        JSON 模式 AI 对话 - 使用大模型原生 JSON 能力
        
        Args:
            messages: 对话历史
            model_type: 模型类型 (text/vision/longtext)
            temperature: 生成温度（JSON 模式建议用较低温度）
            max_tokens: 最大生成长度
            timeout: 超时时间（秒），默认 180 秒
            openid: 用户 openid，用于获取用户配置的模型
        
        Returns:
            解析后的 JSON 字典
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # 获取用户配置的模型
        config = await cls._get_model_config(openid, model_type)
        
        # 对于 JSON 模式，不需要系统提示词（避免干扰 JSON 输出）
        full_messages = messages.copy()
        
        logger.info(f"[AIService] 开始 JSON 模式 AI 调用: model={config['model']}, timeout={timeout}s")
        
        try:
            async with httpx.AsyncClient(**get_http_client_kwargs(timeout)) as client:
                request_body = {
                    "model": config["model"],
                    "messages": full_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                    "response_format": {"type": "json_object"},  # 启用 JSON 模式
                }
                
                response = await client.post(
                    f"{config['base_url']}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {config['api_key']}",
                    },
                    json=request_body,
                )
                
                logger.info(f"[AIService] JSON 模式响应状态码: {response.status_code}")
                
                if response.status_code != 200:
                    error_text = response.text[:500] if response.text else "无响应内容"
                    logger.error(f"[AIService] AI API 错误: status={response.status_code}, body={error_text}")
                    raise ValueError(f"AI API 错误 ({response.status_code})")
                
                data = response.json()
                
                if data.get("choices") and data["choices"][0].get("message"):
                    content = data["choices"][0]["message"]["content"]
                    logger.info(f"[AIService] JSON 模式调用成功, 响应长度: {len(content)}")
                    
                    # 解析 JSON
                    try:
                        result = json.loads(content)
                        return result
                    except json.JSONDecodeError as je:
                        logger.error(f"[AIService] JSON 解析失败: {je}, 内容: {content[:500]}")
                        raise ValueError(f"AI 返回的 JSON 格式无效: {je}")
                
                logger.error(f"[AIService] AI 返回格式异常")
                raise ValueError("AI 返回格式错误")
                
        except httpx.TimeoutException as e:
            logger.error(f"[AIService] JSON 模式 AI 调用超时: {e}")
            raise ValueError(f"AI 服务响应超时（{timeout}秒），请稍后重试")
        except httpx.RequestError as e:
            logger.error(f"[AIService] JSON 模式网络请求错误: {type(e).__name__}: {e}")
            raise ValueError(f"AI 服务网络错误: {str(e)}")
    
    @classmethod
    async def chat_stream(
        cls,
        messages: List[Dict],
        model_type: str = "text",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        user_memory: Optional[Dict] = None,
        openid: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式 AI 对话
        
        Args:
            messages: 对话历史
            model_type: 模型类型
            temperature: 生成温度
            max_tokens: 最大生成长度
            user_memory: 用户记忆/画像
            openid: 用户 openid，用于获取用户配置的模型
        
        Yields:
            AI 回复内容片段
        """
        # 获取用户配置的模型
        config = await cls._get_model_config(openid, model_type)
        
        # 构建完整的消息列表
        full_messages = cls._build_messages(messages, user_memory)
        
        async with httpx.AsyncClient(**get_http_client_kwargs(120.0)) as client:
            async with client.stream(
                "POST",
                f"{config['base_url']}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {config['api_key']}",
                },
                json={
                    "model": config["model"],
                    "messages": full_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            data = json.loads(data_str)
                            if data.get("choices") and data["choices"][0].get("delta"):
                                content = data["choices"][0]["delta"].get("content", "")
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue
    
    # 图片识别提示词映射
    RECOGNIZE_PROMPTS = {
        "ocr": "请识别并提取图片中的所有文字内容，保持原有的格式和结构。如果有表格，请用Markdown表格格式输出。",
        "explain": "请详细解释这张图片的内容，包括文字、图表、公式等，并给出通俗易懂的解释。如果是学习材料，请重点解析知识点。",
        "summary": "请用简洁的语言总结这张图片的主要内容和关键信息。列出3-5个要点。",
        "formula": "请识别图片中的数学公式或方程式，用LaTeX格式输出（使用$...$包裹），并解释其含义和应用场景。",
    }
    
    @classmethod
    def _build_vision_messages(
        cls,
        image_url: str,
        recognize_type: str = "ocr",
        custom_prompt: Optional[str] = None,
    ) -> List[Dict]:
        """构建视觉模型消息"""
        prompt = custom_prompt if custom_prompt else cls.RECOGNIZE_PROMPTS.get(
            recognize_type, "请描述这张图片的内容。"
        )
        
        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ]
    
    @classmethod
    async def recognize_image(
        cls,
        image_url: str,
        recognize_type: str = "ocr",
        custom_prompt: Optional[str] = None,
        openid: Optional[str] = None,
    ) -> str:
        """
        图片识别（非流式）
        
        Args:
            image_url: 图片 URL
            recognize_type: 识别类型 (ocr/explain/summary/formula)
            custom_prompt: 自定义提示词
            openid: 用户 openid，用于获取用户配置的模型
        
        Returns:
            识别结果
        """
        # 获取用户配置的多模态模型
        config = await cls._get_model_config(openid, "multimodal")
        messages = cls._build_vision_messages(image_url, recognize_type, custom_prompt)
        
        async with httpx.AsyncClient(**get_http_client_kwargs(120.0)) as client:
            response = await client.post(
                f"{config['base_url']}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {config['api_key']}",
                },
                json={
                    "model": config["model"],
                    "messages": messages,
                    "max_tokens": 4000,
                    "stream": False,
                },
            )
            
            response.raise_for_status()
            data = response.json()
            
            if data.get("choices") and data["choices"][0].get("message"):
                return data["choices"][0]["message"]["content"]
            
            raise ValueError("视觉 AI 返回格式错误")
    
    @classmethod
    async def recognize_image_stream(
        cls,
        image_url: str,
        recognize_type: str = "ocr",
        custom_prompt: Optional[str] = None,
        openid: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        图片识别（流式）
        
        Args:
            image_url: 图片 URL
            recognize_type: 识别类型 (ocr/explain/summary/formula)
            custom_prompt: 自定义提示词
            openid: 用户 openid，用于获取用户配置的模型
        
        Yields:
            识别结果片段
        """
        # 获取用户配置的多模态模型
        config = await cls._get_model_config(openid, "multimodal")
        messages = cls._build_vision_messages(image_url, recognize_type, custom_prompt)
        
        async with httpx.AsyncClient(**get_http_client_kwargs(120.0)) as client:
            async with client.stream(
                "POST",
                f"{config['base_url']}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {config['api_key']}",
                },
                json={
                    "model": config["model"],
                    "messages": messages,
                    "max_tokens": 4000,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            data = json.loads(data_str)
                            if data.get("choices") and data["choices"][0].get("delta"):
                                content = data["choices"][0]["delta"].get("content", "")
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue
    
    @classmethod
    async def analyze_mistake(
        cls,
        question: str,
        user_answer: str,
        correct_answer: Optional[str] = None,
        subject: str = "",
        image_url: Optional[str] = None,
        openid: Optional[str] = None,
    ) -> Dict:
        """
        错题分析
        
        Args:
            question: 题目内容
            user_answer: 用户答案
            correct_answer: 正确答案
            subject: 学科
            image_url: 题目图片
            openid: 用户 openid，用于获取用户配置的模型
        
        Returns:
            分析结果字典
        """
        prompt = f"""请分析以下错题，给出详细的分析和建议。

【题目】
{question}

【学生答案】
{user_answer}

{"【正确答案】" + chr(10) + correct_answer if correct_answer else ""}

{"【学科】" + subject if subject else ""}

请按以下JSON格式返回分析结果（只返回JSON）：
{{
    "error_type": "错误类型（如：概念理解错误、计算失误、审题不清等）",
    "error_reason": "详细的错误原因分析",
    "correct_solution": "正确的解题过程和答案",
    "knowledge_points": ["涉及的知识点1", "知识点2"],
    "similar_questions": ["类似题目的描述1", "类似题目2"],
    "study_suggestions": ["学习建议1", "建议2", "建议3"]
}}"""

        # 根据是否有图片选择模型类型
        model_type = "multimodal" if image_url else "text"
        config = await cls._get_model_config(openid, model_type)
        
        # 构建消息
        if image_url:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ]
        else:
            messages = [{"role": "user", "content": prompt}]
        
        async with httpx.AsyncClient(**get_http_client_kwargs(120.0)) as client:
            response = await client.post(
                f"{config['base_url']}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {config['api_key']}",
                },
                json={
                    "model": config["model"],
                    "messages": messages,
                    "max_tokens": 2000,
                    "temperature": 0.7,
                },
            )
            
            response.raise_for_status()
            data = response.json()
            
            if data.get("choices") and data["choices"][0].get("message"):
                content = data["choices"][0]["message"]["content"]
                
                # 解析 JSON
                import re
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    return json.loads(json_match.group())
            
            raise ValueError("错题分析返回格式错误")

    @classmethod
    async def analyze_mistake_text_stream(
        cls,
        question: str,
        user_answer: str,
        correct_answer: Optional[str] = None,
        subject: str = "",
        image_url: Optional[str] = None,
        openid: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        错题分析（流式，返回纯文本）

        用途：前端需要“边生成边展示”的体验；最终可以把完整文本保存到 mistakes.aiAnalysis。
        """
        prompt = f"""你是一名学习教练。请对下面错题进行分析，并直接输出【可读的中文文本】（不要输出 JSON）。

请按以下结构输出（保持标题不变）：
错误类型：
错误原因：
正确解法：
涉及知识点：
学习建议：

【题目】
{question}

【学生答案】
{user_answer}

{("【正确答案】" + chr(10) + str(correct_answer)) if correct_answer else ""}

{("【学科】" + str(subject)) if subject else ""}"""

        # 如果有图片，使用视觉模型
        import logging
        logger = logging.getLogger(__name__)
        
        # 确定模型类型：有图片用 multimodal，否则用 text
        model_type = "multimodal" if image_url else "text"
        
        # 优先使用用户配置的模型
        config = None
        if openid:
            try:
                user_model = await ModelConfigService.get_model_for_type(openid, model_type)
                if user_model.get("api_key"):
                    config = {
                        "base_url": user_model["base_url"],
                        "api_key": user_model["api_key"],
                        "model": user_model["model"],
                    }
                    logger.info(f"[AIService] 错题分析使用用户配置: platform={user_model.get('platform')}, model={user_model.get('model')}")
            except Exception as e:
                logger.warning(f"[AIService] 获取用户模型配置失败: {e}")
        
        # 如果用户未配置或配置无效，回退到系统默认
        if not config:
            fallback_type = "vision" if image_url else "text"
            fallback_config = AI_MODELS.get(fallback_type, AI_MODELS["text"])
            if not fallback_config.get("api_key"):
                raise ValueError("请先在「个人中心 → 模型配置」中配置 AI 模型的 API Key")
            config = fallback_config
            logger.info(f"[AIService] 错题分析使用系统默认: model={config.get('model')}")
        
        # 构建消息
        if image_url:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ]
        else:
            messages = [{"role": "user", "content": prompt}]

        async with httpx.AsyncClient(**get_http_client_kwargs(120.0)) as client:
            async with client.stream(
                "POST",
                f"{config['base_url']}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {config['api_key']}",
                },
                json={
                    "model": config["model"],
                    "messages": messages,
                    "max_tokens": 2000,
                    "temperature": 0.7,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        if data.get("choices") and data["choices"][0].get("delta"):
                            content = data["choices"][0]["delta"].get("content", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue
    
    @classmethod
    def _build_messages(
        cls,
        messages: List[Dict],
        user_memory: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        构建完整的消息列表，包含系统提示和用户记忆
        """
        full_messages = []
        
        # 1. 添加系统提示词
        system_prompt = cls.COACH_SYSTEM_PROMPT
        
        # 2. 如果有用户记忆，添加到系统提示中
        if user_memory:
            memory_info = cls._format_user_memory(user_memory)
            if memory_info:
                system_prompt += f"\n\n【用户档案】\n{memory_info}"
        
        full_messages.append({"role": "system", "content": system_prompt})
        
        # 3. 添加对话历史
        for msg in messages:
            full_messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })
        
        return full_messages
    
    @classmethod
    def _format_user_memory(cls, memory: Dict) -> str:
        """格式化用户记忆为文本"""
        parts = []
        
        profile = memory.get("profile", {})
        if profile.get("name"):
            parts.append(f"- 称呼：{profile['name']}")
        if profile.get("grade"):
            parts.append(f"- 年级/职业：{profile['grade']}")
        if profile.get("learningGoals"):
            parts.append(f"- 学习目标：{', '.join(profile['learningGoals'])}")
        if profile.get("subjects"):
            parts.append(f"- 正在学习：{', '.join(profile['subjects'])}")
        if profile.get("weakPoints"):
            parts.append(f"- 薄弱点：{', '.join(profile['weakPoints'])}")
        
        facts = memory.get("facts", [])
        if facts:
            recent_facts = [f["fact"] for f in facts[-5:]]
            parts.append(f"- 重要信息：{'; '.join(recent_facts)}")
        
        return "\n".join(parts) if parts else ""

