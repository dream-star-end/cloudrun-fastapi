"""
学习计划生成服务
使用 AI 生成个性化学习计划和每日任务
"""
import json
import re
from typing import Dict, List, Optional
from .ai_service import AIService


class PlanService:
    """学习计划服务类"""

    @classmethod
    def _infer_goal_type(cls, goal: str, domain: str = "") -> str:
        """
        推断目标类型：exam/skill/project/other
        - exam: 考试、证书、刷题导向
        - project: 项目交付、作品集、上线导向
        - skill: 技能提升（默认）
        """
        text = f"{goal or ''} {domain or ''}".lower()
        exam_kw = ["考试", "考研", "雅思", "托福", "cet", "四级", "六级", "证书", "资格", "真题", "刷题", "面试"]
        project_kw = ["项目", "作品", "上线", "交付", "需求", "产品", "demo", "portfolio", "开源"]
        if any(k in text for k in project_kw):
            return "project"
        if any(k in text for k in exam_kw):
            return "exam"
        return "skill"

    @classmethod
    def _normalize_preferences(cls, preferences: Optional[Dict], goal: str, domain: str) -> Dict:
        """
        统一偏好字段命名，允许前端/不同版本以多种 key 传入。
        返回：
        - goal_type: exam/skill/project/other
        - weekly_days: 1-7
        - modality: video/reading/practice/mixed
        - intensity: low/medium/high (节奏强度)
        - time_slots: 可选，用户偏好的时间段描述
        """
        preferences = preferences or {}
        if not isinstance(preferences, dict):
            return {
                "goal_type": cls._infer_goal_type(goal, domain),
                "weekly_days": 6,
                "modality": "mixed",
                "intensity": "medium",
            }

        goal_type = (
            preferences.get("goal_type")
            or preferences.get("goalType")
            or preferences.get("targetType")
            or preferences.get("target_type")
        )
        goal_type = str(goal_type).strip().lower() if goal_type else ""
        if goal_type not in ["exam", "skill", "project", "other"]:
            goal_type = cls._infer_goal_type(goal, domain)

        weekly_days = preferences.get("weekly_days") or preferences.get("weeklyDays") or preferences.get("days_per_week")
        try:
            weekly_days = int(weekly_days) if weekly_days is not None else 6
        except Exception:
            weekly_days = 6
        weekly_days = max(1, min(7, weekly_days))

        modality = preferences.get("modality") or preferences.get("modalityPreference") or preferences.get("learningModality")
        modality = str(modality).strip().lower() if modality else "mixed"
        if modality not in ["video", "reading", "practice", "mixed"]:
            modality = "mixed"

        intensity = preferences.get("intensity") or preferences.get("pace") or preferences.get("rhythm")
        intensity = str(intensity).strip().lower() if intensity else "medium"
        if intensity not in ["low", "medium", "high"]:
            intensity = "medium"

        time_slots = preferences.get("time_slots") or preferences.get("timeSlots") or preferences.get("availableTimeSlots")
        time_slots = time_slots if isinstance(time_slots, (list, str, dict)) else None

        return {
            "goal_type": goal_type,
            "weekly_days": weekly_days,
            "modality": modality,
            "intensity": intensity,
            "time_slots": time_slots,
            **preferences,  # 保留其它自定义字段，便于后续扩展
        }
    
    @classmethod
    async def generate_study_plan(
        cls,
        goal: str,
        domain: str,
        daily_hours: float = 2,
        deadline: Optional[str] = None,
        current_level: str = "beginner",
        preferences: Optional[Dict] = None,
        openid: Optional[str] = None,
    ) -> Dict:
        """
        生成学习计划
        
        Args:
            goal: 学习目标
            domain: 学习领域
            daily_hours: 每日学习时长
            deadline: 目标截止日期
            current_level: 当前水平
            preferences: 学习偏好
            openid: 用户 openid，用于获取用户配置的模型
        
        Returns:
            学习计划字典
        """
        import logging
        import asyncio
        logger = logging.getLogger(__name__)
        
        logger.info(f"[PlanService] 开始生成计划: goal={goal[:50] if goal else ''}, domain={domain}")
        
        prompt = cls._build_plan_prompt(
            goal, domain, daily_hours, deadline, current_level, preferences
        )
        
        messages = [{"role": "user", "content": prompt}]
        
        try:
            logger.info("[PlanService] 调用 AI 服务...")
            
            # 设置 50 秒超时，留出余量给微信云托管（默认 60 秒）
            response = await asyncio.wait_for(
                AIService.chat(
                    messages=messages,
                    model_type="text",
                    temperature=0.7,
                    max_tokens=4000,
                    openid=openid,
                ),
                timeout=50.0
            )
            
            logger.info(f"[PlanService] AI 响应长度: {len(response) if response else 0}")
            
            # 解析 JSON
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                try:
                    plan = json.loads(json_match.group())
                    logger.info(f"[PlanService] 计划解析成功, phases数量: {len(plan.get('phases', []))}")
                    return {"success": True, "plan": plan}
                except json.JSONDecodeError as je:
                    logger.error(f"[PlanService] JSON 解析失败: {je}")
                    logger.error(f"[PlanService] 原始响应: {response[:500] if response else 'None'}...")
                    return {"success": False, "error": f"JSON解析失败: {str(je)}"}
            
            logger.error(f"[PlanService] AI 响应中未找到 JSON 格式数据")
            logger.error(f"[PlanService] 原始响应: {response[:500] if response else 'None'}...")
            return {"success": False, "error": "计划生成格式错误，AI未返回有效JSON"}
        
        except asyncio.TimeoutError:
            logger.error("[PlanService] AI 调用超时 (50秒)")
            return {"success": False, "error": "AI 生成超时，请稍后重试"}
            
        except Exception as e:
            logger.error(f"[PlanService] 生成计划异常: {type(e).__name__}: {str(e)}", exc_info=True)
            return {"success": False, "error": f"生成失败: {str(e)}"}
    
    @classmethod
    async def generate_daily_tasks(
        cls,
        domain: str,
        daily_hours: float,
        current_phase: Optional[Dict] = None,
        learning_history: Optional[Dict] = None,
        today_stats: Optional[Dict] = None,
        learning_context: Optional[Dict] = None,
        openid: Optional[str] = None,
    ) -> List[Dict]:
        """
        生成每日学习任务（非流式）
        
        Args:
            domain: 学习领域
            daily_hours: 每日学习时长
            current_phase: 当前学习阶段
            learning_history: 学习历史统计
            today_stats: 今日任务统计
            openid: 用户 openid，用于获取用户配置的模型
        
        Returns:
            任务列表
        """
        prompt = cls._build_task_prompt(
            domain, daily_hours, current_phase, learning_history, today_stats, learning_context
        )
        
        messages = [{"role": "user", "content": prompt}]
        
        try:
            response = await AIService.chat(
                messages=messages,
                model_type="text",
                temperature=0.7,
                max_tokens=2000,
                openid=openid,
            )
            
            # 解析 JSON 数组
            json_match = re.search(r'\[[\s\S]*\]', response)
            if json_match:
                tasks = json.loads(json_match.group())
                return cls._validate_tasks(tasks, daily_hours)
            
            # 如果 AI 生成失败，返回默认任务
            return cls._get_default_tasks(domain, daily_hours)
            
        except Exception as e:
            print(f"生成任务失败: {e}")
            return cls._get_default_tasks(domain, daily_hours)
    
    @classmethod
    async def generate_daily_tasks_stream(
        cls,
        domain: str,
        daily_hours: float,
        current_phase: Optional[Dict] = None,
        learning_history: Optional[Dict] = None,
        today_stats: Optional[Dict] = None,
        learning_context: Optional[Dict] = None,
        openid: Optional[str] = None,
    ):
        """
        生成每日学习任务（流式）
        
        Args:
            openid: 用户 openid，用于获取用户配置的模型
        
        Yields:
            AI 响应内容片段
        """
        prompt = cls._build_task_prompt(
            domain, daily_hours, current_phase, learning_history, today_stats, learning_context
        )
        
        messages = [{"role": "user", "content": prompt}]
        
        async for chunk in AIService.chat_stream(
            messages=messages,
            model_type="text",
            temperature=0.7,
            max_tokens=2000,
            openid=openid,
        ):
            yield chunk

    @classmethod
    def generate_daily_tasks_fast(
        cls,
        domain: str,
        daily_hours: float,
        current_phase: Optional[Dict] = None,
        learning_history: Optional[Dict] = None,
        today_stats: Optional[Dict] = None,
        learning_context: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        快速生成每日任务（无 AI、毫秒级），用于提升用户感知：
        - 任务围绕学习领域/阶段目标/已学进度（最近完成率、昨日未完成、错题待复习）生成
        - 返回结构与 AI 版一致
        """
        total_minutes = max(20, int(float(daily_hours) * 60))
        learning_context = learning_context or {}

        # 基于时长决定任务数
        if total_minutes <= 60:
            task_count = 3
        elif total_minutes <= 120:
            task_count = 4
        elif total_minutes <= 180:
            task_count = 5
        else:
            task_count = 6

        # 基于完成率调节任务量
        completion_rate = 0
        if learning_history and isinstance(learning_history, dict):
            completion_rate = int(learning_history.get("avgCompletionRate") or 0)
        if today_stats and isinstance(today_stats, dict):
            # 昨日统计/今日统计都可能传进来，取更低的作为保守参考
            completion_rate = min(completion_rate or 100, int(today_stats.get("completionRate") or 0))
        if completion_rate and completion_rate < 50 and task_count > 3:
            task_count -= 1

        # 抽取阶段信息
        phase_name = (current_phase or {}).get("name") or ""
        phase_goals = (current_phase or {}).get("goals") or (current_phase or {}).get("objectives") or []
        key_points = (
            (current_phase or {}).get("keyPoints")
            or (current_phase or {}).get("key_points")
            or (current_phase or {}).get("key_tasks")
            or []
        )
        if isinstance(phase_goals, str):
            phase_goals = [phase_goals]
        if isinstance(key_points, str):
            key_points = [key_points]

        # 最近未完成任务（用于“续做”）
        carry = learning_context.get("carryover") or {}
        carry_titles = carry.get("uncompletedTitles") or []
        if isinstance(carry_titles, str):
            carry_titles = [carry_titles]
        carry_titles = [t for t in carry_titles if t][:3]

        # 错题待复习
        mistakes = learning_context.get("mistakes") or []
        mistake_titles = []
        for m in mistakes[:3]:
            if isinstance(m, dict):
                title = m.get("topic") or m.get("question") or m.get("title") or ""
                if title:
                    mistake_titles.append(str(title)[:30])

        # 选 2-3 个本阶段主题
        topics = []
        for x in (key_points or []) + (phase_goals or []):
            s = str(x).strip()
            if s and s not in topics:
                topics.append(s)
        topics = topics[: max(1, min(3, task_count - 1))]
        if not topics:
            topics = [domain or "核心内容"]

        # 分配时长比例
        ratios = [0.15, 0.35, 0.35, 0.15] if task_count <= 4 else [0.12, 0.28, 0.28, 0.2, 0.12]
        ratios = ratios[:task_count]
        total_ratio = sum(ratios) or 1.0
        durations = [max(10, int(total_minutes * r / total_ratio)) for r in ratios]
        # 纠偏：总和可能不等于 total_minutes
        diff = total_minutes - sum(durations)
        if durations:
            durations[0] = max(10, durations[0] + diff)

        tasks: List[Dict] = []

        # 1) 续做/复盘优先
        if carry_titles:
            tasks.append(
                {
                    "title": "✅ 续做昨日未完成",
                    "description": f"优先完成昨日未完成任务：{'; '.join(carry_titles)}。完成后在任务里勾选并补充一句总结。",
                    "duration": durations[len(tasks)] if len(tasks) < len(durations) else 25,
                    "priority": "high",
                    "type": "review",
                }
            )
        elif mistake_titles:
            tasks.append(
                {
                    "title": "🔁 错题复盘",
                    "description": f"复盘近期错题：{'; '.join(mistake_titles)}。每题写出错误原因 + 正确解法 + 1条避免再错的规则。",
                    "duration": durations[len(tasks)] if len(tasks) < len(durations) else 25,
                    "priority": "high",
                    "type": "review",
                }
            )

        # 2) 学习 + 练习围绕阶段主题
        topic_idx = 0
        while len(tasks) < max(1, task_count - 1):
            topic = topics[topic_idx % len(topics)]
            topic_idx += 1
            is_learn = (len(tasks) % 2 == 0)
            if is_learn:
                tasks.append(
                    {
                        "title": f"📖 学习：{topic}",
                        "description": f"围绕「{topic}」学习并做笔记（至少3条要点+1个例子）。如有资料，优先按阶段资源/官方文档。",
                        "duration": durations[len(tasks)] if len(tasks) < len(durations) else 30,
                        "priority": "high",
                        "type": "learn",
                    }
                )
            else:
                tasks.append(
                    {
                        "title": f"✍️ 练习：{topic}",
                        "description": f"围绕「{topic}」做针对性练习：完成3-5个小题/1个小练习，并把错因记录到错题本。",
                        "duration": durations[len(tasks)] if len(tasks) < len(durations) else 30,
                        "priority": "high",
                        "type": "practice",
                    }
                )

        # 3) 总结收尾
        tasks.append(
            {
                "title": "📝 今日总结",
                "description": f"用5分钟总结今天学到的3点（{phase_name+'：' if phase_name else ''}{', '.join(topics[:2])}），并列出明天要继续的1件事。",
                "duration": durations[len(tasks)] if len(tasks) < len(durations) else 15,
                "priority": "medium",
                "type": "review",
            }
        )

        tasks = tasks[:task_count]
        return cls._validate_tasks(tasks, daily_hours)
    
    @classmethod
    def _build_phase_detail_prompt(
        cls,
        phase_name: str,
        phase_goals: List[str],
        domain: str,
        duration: str,
    ) -> str:
        """构建阶段详情生成提示词"""
        goals_text = chr(10).join(['- ' + g for g in phase_goals]) if phase_goals else "- 完成本阶段学习"
        
        return f"""请为以下学习阶段生成详细的学习内容。

【阶段名称】{phase_name}
【学习领域】{domain}
【阶段时长】{duration}
【阶段目标】
{goals_text}

要求：
1. 只返回一个有效的JSON对象，不要包含任何其他文字
2. JSON必须是完整的，确保所有括号正确闭合
3. 字符串中不要包含未转义的特殊字符

JSON格式如下：
```json
{{
    "key_points": ["知识点1", "知识点2", "知识点3"],
    "learning_resources": [
        {{"type": "video", "name": "资源名称"}},
        {{"type": "book", "name": "资源名称"}}
    ],
    "practice_suggestions": ["练习建议1", "练习建议2"],
    "milestones": [
        {{"week": 1, "goal": "目标描述"}}
    ],
    "tips": ["学习小贴士"]
}}
```

请生成3-5个key_points，2-3个learning_resources，2-3个practice_suggestions。
直接输出JSON，不要有任何前缀或后缀文字。"""

    @classmethod
    async def generate_phase_detail(
        cls,
        phase_name: str,
        phase_goals: List[str],
        domain: str,
        duration: str,
        openid: Optional[str] = None,
    ) -> Dict:
        """
        生成学习阶段的详细内容（使用 JSON 模式，更可靠）
        
        Args:
            phase_name: 阶段名称
            phase_goals: 阶段目标
            domain: 学习领域
            duration: 阶段时长
            openid: 用户 openid，用于获取用户配置的模型
        
        Returns:
            阶段详情字典
        """
        import logging
        logger = logging.getLogger(__name__)
        
        prompt = cls._build_phase_detail_prompt(phase_name, phase_goals, domain, duration)
        messages = [{"role": "user", "content": prompt}]
        
        try:
            # 使用 JSON 模式，超时设为 180 秒
            detail = await AIService.chat_json(
                messages=messages,
                model_type="text",
                temperature=0.5,  # JSON 模式用较低温度更稳定
                max_tokens=2000,
                timeout=180.0,
                openid=openid,
            )
            
            logger.info(f"[PlanService] 阶段详情生成成功: {phase_name}")
            return {"success": True, "detail": detail}
            
        except Exception as e:
            logger.error(f"[PlanService] 阶段详情生成失败: {e}")
            return {"success": False, "error": str(e)}
    
    @classmethod
    def _build_plan_prompt(
        cls,
        goal: str,
        domain: str,
        daily_hours: float,
        deadline: Optional[str],
        current_level: str,
        preferences: Optional[Dict],
    ) -> str:
        """构建学习计划生成提示词"""
        from datetime import datetime, timezone, timedelta
        
        prefs = cls._normalize_preferences(preferences, goal, domain)
        goal_type = prefs.get("goal_type", "skill")
        weekly_days = prefs.get("weekly_days", 6)
        modality = prefs.get("modality", "mixed")
        intensity = prefs.get("intensity", "medium")
        time_slots = prefs.get("time_slots")
        
        # 获取当前北京时间
        now_utc = datetime.now(timezone.utc)
        beijing_now = now_utc + timedelta(hours=8)
        current_date_str = beijing_now.strftime("%Y年%m月%d日")

        level_desc = {
            "beginner": "零基础/入门",
            "intermediate": "有一定基础/中级",
            "advanced": "基础扎实/进阶",
        }

        goal_type_desc = {
            "exam": "考试/刷题/证书导向（强调真题、错题闭环、稳定性）",
            "skill": "技能提升导向（强调可迁移能力、结构化知识体系）",
            "project": "项目/作品导向（强调可交付产出、里程碑、迭代）",
            "other": "通用学习导向",
        }

        modality_desc = {
            "video": "偏好视频/课程（需要拆成短视频块 + 关键笔记）",
            "reading": "偏好阅读/文档（需要精读+要点提炼）",
            "practice": "偏好练习/动手（需要更多题目/编码/实验）",
            "mixed": "混合偏好（学习/练习/复盘均衡）",
        }

        intensity_desc = {
            "low": "低强度（更轻松、更可持续，避免挫败）",
            "medium": "中等强度（稳定推进，留出缓冲）",
            "high": "高强度（更紧凑，强调挑战与反馈）",
        }

        prompt = f"""你是一位资深的学习规划师，请根据以下信息制定一份详细的学习计划：

【当前日期】{current_date_str}（计划从今天开始执行）
【学习目标】{goal}
【学习领域】{domain}
【当前水平】{level_desc.get(current_level, current_level)}
【每日可用时间】{daily_hours}小时
【每周学习天数】{weekly_days}天
{"【目标截止日期】" + deadline if deadline else ""}
【目标类型】{goal_type_desc.get(goal_type, goal_type)}
【偏好媒介】{modality_desc.get(modality, modality)}
【节奏强度】{intensity_desc.get(intensity, intensity)}
{"【可用时间段】" + (json.dumps(time_slots, ensure_ascii=False) if not isinstance(time_slots, str) else time_slots) if time_slots else ""}

请返回JSON格式的学习计划（只返回JSON）。并在计划中体现“个性化强度与节奏”：
- 如果【目标类型】是考试：练习/复盘占比更高，包含错题闭环与阶段测验；强调“稳定性”
- 如果【目标类型】是项目：每阶段要有可交付物（Demo/功能点），每周要有里程碑
- 如果【偏好媒介】是视频：把学习拆成“观看-笔记-复述-练习”的闭环，并给出短任务
- 如果【节奏强度】较低：单日任务更少、更容易完成；强度较高：挑战更大但要有恢复任务

输出里可以额外包含字段（如 intensity/cadence/modalityPlan），但必须至少包含以下字段：
{{
    "goal": "学习目标",
    "domain": "学习领域",
    "total_duration": "总时长，必须从当前日期开始计算（如：约3个月，从{current_date_str}至xxxx年xx月）",
    "phases": [
        {{
            "name": "阶段名称（如：基础入门）",
            "duration": "阶段时长（如：2周）",
            "goals": ["阶段目标1", "阶段目标2"],
            "key_points": ["重点1", "重点2", "重点3"]
        }}
    ],
    "daily_schedule": [
        {{
            "time_slot": "时间段",
            "activity": "活动内容",
            "duration_minutes": 30
        }}
    ],
    "tips": ["学习建议1", "建议2", "建议3"]
}}

要求：
1. 阶段划分合理，循序渐进
2. 每个阶段有明确可衡量的目标
3. 考虑用户的时间限制
4. 提供实用的学习建议
5. 计划要“可执行”，避免空泛描述；尽量给出量化指标（页数/题数/时长/产出）"""

        return prompt
    
    @classmethod
    def _build_task_prompt(
        cls,
        domain: str,
        daily_hours: float,
        current_phase: Optional[Dict],
        learning_history: Optional[Dict],
        today_stats: Optional[Dict],
        learning_context: Optional[Dict],
    ) -> str:
        """构建每日任务生成提示词"""
        total_minutes = int(daily_hours * 60)

        learning_context = learning_context or {}

        # 个性化偏好（来自学习计划/前端传入）
        prefs = cls._normalize_preferences(learning_context.get("preferences"), goal="", domain=str(domain))
        modality = prefs.get("modality", "mixed")
        intensity = prefs.get("intensity", "medium")
        goal_type = prefs.get("goal_type", "skill")

        pace_hint = ""
        pace = learning_context.get("pace") or {}
        if isinstance(pace, dict):
            if pace.get("missedDays"):
                pace_hint += f"最近缺勤 {pace.get('missedDays')} 天，今天需要更可持续的安排；"
            if pace.get("highCompletionStreak"):
                pace_hint += f"近期连续高完成（{pace.get('highCompletionStreak')} 天），可以适当提高挑战；"
            if pace.get("carryoverMinutes"):
                pace_hint += f"有待补做任务约 {pace.get('carryoverMinutes')} 分钟，需优先安排；"
        
        # 分析学习状态
        state_analysis = ""
        if learning_history:
            avg_rate = learning_history.get("avgCompletionRate", 0)
            if avg_rate >= 80:
                state_analysis = "学习状态良好，可适当增加挑战"
            elif avg_rate >= 50:
                state_analysis = "学习状态一般，保持当前难度"
            else:
                state_analysis = "建议减少任务量或降低难度"
        
        # 今日表现分析
        today_analysis = ""
        if today_stats:
            rate = today_stats.get("completionRate", 0)
            if rate >= 80:
                today_analysis = "今日表现优秀"
            elif rate >= 50:
                today_analysis = "今日完成一半以上"
            else:
                today_analysis = "今日完成率较低"
        
        phase_name = current_phase.get("name", "") if current_phase else ""
        phase_goals = current_phase.get("goals", []) if current_phase else []
        phase_goals_str = ", ".join(phase_goals) if phase_goals else ""

        # 结合“已学内容/进度”：最近未完成、错题待复盘等
        context_str = ""
        if learning_context and isinstance(learning_context, dict):
            carry = learning_context.get("carryover") or {}
            uncompleted = carry.get("uncompletedTitles") or []
            if isinstance(uncompleted, list) and uncompleted:
                context_str += "【昨日未完成】" + "；".join([str(x)[:40] for x in uncompleted[:3]]) + "\n"
            mistakes = learning_context.get("mistakes") or []
            if isinstance(mistakes, list) and mistakes:
                ms = []
                for m in mistakes[:3]:
                    if isinstance(m, dict):
                        ms.append(str(m.get("topic") or m.get("question") or "")[:40])
                ms = [x for x in ms if x]
                if ms:
                    context_str += "【待复盘错题】" + "；".join(ms) + "\n"

        prompt = f"""你是一位专业的学习规划师，请根据以下信息生成【今天】的学习任务（与日历日期绑定）：

【学习领域】{domain}
【每日学习时长】{daily_hours}小时（{total_minutes}分钟）
{"【当前阶段】" + phase_name if phase_name else ""}
{"【阶段目标】" + phase_goals_str if phase_goals_str else ""}
{"【学习状态】" + state_analysis if state_analysis else ""}
{"【今日表现】" + today_analysis if today_analysis else ""}
{"【节奏提示】" + pace_hint if pace_hint else ""}
【个性化偏好】目标类型={goal_type}；媒介偏好={modality}；节奏强度={intensity}
{context_str if context_str else ""}

【核心要求】
1. ⚠️ **任务内容必须严格围绕【学习领域】和【阶段目标】展开。严禁生成与该领域无关的任务（例如：如果领域不是英语，绝不要生成背单词、练听力等任务）。**
2. 每个任务必须具体可执行，明确指出：学什么、学多少、怎么学
3. 避免模糊描述，如"复习知识点"应改为"复习第3章牛顿运动定律，完成课后习题1-10题"
4. 任务描述包含具体数量指标
5. 总时长约{total_minutes}分钟
6. 高强度和轻松任务穿插
7. 按偏好调整结构：
   - video：任务中包含“观看+笔记+复述+小练习”
   - reading：任务中包含“精读+要点提炼+回忆复述”
   - practice：任务中练习占比更高，并包含错题/复盘
8. 按节奏强度调整：
   - low：优先可完成、少而精；减少任务数或难度
   - high：提高练习/挑战，加入小测验，但保留恢复/总结

【任务描述示例】
- ❌ 差："复习英语单词"
- ✅ 好（英语领域）："使用艾宾浩斯记忆法复习Unit3的50个核心词汇，要求能拼写并造句"
- ✅ 好（编程领域）："阅读React官方文档关于Hooks的章节，并手写一个useEffect的计数器Demo"
- ✅ 好（考试领域）："完成《系统架构设计师教程》第4章的课后习题，重点复习软件工程模型部分"

请返回JSON数组格式（只返回JSON）：
[
    {{
        "title": "简洁任务标题（带emoji，不超过15字）",
        "description": "详细具体的任务描述（40-80字）",
        "duration": 分钟数,
        "priority": "high/medium/low",
        "type": "review/learn/practice/rest"
    }}
]"""

        return prompt
    
    @classmethod
    def _validate_tasks(cls, tasks: List[Dict], daily_hours: float) -> List[Dict]:
        """验证和规范化任务"""
        validated = []
        for i, task in enumerate(tasks):
            validated.append({
                "title": task.get("title", f"任务{i+1}"),
                "description": task.get("description", task.get("title", "")),
                "duration": min(task.get("duration", 30), 120),  # 单个任务不超过2小时
                "priority": task.get("priority", "medium") if task.get("priority") in ["high", "medium", "low"] else "medium",
                "type": task.get("type", "learn"),
            })
        
        return validated
    
    @classmethod
    def _get_default_tasks(cls, domain: str, daily_hours: float) -> List[Dict]:
        """获取默认任务模板"""
        total_minutes = int(daily_hours * 60)
        
        templates = {
            "考研": [
                {"title": "🌅 晨间复习", "desc": "使用艾宾浩斯记忆法复习昨日专业课核心概念，完成10道自测题", "ratio": 0.1, "priority": "high", "type": "review"},
                {"title": "📖 专业课精读", "desc": "阅读教材新章节30页，标注重点并制作思维导图", "ratio": 0.35, "priority": "high", "type": "learn"},
                {"title": "🔢 数学限时训练", "desc": "完成高数/线代练习题15道，限时45分钟，错题记录", "ratio": 0.25, "priority": "high", "type": "practice"},
                {"title": "🇬🇧 英语强化", "desc": "完成1篇阅读理解真题，背诵40个考研核心词汇", "ratio": 0.2, "priority": "medium", "type": "learn"},
                {"title": "📝 今日总结", "desc": "整理今日学习笔记，列出待解决问题", "ratio": 0.1, "priority": "medium", "type": "review"},
            ],
            "英语学习": [
                {"title": "🌅 词汇攻关", "desc": "学习50个新词，复习昨日词汇并自测", "ratio": 0.15, "priority": "high", "type": "learn"},
                {"title": "👂 听力精听", "desc": "精听5分钟音频，逐句跟读3遍", "ratio": 0.25, "priority": "high", "type": "practice"},
                {"title": "📖 阅读精析", "desc": "精读1篇500词文章，分析长难句", "ratio": 0.3, "priority": "high", "type": "learn"},
                {"title": "✍️ 写作/口语", "desc": "完成150词短文或15分钟口语练习", "ratio": 0.2, "priority": "medium", "type": "practice"},
                {"title": "📝 复习巩固", "desc": "复习今日所有生词，用新词造5个句子", "ratio": 0.1, "priority": "medium", "type": "review"},
            ],
            "编程技术": [
                {"title": "📖 技术文档", "desc": "阅读官方文档30分钟，学习1个新API", "ratio": 0.25, "priority": "high", "type": "learn"},
                {"title": "💻 算法练习", "desc": "完成LeetCode 3道题（1简单+2中等）", "ratio": 0.35, "priority": "high", "type": "practice"},
                {"title": "🚀 项目实战", "desc": "推进个人项目，完成1个功能模块", "ratio": 0.25, "priority": "high", "type": "practice"},
                {"title": "📝 代码Review", "desc": "回顾今日代码，优化并补充注释", "ratio": 0.15, "priority": "medium", "type": "review"},
            ],
        }
        
        # 获取对应领域的模板，如果没有则使用通用模板
        task_templates = templates.get(domain, [
            {"title": "🌅 晨间复习", "desc": "回顾昨日学习的核心知识点", "ratio": 0.1, "priority": "high", "type": "review"},
            {"title": "📖 核心学习", "desc": "学习新章节内容，标注重点并制作笔记", "ratio": 0.4, "priority": "high", "type": "learn"},
            {"title": "✏️ 实战练习", "desc": "完成与今日学习内容相关的练习题", "ratio": 0.3, "priority": "high", "type": "practice"},
            {"title": "🔍 查漏补缺", "desc": "针对错题和疑问进行专项突破", "ratio": 0.1, "priority": "medium", "type": "review"},
            {"title": "📝 今日总结", "desc": "整理笔记，列出明日学习计划", "ratio": 0.1, "priority": "medium", "type": "review"},
        ])
        
        # 计算每个任务的时长
        total_ratio = sum(t["ratio"] for t in task_templates)
        
        return [
            {
                "title": t["title"],
                "description": t["desc"],
                "duration": int((t["ratio"] / total_ratio) * total_minutes),
                "priority": t["priority"],
                "type": t["type"],
            }
            for t in task_templates
        ]

