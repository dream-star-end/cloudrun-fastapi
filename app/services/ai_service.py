"""
AI 服务模块
支持多种 AI 模型调用，包括文本、视觉模型
"""
import httpx
import json
from typing import List, Dict, AsyncGenerator, Optional
from ..config import AI_MODELS, settings


class AIService:
    """AI 服务类"""
    
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
- 公式使用 LaTeX 格式（$...$）"""
    
    @classmethod
    async def chat(
        cls,
        messages: List[Dict],
        model_type: str = "text",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        user_memory: Optional[Dict] = None,
    ) -> str:
        """
        非流式 AI 对话
        
        Args:
            messages: 对话历史
            model_type: 模型类型 (text/vision/longtext)
            temperature: 生成温度
            max_tokens: 最大生成长度
            user_memory: 用户记忆/画像
        
        Returns:
            AI 回复内容
        """
        config = AI_MODELS.get(model_type, AI_MODELS["text"])
        
        # 构建完整的消息列表
        full_messages = cls._build_messages(messages, user_memory)
        
        async with httpx.AsyncClient(timeout=120.0) as client:
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
            
            response.raise_for_status()
            data = response.json()
            
            if data.get("choices") and data["choices"][0].get("message"):
                return data["choices"][0]["message"]["content"]
            
            raise ValueError("AI 返回格式错误")
    
    @classmethod
    async def chat_stream(
        cls,
        messages: List[Dict],
        model_type: str = "text",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        user_memory: Optional[Dict] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式 AI 对话
        
        Args:
            messages: 对话历史
            model_type: 模型类型
            temperature: 生成温度
            max_tokens: 最大生成长度
            user_memory: 用户记忆/画像
        
        Yields:
            AI 回复内容片段
        """
        config = AI_MODELS.get(model_type, AI_MODELS["text"])
        
        # 构建完整的消息列表
        full_messages = cls._build_messages(messages, user_memory)
        
        async with httpx.AsyncClient(timeout=120.0) as client:
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
    
    @classmethod
    async def recognize_image(
        cls,
        image_url: str,
        recognize_type: str = "ocr",
        custom_prompt: Optional[str] = None,
    ) -> str:
        """
        图片识别
        
        Args:
            image_url: 图片 URL
            recognize_type: 识别类型 (ocr/explain/summary/formula)
            custom_prompt: 自定义提示词
        
        Returns:
            识别结果
        """
        # 构建提示词
        if custom_prompt:
            prompt = custom_prompt
        else:
            prompts = {
                "ocr": "请识别并提取图片中的所有文字内容，保持原有的格式和结构。如果有表格，请用Markdown表格格式输出。",
                "explain": "请详细解释这张图片的内容，包括文字、图表、公式等，并给出通俗易懂的解释。如果是学习材料，请重点解析知识点。",
                "summary": "请用简洁的语言总结这张图片的主要内容和关键信息。列出3-5个要点。",
                "formula": "请识别图片中的数学公式或方程式，用LaTeX格式输出（使用$...$包裹），并解释其含义和应用场景。",
            }
            prompt = prompts.get(recognize_type, "请描述这张图片的内容。")
        
        config = AI_MODELS["vision"]
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ]
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{config['base_url']}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {config['api_key']}",
                },
                json={
                    "model": config["model"],
                    "messages": messages,
                    "max_tokens": config["max_tokens"],
                },
            )
            
            response.raise_for_status()
            data = response.json()
            
            if data.get("choices") and data["choices"][0].get("message"):
                return data["choices"][0]["message"]["content"]
            
            raise ValueError("视觉 AI 返回格式错误")
    
    @classmethod
    async def analyze_mistake(
        cls,
        question: str,
        user_answer: str,
        correct_answer: Optional[str] = None,
        subject: str = "",
        image_url: Optional[str] = None,
    ) -> Dict:
        """
        错题分析
        
        Args:
            question: 题目内容
            user_answer: 用户答案
            correct_answer: 正确答案
            subject: 学科
            image_url: 题目图片
        
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

        # 如果有图片，使用视觉模型
        if image_url:
            config = AI_MODELS["vision"]
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
            config = AI_MODELS["text"]
            messages = [{"role": "user", "content": prompt}]
        
        async with httpx.AsyncClient(timeout=120.0) as client:
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

