"""
微信云开发数据库访问层
支持云托管内网直连云开发数据库

在微信云托管环境中，可以通过内网 HTTP API 访问云开发数据库
文档: https://developers.weixin.qq.com/miniprogram/dev/wxcloud/guide/database/http-api.html
"""

import os
import json
import httpx
from typing import Optional, List, Dict, Any
from datetime import datetime

from ..config import settings


class WxCloudDB:
    """
    微信云开发数据库客户端
    
    在云托管环境中使用内网访问，无需 access_token
    通过环境变量自动获取配置
    """
    
    def __init__(self, env_id: Optional[str] = None):
        """
        初始化数据库客户端
        
        Args:
            env_id: 云环境ID，如果不提供则从环境变量获取
        """
        # 云环境ID
        self.env_id = env_id or os.environ.get('TCB_ENV', 'prod-3gvp927wbf0bbf20')
        
        # 内网访问地址（云托管环境中可用）
        # 格式: https://api.weixin.qq.com/tcb/
        self.base_url = "https://api.weixin.qq.com/tcb"
        
        # 是否在云托管环境中（有内网访问能力）
        self.is_cloudrun = os.environ.get('TCB_CONTEXT_KEYS') is not None
        
        # HTTP 客户端
        self._client: Optional[httpx.AsyncClient] = None
        
        # access_token（非云托管环境需要）
        self._access_token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._client is None:
            from ..config import get_http_client_kwargs
            # 使用统一的 HTTP 客户端配置
            self._client = httpx.AsyncClient(**get_http_client_kwargs(30.0))
        return self._client
    
    async def _get_access_token(self) -> str:
        """
        获取微信 API access_token
        
        使用 appid 和 secret 获取 access_token，支持缓存
        """
        # 检查缓存的 token
        if self._access_token and self._token_expires:
            if datetime.now() < self._token_expires:
                return self._access_token
        
        # 获取新 token
        client = await self._get_client()
        appid = settings.WX_APPID
        secret = settings.WX_SECRET
        
        if not appid or not secret:
            raise ValueError("需要配置 WX_APPID 和 WX_SECRET 环境变量")
        
        url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={appid}&secret={secret}"
        response = await client.get(url)
        data = response.json()
        
        if "access_token" in data:
            self._access_token = data["access_token"]
            # token 有效期2小时，提前5分钟刷新
            from datetime import timedelta
            self._token_expires = datetime.now() + timedelta(seconds=data.get("expires_in", 7200) - 300)
            return self._access_token
        else:
            raise Exception(f"获取 access_token 失败: {data}")
    
    async def _request(self, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        发送数据库请求
        
        Args:
            action: 操作类型，如 databaseQuery, databaseAdd 等
            data: 请求数据
            
        Returns:
            响应数据
        """
        client = await self._get_client()
        
        # 添加环境ID
        data["env"] = self.env_id
        
        # 构建 URL - 无论是否云托管，HTTP API 都需要 access_token
        token = await self._get_access_token()
        url = f"{self.base_url}/{action}?access_token={token}"
        
        response = await client.post(url, json=data)
        result = response.json()
        
        if result.get("errcode", 0) != 0:
            raise Exception(f"数据库操作失败: {result}")
        
        return result
    
    # ==================== 查询操作 ====================
    
    async def query(
        self,
        collection: str,
        query: Dict[str, Any],
        limit: int = 100,
        skip: int = 0,
        order_by: Optional[str] = None,
        order_type: str = "desc",
    ) -> List[Dict[str, Any]]:
        """
        查询文档
        
        Args:
            collection: 集合名称
            query: 查询条件
            limit: 返回数量限制
            skip: 跳过数量
            order_by: 排序字段
            order_type: 排序方式 asc/desc
            
        Returns:
            文档列表
        """
        # 构建查询语句
        query_str = f"db.collection('{collection}').where({json.dumps(query)})"
        
        if order_by:
            query_str += f".orderBy('{order_by}', '{order_type}')"
        
        query_str += f".skip({skip}).limit({limit}).get()"
        
        result = await self._request("databaseQuery", {"query": query_str})
        
        # 解析返回数据
        data = result.get("data", [])
        if isinstance(data, list):
            return [json.loads(item) if isinstance(item, str) else item for item in data]
        return []
    
    async def get_one(
        self,
        collection: str,
        query: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """查询单个文档"""
        results = await self.query(collection, query, limit=1)
        return results[0] if results else None
    
    async def get_by_id(
        self,
        collection: str,
        doc_id: str,
    ) -> Optional[Dict[str, Any]]:
        """根据 ID 获取文档"""
        query_str = f"db.collection('{collection}').doc('{doc_id}').get()"
        result = await self._request("databaseQuery", {"query": query_str})
        
        data = result.get("data", [])
        if data:
            item = data[0] if isinstance(data, list) else data
            return json.loads(item) if isinstance(item, str) else item
        return None
    
    async def count(
        self,
        collection: str,
        query: Dict[str, Any],
    ) -> int:
        """统计文档数量"""
        query_str = f"db.collection('{collection}').where({json.dumps(query)}).count()"
        result = await self._request("databaseQuery", {"query": query_str})
        return result.get("total", 0)
    
    # ==================== 写入操作 ====================
    
    async def add(
        self,
        collection: str,
        data: Dict[str, Any],
    ) -> str:
        """
        添加文档
        
        Args:
            collection: 集合名称
            data: 文档数据
            
        Returns:
            新文档 ID
        """
        # 添加时间戳
        if "createdAt" not in data:
            data["createdAt"] = {"$date": datetime.now().isoformat()}
        
        query_str = f"db.collection('{collection}').add({{data: {json.dumps(data, ensure_ascii=False)}}})"
        result = await self._request("databaseAdd", {"query": query_str})
        
        return result.get("id_list", [""])[0]
    
    async def update(
        self,
        collection: str,
        query: Dict[str, Any],
        data: Dict[str, Any],
    ) -> int:
        """
        更新文档
        
        Args:
            collection: 集合名称
            query: 查询条件
            data: 更新数据
            
        Returns:
            更新的文档数量
        """
        # 添加更新时间
        data["updatedAt"] = {"$date": datetime.now().isoformat()}
        
        query_str = f"db.collection('{collection}').where({json.dumps(query)}).update({{data: {json.dumps(data, ensure_ascii=False)}}})"
        result = await self._request("databaseUpdate", {"query": query_str})
        
        return result.get("modified", 0)
    
    async def update_by_id(
        self,
        collection: str,
        doc_id: str,
        data: Dict[str, Any],
    ) -> bool:
        """根据 ID 更新文档"""
        data["updatedAt"] = {"$date": datetime.now().isoformat()}
        
        query_str = f"db.collection('{collection}').doc('{doc_id}').update({{data: {json.dumps(data, ensure_ascii=False)}}})"
        result = await self._request("databaseUpdate", {"query": query_str})
        
        return result.get("modified", 0) > 0
    
    async def delete(
        self,
        collection: str,
        query: Dict[str, Any],
    ) -> int:
        """
        删除文档
        
        Args:
            collection: 集合名称
            query: 查询条件
            
        Returns:
            删除的文档数量
        """
        query_str = f"db.collection('{collection}').where({json.dumps(query)}).remove()"
        result = await self._request("databaseDelete", {"query": query_str})
        
        return result.get("deleted", 0)
    
    async def delete_by_id(
        self,
        collection: str,
        doc_id: str,
    ) -> bool:
        """根据 ID 删除文档"""
        query_str = f"db.collection('{collection}').doc('{doc_id}').remove()"
        result = await self._request("databaseDelete", {"query": query_str})
        
        return result.get("deleted", 0) > 0
    
    # ==================== 聚合操作 ====================
    
    async def aggregate(
        self,
        collection: str,
        pipeline: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        聚合查询
        
        Args:
            collection: 集合名称
            pipeline: 聚合管道
            
        Returns:
            聚合结果
        """
        # 构建聚合语句
        pipeline_str = ".".join([
            f"{list(stage.keys())[0]}({json.dumps(list(stage.values())[0])})"
            for stage in pipeline
        ])
        
        query_str = f"db.collection('{collection}').aggregate().{pipeline_str}.end()"
        result = await self._request("databaseAggregate", {"query": query_str})
        
        data = result.get("data", [])
        if isinstance(data, list):
            return [json.loads(item) if isinstance(item, str) else item for item in data]
        return []
    
    # ==================== 便捷方法 ====================
    
    async def close(self):
        """关闭客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None


# 全局数据库实例
_db_instance: Optional[WxCloudDB] = None


def get_db() -> WxCloudDB:
    """获取数据库实例（单例）"""
    global _db_instance
    if _db_instance is None:
        _db_instance = WxCloudDB()
    return _db_instance


# ==================== 业务数据访问类 ====================

class UserRepository:
    """用户数据仓库"""
    
    def __init__(self, db: Optional[WxCloudDB] = None):
        self.db = db or get_db()
    
    async def get_user(self, openid: str) -> Optional[Dict[str, Any]]:
        """获取用户信息"""
        return await self.db.get_one("users", {"openid": openid})
    
    async def get_stats(self, openid: str) -> Optional[Dict[str, Any]]:
        """获取用户统计"""
        return await self.db.get_one("user_stats", {"openid": openid})
    
    async def get_memory(self, openid: str) -> Optional[Dict[str, Any]]:
        """获取用户记忆"""
        return await self.db.get_one("user_memory", {"openid": openid})
    
    async def update_stats(self, openid: str, data: Dict[str, Any]) -> bool:
        """更新用户统计"""
        return await self.db.update("user_stats", {"openid": openid}, data) > 0


class CheckinRepository:
    """打卡数据仓库"""
    
    def __init__(self, db: Optional[WxCloudDB] = None):
        self.db = db or get_db()
    
    async def get_today_checkin(self, openid: str) -> Optional[Dict[str, Any]]:
        """获取今日打卡记录"""
        today = datetime.now().strftime("%Y-%m-%d")
        return await self.db.get_one("checkin_records", {"openid": openid, "date": today})
    
    async def do_checkin(self, openid: str) -> Dict[str, Any]:
        """执行打卡"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        # 检查是否已打卡
        existing = await self.get_today_checkin(openid)
        if existing:
            return {"success": False, "error": "今日已打卡", "data": existing}
        
        # 获取当前连续天数
        stats = await self.db.get_one("user_stats", {"openid": openid})
        current_streak = (stats.get("currentStreak", 0) if stats else 0) + 1
        
        # 创建打卡记录
        record = {
            "openid": openid,
            "date": today,
            "time": datetime.now().strftime("%H:%M"),
            "streak": current_streak,
        }
        await self.db.add("checkin_records", record)
        
        # 更新统计
        update_data = {
            "todayChecked": True,
            "currentStreak": current_streak,
            "lastCheckinDate": today,
        }
        if stats:
            update_data["studyDays"] = stats.get("studyDays", 0) + 1
            if current_streak > stats.get("longestStreak", 0):
                update_data["longestStreak"] = current_streak
        
        await self.db.update("user_stats", {"openid": openid}, update_data)
        
        return {
            "success": True,
            "data": {
                "currentStreak": current_streak,
                "studyDays": update_data.get("studyDays", 1),
            }
        }
    
    async def get_checkin_stats(self, openid: str) -> Dict[str, Any]:
        """获取打卡统计"""
        stats = await self.db.get_one("user_stats", {"openid": openid}) or {}
        
        # 获取本月打卡日期
        now = datetime.now()
        month_start = now.replace(day=1).strftime("%Y-%m-%d")
        records = await self.db.query(
            "checkin_records",
            {"openid": openid, "date": {"$gte": month_start}},
            limit=31
        )
        
        return {
            "todayChecked": stats.get("todayChecked", False),
            "currentStreak": stats.get("currentStreak", 0),
            "longestStreak": stats.get("longestStreak", 0),
            "studyDays": stats.get("studyDays", 0),
            "totalMinutes": stats.get("totalMinutes", 0),
            "thisMonthDays": len(records),
            "checkedDates": [r.get("date") for r in records],
        }


class TaskRepository:
    """任务数据仓库"""
    
    def __init__(self, db: Optional[WxCloudDB] = None):
        self.db = db or get_db()
    
    async def get_today_tasks(self, openid: str) -> List[Dict[str, Any]]:
        """获取今日任务"""
        today = datetime.now().strftime("%Y-%m-%d")
        return await self.db.query(
            "plan_tasks",
            {"openid": openid, "date": today},
            order_by="order",
            order_type="asc"
        )
    
    async def complete_task(self, task_id: str, completed: bool = True) -> bool:
        """完成/取消完成任务"""
        data = {
            "completed": completed,
        }
        if completed:
            data["completedAt"] = {"$date": datetime.now().isoformat()}
        
        return await self.db.update_by_id("plan_tasks", task_id, data)
    
    async def get_task_progress(self, openid: str) -> Dict[str, Any]:
        """获取任务进度"""
        tasks = await self.get_today_tasks(openid)
        
        total = len(tasks)
        completed = len([t for t in tasks if t.get("completed")])
        
        return {
            "total": total,
            "completed": completed,
            "progress": round(completed / total * 100, 1) if total > 0 else 0,
            "tasks": tasks,
        }


class MistakeRepository:
    """错题数据仓库"""
    
    def __init__(self, db: Optional[WxCloudDB] = None):
        self.db = db or get_db()
    
    async def get_mistakes(
        self,
        openid: str,
        category: Optional[str] = None,
        mastered: Optional[bool] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """获取错题列表"""
        query = {"openid": openid}
        if category and category != "all":
            query["category"] = category
        if mastered is not None:
            query["mastered"] = mastered
        
        return await self.db.query(
            "mistakes",
            query,
            limit=limit,
            order_by="createdAt",
            order_type="desc"
        )
    
    async def add_mistake(self, openid: str, data: Dict[str, Any]) -> str:
        """添加错题"""
        data["openid"] = openid
        data["mastered"] = False
        data["reviewCount"] = 0
        return await self.db.add("mistakes", data)
    
    async def mark_mastered(self, mistake_id: str, mastered: bool = True) -> bool:
        """标记掌握状态"""
        data = {"mastered": mastered}
        if mastered:
            data["masteredAt"] = {"$date": datetime.now().isoformat()}
        return await self.db.update_by_id("mistakes", mistake_id, data)
    
    async def get_stats(self, openid: str) -> Dict[str, Any]:
        """获取错题统计"""
        all_mistakes = await self.db.query("mistakes", {"openid": openid}, limit=1000)
        
        total = len(all_mistakes)
        mastered = len([m for m in all_mistakes if m.get("mastered")])
        
        # 按分类统计
        by_category = {}
        for m in all_mistakes:
            cat = m.get("category", "other")
            if cat not in by_category:
                by_category[cat] = {"total": 0, "mastered": 0}
            by_category[cat]["total"] += 1
            if m.get("mastered"):
                by_category[cat]["mastered"] += 1
        
        return {
            "total": total,
            "mastered": mastered,
            "pending": total - mastered,
            "byCategory": by_category,
        }


class FocusRepository:
    """专注数据仓库"""
    
    def __init__(self, db: Optional[WxCloudDB] = None):
        self.db = db or get_db()
    
    async def get_today_stats(self, openid: str) -> Dict[str, Any]:
        """获取今日专注统计"""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        records = await self.db.query(
            "focus_records",
            {"openid": openid, "date": {"$gte": {"$date": today.isoformat()}}},
            limit=100
        )
        
        total_minutes = sum(r.get("duration", 0) for r in records)
        
        return {
            "todayCount": len(records),
            "todayMinutes": total_minutes,
            "records": records,
        }
    
    async def save_focus_record(
        self,
        openid: str,
        duration: int,
        task: str = "",
    ) -> str:
        """保存专注记录"""
        record = {
            "openid": openid,
            "date": {"$date": datetime.now().isoformat()},
            "duration": duration,
            "task": task,
            "completed": True,
        }
        return await self.db.add("focus_records", record)


class PlanRepository:
    """学习计划数据仓库"""
    
    def __init__(self, db: Optional[WxCloudDB] = None):
        self.db = db or get_db()
    
    async def get_active_plan(self, openid: str) -> Optional[Dict[str, Any]]:
        """获取当前活跃的学习计划"""
        return await self.db.get_one("study_plans", {"openid": openid, "status": "active"})
    
    async def get_achievement_rate(self, openid: str) -> Dict[str, Any]:
        """获取目标达成率"""
        plan = await self.get_active_plan(openid)
        
        if not plan:
            return {"hasActivePlan": False}
        
        # 获取任务完成情况
        task_repo = TaskRepository(self.db)
        progress = await task_repo.get_task_progress(openid)
        
        return {
            "hasActivePlan": True,
            "planGoal": plan.get("goal", ""),
            "planProgress": plan.get("progress", 0),
            "todayProgress": progress.get("progress", 0),
            "taskCompletionRate": progress.get("progress", 0),
        }

