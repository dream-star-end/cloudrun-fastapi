"""
错题本 API 路由

目标：替代云函数 studyCoachFunctions/modules/mistake.js
提供给小程序的错题本 CRUD + 复习生成能力。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request

from ..db.wxcloud import MistakeRepository, get_db
from ..services.ai_service import AIService


router = APIRouter(prefix="/api/mistakes", tags=["错题本"])


# ==================== helpers ====================


def _get_openid_from_request(request: Request) -> str:
    openid = request.headers.get("x-wx-openid") or request.headers.get("X-WX-OPENID")
    if not openid:
        raise HTTPException(
            status_code=401,
            detail="缺少用户身份（X-WX-OPENID），请使用 wx.cloud.callContainer 内网调用",
        )
    return openid


CATEGORY_NAMES = {
    "math": "数学",
    "english": "英语",
    "physics": "物理",
    "chemistry": "化学",
    "other": "其他",
}


def _format_date_m_d(value: Any) -> str:
    dt = _parse_cloud_date(value)
    if not dt:
        return ""
    # 与云函数 shared/utils.js 的 formatDate 对齐：`${month}月${day}日`
    return f"{dt.month}月{dt.day}日"


def _parse_cloud_date(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value) / 1000.0) if float(value) > 10_000_000_000 else datetime.fromtimestamp(float(value))
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # ISO
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            pass
        # fallback
        try:
            return datetime.fromtimestamp(float(s))
        except Exception:
            return None
    if isinstance(value, dict):
        if "$date" in value:
            return _parse_cloud_date(value.get("$date"))
        if "date" in value:
            return _parse_cloud_date(value.get("date"))
        if "seconds" in value and isinstance(value["seconds"], (int, float)):
            return datetime.fromtimestamp(float(value["seconds"]))
        if "_seconds" in value and isinstance(value["_seconds"], (int, float)):
            return datetime.fromtimestamp(float(value["_seconds"]))
    return None


def _compute_need_review(m: Dict[str, Any]) -> bool:
    # 与云函数 computeNeedReview 对齐
    if m.get("mastered"):
        return False
    last_review_at = m.get("lastReviewAt")
    if not last_review_at:
        return True
    last = _parse_cloud_date(last_review_at)
    if not last:
        return True
    days = (datetime.now(timezone.utc) - last.replace(tzinfo=timezone.utc)).total_seconds() / (3600 * 24)
    return days >= 3


def _normalize_tags(input_value: Any) -> List[str]:
    if not input_value:
        return []
    arr = input_value if isinstance(input_value, list) else [input_value]
    out: List[str] = []
    for x in arr:
        if not isinstance(x, str):
            continue
        t = x.strip()
        if not t:
            continue
        cleaned = re.sub(r"^[,，;；、\s]+|[,，;；、\s]+$", "", t).strip()
        if not cleaned:
            continue
        out.append(cleaned[:24])
    seen = set()
    uniq: List[str] = []
    for t in out:
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(t)
    return uniq[:8]


def _extract_json_array(text: str) -> Optional[List[Any]]:
    if not text:
        return None
    s = str(text).strip()
    if not s:
        return None
    try:
        v = json.loads(s)
        if isinstance(v, list):
            return v
    except Exception:
        pass
    m = re.search(r"\[[\s\S]*\]", s)
    if m:
        try:
            v = json.loads(m.group(0))
            if isinstance(v, list):
                return v
        except Exception:
            return None
    return None


def _normalize_mistake_for_ui(m: Dict[str, Any]) -> Dict[str, Any]:
    # 兼容旧数据：旧版小程序把 answer 当“正确答案”，且没有 correctAnswer/source
    is_legacy_miniprogram = (not m.get("source")) and (not m.get("correctAnswer")) and bool(m.get("answer"))
    user_answer = "" if is_legacy_miniprogram else (m.get("answer") or "")
    correct_answer = (m.get("answer") or "") if is_legacy_miniprogram else (m.get("correctAnswer") or "")

    nm = dict(m)
    nm["categoryName"] = CATEGORY_NAMES.get(nm.get("category") or "other", "其他")
    nm["createTimeStr"] = _format_date_m_d(nm.get("createdAt"))
    nm["needReview"] = _compute_need_review(nm)
    nm["userAnswer"] = user_answer
    nm["correctAnswer"] = correct_answer
    nm["tags"] = nm.get("tags") if isinstance(nm.get("tags"), list) else []
    return nm


async def _ai_generate_tags(question: str, user_answer: str, correct_answer: str, analysis: str, openid: Optional[str] = None) -> List[str]:
    """
    使用 AI 自动生成错题标签
    
    Args:
        question: 题目内容
        user_answer: 用户答案
        correct_answer: 正确答案
        analysis: 补充说明
        openid: 用户 openid，用于获取用户配置的模型
    
    Returns:
        标签列表
    """
    prompt = (
        "你是学习教练助手。请为下面这道错题生成标签（tags）。\n"
        "要求：\n"
        '- 输出必须是严格的 JSON 数组，例如 ["一元二次方程","配方法","计算错误"]\n'
        "- 3~6 个标签\n"
        "- 标签要短（中文优先），只包含主题/知识点/技能/错误类型，不要句子，不要编号\n"
        "- 不要输出任何额外文字\n\n"
        f"题目：{question or ''}\n"
        f"我的答案：{user_answer or ''}\n"
        f"正确答案：{correct_answer or ''}\n"
        f"补充说明：{analysis or ''}"
    )

    from ..config import get_http_client_kwargs
    from ..services.model_config_service import ModelConfigService
    import httpx

    # 优先使用用户配置的模型
    mcfg = None
    if openid:
        try:
            mcfg = await ModelConfigService.get_model_for_type(openid, "text")
        except Exception:
            pass

    # 如果用户没有配置，返回空标签（不报错，静默失败）
    if not mcfg or not mcfg.get("api_key"):
        return []

    async with httpx.AsyncClient(**get_http_client_kwargs(60.0)) as client:
        resp = await client.post(
            f"{mcfg['base_url']}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {mcfg['api_key']}",
            },
            json={
                "model": mcfg["model"],
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
                "temperature": 0.2,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = ""
        if data.get("choices") and data["choices"][0].get("message"):
            content = data["choices"][0]["message"].get("content") or ""

    arr = _extract_json_array(content) or []
    return _normalize_tags(arr)


def _pick_review_candidates(mistakes: List[Dict[str, Any]], days: int = 3) -> Tuple[str, List[Dict[str, Any]]]:
    """返回 (notice, picked)"""
    threshold = datetime.now(timezone.utc) - timedelta(days=days)

    def is_due(m: Dict[str, Any]) -> bool:
        if m.get("mastered"):
            return False
        last = _parse_cloud_date(m.get("lastReviewAt"))
        if not last:
            return True
        # normalize tz
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return last <= threshold

    due = [m for m in mistakes if is_due(m)]
    notice = ""
    candidates = due
    if not candidates:
        # 巩固复习：最近未掌握
        candidates = [m for m in mistakes if not m.get("mastered")]
        candidates = candidates[:5]
        if not candidates:
            return "", []
        notice = "当前没有到期错题，已为你选取最近的题目做巩固复习。"

    # 排序：未复习优先，其次 lastReviewAt 更早优先
    def sort_key(m: Dict[str, Any]):
        last = _parse_cloud_date(m.get("lastReviewAt"))
        return (0 if last is None else 1, last.timestamp() if last else 0.0)

    candidates.sort(key=sort_key)
    picked = candidates[:5]
    return notice, picked


# ==================== APIs ====================


@router.post("/list")
async def list_mistakes(request: Request):
    """
    获取错题列表（分页 + 筛选）

    请求体（对齐云函数 getMistakes）：
    - tag: 可选，按标签筛选
    - status: all/pending/mastered
    - page: 从 0 开始
    - pageSize: 5~50
    """
    openid = _get_openid_from_request(request)
    payload = await request.json()

    tag = payload.get("tag")
    status = payload.get("status") or "all"
    page = int(payload.get("page") or 0)
    page_size = int(payload.get("pageSize") or 20)
    page = max(0, page)
    page_size = min(50, max(5, page_size))

    mastered: Optional[bool] = None
    if status == "mastered":
        mastered = True
    elif status == "pending":
        mastered = False

    db = get_db()
    repo = MistakeRepository(db)

    # 先取分页数据
    skip = page * page_size
    query: Dict[str, Any] = {"openid": openid}
    if tag and str(tag).strip():
        query["tags"] = {"$all": [str(tag).strip()]}
    if mastered is not None:
        query["mastered"] = mastered

    raw = await db.query(
        "mistakes",
        query,
        limit=page_size,
        skip=skip,
        order_by="createdAt",
        order_type="desc",
    )
    mistakes = [_normalize_mistake_for_ui(m) for m in (raw or [])]
    # needReview=true 优先（与云函数一致）
    mistakes.sort(key=lambda x: 1 if x.get("needReview") else 0, reverse=True)

    # 统计：不受筛选影响
    stats = await repo.get_stats(openid)
    total_count = int(stats.get("total") or 0)
    mastered_count = int(stats.get("mastered") or 0)
    pending_count = int(stats.get("pending") or max(0, total_count - mastered_count))

    return {
        "success": True,
        "data": {
            "mistakes": mistakes,
            "page": page,
            "pageSize": page_size,
            "hasMore": len(mistakes) == page_size,
            "stats": {"totalCount": total_count, "pendingCount": pending_count, "masteredCount": mastered_count},
        },
    }


@router.get("/stats")
async def get_mistake_stats(request: Request):
    """获取错题统计（用于首页未掌握数量展示等）"""
    openid = _get_openid_from_request(request)
    repo = MistakeRepository()
    stats = await repo.get_stats(openid)
    return {
        "success": True,
        "data": {
            "totalCount": int(stats.get("total") or 0),
            "pendingCount": int(stats.get("pending") or 0),
            "masteredCount": int(stats.get("mastered") or 0),
            "byTag": stats.get("byTag") or {},
        },
    }


@router.post("/add")
async def add_mistake(request: Request):
    """添加错题（失败不影响主流程：AI 自动打标签）"""
    openid = _get_openid_from_request(request)
    payload = await request.json()

    question = (payload.get("question") or "").strip()
    if not question:
        return {"success": False, "error": "题目不能为空"}

    user_answer = payload.get("userAnswer")
    if user_answer is None:
        user_answer = payload.get("answer") or ""
    correct_answer = payload.get("correctAnswer") or ""
    analysis = payload.get("analysis") or ""
    image_url = payload.get("imageUrl") or ""
    tags_manual = _normalize_tags(payload.get("tags") or [])

    repo = MistakeRepository()
    mistake_id = await repo.add_mistake(
        openid,
        {
            "question": question,
            "answer": str(user_answer or ""),
            "correctAnswer": str(correct_answer or ""),
            "category": payload.get("category") or "other",
            "analysis": str(analysis or ""),
            "imageUrl": str(image_url or ""),
            "tags": tags_manual,
            "source": "miniprogram",
            "aiAnalysis": "",
            "mastered": False,
            "reviewCount": 0,
            "lastReviewAt": None,
        },
    )

    # AI 自动打标签（失败不影响主流程）
    try:
        ai_tags = await _ai_generate_tags(question, str(user_answer or ""), str(correct_answer or ""), str(analysis or ""), openid=openid)
        merged = _normalize_tags([*(tags_manual or []), *(ai_tags or [])])
        if merged:
            db = get_db()
            updated = await db.update("mistakes", {"_id": mistake_id, "openid": openid}, {"tags": merged, "updatedAt": {"$date": datetime.now().isoformat()}})
            # updated may be int / bool depending backend; ignore
            _ = updated
    except Exception:
        # 静默失败
        pass

    return {"success": True, "data": {"mistakeId": mistake_id}}


@router.post("/update")
async def update_mistake(request: Request):
    """更新错题（白名单字段）"""
    openid = _get_openid_from_request(request)
    payload = await request.json()

    mistake_id = payload.get("mistakeId") or payload.get("mistake_id") or payload.get("id")
    if not mistake_id:
        return {"success": False, "error": "缺少 mistakeId"}

    allowed_fields = {
        "question",
        "answer",  # 我的答案（兼容）
        "userAnswer",  # 写入 answer
        "correctAnswer",
        "category",
        "analysis",
        "aiAnalysis",
        "imageUrl",
        "tags",
        "mastered",
    }
    update_data: Dict[str, Any] = {}
    for k in allowed_fields:
        if k in payload and payload[k] is not None:
            if k == "userAnswer":
                update_data["answer"] = str(payload.get(k) or "")
            elif k == "tags":
                update_data["tags"] = _normalize_tags(payload.get(k))
            else:
                update_data[k] = payload.get(k)

    db = get_db()

    # 复习 +1：需要先读出当前 reviewCount（db proxy 未实现 $inc）
    if payload.get("incReview") is True:
        doc = await db.get_one("mistakes", {"_id": str(mistake_id), "openid": openid})
        if not doc:
            return {"success": False, "error": "记录不存在或无权限"}
        current = int(doc.get("reviewCount") or 0)
        update_data["reviewCount"] = current + 1
        update_data["lastReviewAt"] = {"$date": datetime.now().isoformat()}

    if payload.get("mastered") is True:
        update_data["masteredAt"] = {"$date": datetime.now().isoformat()}

    update_data["updatedAt"] = {"$date": datetime.now().isoformat()}

    updated = await db.update("mistakes", {"_id": str(mistake_id), "openid": openid}, update_data)
    # db proxy returns updated count (int); wxcloud returns int too
    if isinstance(updated, bool):
        ok = bool(updated)
    else:
        ok = int(updated or 0) > 0

    if not ok:
        return {"success": False, "error": "记录不存在或无权限"}
    return {"success": True}


@router.post("/delete")
async def delete_mistake(request: Request):
    openid = _get_openid_from_request(request)
    payload = await request.json()
    mistake_id = payload.get("mistakeId") or payload.get("mistake_id") or payload.get("id")
    if not mistake_id:
        return {"success": False, "error": "缺少 mistakeId"}

    db = get_db()
    deleted = await db.delete("mistakes", {"_id": str(mistake_id), "openid": openid})
    if int(deleted or 0) <= 0:
        return {"success": False, "error": "记录不存在或无权限"}
    return {"success": True}


@router.post("/review")
async def generate_mistake_review(request: Request):
    """生成错题复习题目（对齐云函数 generateMistakeReview）"""
    openid = _get_openid_from_request(request)
    db = get_db()
    # 拉取最近未掌握优先（足够做本地筛选）
    raw = await db.query(
        "mistakes",
        {"openid": openid},
        limit=50,
        skip=0,
        order_by="createdAt",
        order_type="desc",
    )
    notice, picked = _pick_review_candidates(raw or [], days=3)
    if not picked:
        return {"success": False, "error": "暂无待复习的错题"}
    questions = "\n\n".join([f"{i+1}. {(m.get('question') or '').strip()}" for i, m in enumerate(picked)]).strip()
    return {"success": True, "data": {"questions": questions, "notice": notice}}


