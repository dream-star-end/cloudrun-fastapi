"""
学友系统 API 路由

功能：
- 搜索用户/添加学友
- 获取学友列表
- 处理学友请求（接受/拒绝）
- 邀请学友作为监督者
- 邀请学友作为学伴
- 获取监督/学伴关系
- 发送监督提醒
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..db.wxcloud import get_db
from .websocket import (
    notify_friend_request,
    notify_friend_request_handled,
    notify_supervisor_invite,
    notify_supervisor_invite_handled,
    notify_buddy_invite,
    notify_buddy_invite_handled,
    notify_supervisor_reminder,
)

router = APIRouter(prefix="/api/friends", tags=["学友系统"])


# ==================== 请求/响应模型 ====================

class SearchUserRequest(BaseModel):
    keyword: str  # 搜索关键词（昵称）


class AddFriendRequest(BaseModel):
    friendOpenid: str
    remark: Optional[str] = ""


class HandleFriendRequest(BaseModel):
    friendshipId: str
    action: str  # accept, reject


class InviteSupervisorRequest(BaseModel):
    friendOpenid: str
    planId: Optional[str] = None  # 可选，指定监督某个计划
    message: Optional[str] = ""


class HandleSupervisorRequest(BaseModel):
    relationId: str
    action: str  # accept, reject


class InviteBuddyRequest(BaseModel):
    friendOpenid: str
    planId: str
    message: Optional[str] = ""


class HandleBuddyRequest(BaseModel):
    relationId: str
    action: str  # accept, reject


class SendReminderRequest(BaseModel):
    supervisedOpenid: str
    reminderType: str  # daily_checkin, task_progress, encouragement
    content: str


class UpdateRemarkRequest(BaseModel):
    friendshipId: str
    remark: str


# ==================== 工具函数 ====================

def _get_openid_from_request(request: Request) -> str:
    openid = request.headers.get("x-wx-openid") or request.headers.get("X-WX-OPENID")
    if not openid:
        raise HTTPException(
            status_code=401,
            detail="缺少用户身份（X-WX-OPENID），请使用 wx.cloud.callContainer 内网调用",
        )
    return openid


async def _get_user_info(db, openid: str) -> dict:
    """获取用户基本信息"""
    user = await db.get_one("users", {"openid": openid})
    if user:
        return {
            "openid": openid,
            "nickName": user.get("nickName") or "学习者",
            "avatarUrl": user.get("avatarUrl", ""),
        }
    return {
        "openid": openid,
        "nickName": "学习者",
        "avatarUrl": "",
    }


async def _get_user_stats(db, openid: str) -> dict:
    """获取用户学习统计"""
    stats = await db.get_one("user_stats", {"openid": openid})
    if stats:
        return {
            "studyDays": stats.get("studyDays", 0),
            "totalMinutes": stats.get("totalMinutes", 0),
            "currentStreak": stats.get("currentStreak", 0),
            "todayChecked": stats.get("todayChecked", False),
        }
    return {
        "studyDays": 0,
        "totalMinutes": 0,
        "currentStreak": 0,
        "todayChecked": False,
    }


# ==================== 学友管理 API ====================

@router.post("/search")
async def search_users(request: Request, body: SearchUserRequest):
    """
    搜索用户（通过昵称模糊搜索）
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    keyword = body.keyword.strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="请输入搜索关键词")
    
    try:
        # 搜索用户（排除自己）
        # 注意：微信云数据库的模糊搜索需要使用正则
        users = await db.query(
            "users",
            {
                "nickName": {"$regex": keyword, "$options": "i"},
                "openid": {"$ne": openid},
            },
            limit=20,
        )
        
        # 获取已有的学友关系
        existing_friends = await db.query(
            "friendships",
            {
                "$or": [
                    {"openid": openid},
                    {"friendOpenid": openid},
                ]
            },
            limit=1000,
        )
        
        # 构建已关联的用户集合
        friend_status_map = {}
        for f in existing_friends:
            if f.get("openid") == openid:
                friend_status_map[f.get("friendOpenid")] = f.get("status")
            else:
                friend_status_map[f.get("openid")] = f.get("status")
        
        # 组装结果
        result_users = []
        for u in users:
            user_openid = u.get("openid")
            result_users.append({
                "openid": user_openid,
                "nickName": u.get("nickName") or "学习者",
                "avatarUrl": u.get("avatarUrl", ""),
                "friendStatus": friend_status_map.get(user_openid),  # None, pending, accepted, rejected
            })
        
        return {
            "success": True,
            "data": {
                "users": result_users,
            }
        }
    except Exception as e:
        print(f"搜索用户失败: {e}")
        return {
            "success": True,
            "data": {
                "users": [],
            }
        }


@router.post("/add")
async def add_friend(request: Request, body: AddFriendRequest):
    """
    添加学友（发送好友请求）
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    friend_openid = body.friendOpenid
    remark = body.remark or ""
    
    if openid == friend_openid:
        raise HTTPException(status_code=400, detail="不能添加自己为学友")
    
    # 检查对方是否存在
    friend_user = await db.get_one("users", {"openid": friend_openid})
    if not friend_user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 检查是否已有关系
    existing = await db.get_one(
        "friendships",
        {
            "$or": [
                {"openid": openid, "friendOpenid": friend_openid},
                {"openid": friend_openid, "friendOpenid": openid},
            ]
        }
    )
    
    if existing:
        status = existing.get("status")
        if status == "accepted":
            raise HTTPException(status_code=400, detail="你们已经是学友了")
        elif status == "pending":
            # 检查是谁发起的
            if existing.get("openid") == openid:
                raise HTTPException(status_code=400, detail="已发送过好友请求，等待对方确认")
            else:
                raise HTTPException(status_code=400, detail="对方已向你发送好友请求，请在好友请求中查看")
        elif status == "blocked":
            raise HTTPException(status_code=400, detail="无法添加此用户")
    
    # 获取双方用户信息
    user_info = await _get_user_info(db, openid)
    friend_info = await _get_user_info(db, friend_openid)
    
    # 创建好友关系
    now = datetime.now(timezone.utc).isoformat()
    friendship = {
        "openid": openid,
        "friendOpenid": friend_openid,
        "status": "pending",
        "userInfo": user_info,
        "friendInfo": friend_info,
        "remark": remark.strip(),
        "createdAt": {"$date": now},
        "updatedAt": {"$date": now},
    }
    
    friendship_id = await db.add("friendships", friendship)
    friendship["_id"] = friendship_id
    
    # WebSocket 实时通知对方
    await notify_friend_request(openid, friend_openid, friendship)
    
    return {
        "success": True,
        "message": "好友请求已发送",
        "data": {
            "friendship": friendship,
        }
    }


@router.get("/list")
async def get_friends_list(request: Request):
    """
    获取学友列表
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    # 查询已接受的好友关系
    friendships = await db.query(
        "friendships",
        {
            "$or": [
                {"openid": openid, "status": "accepted"},
                {"friendOpenid": openid, "status": "accepted"},
            ]
        },
        limit=500,
        order_by="acceptedAt",
        order_type="desc",
    )
    
    # 组装学友列表
    friends = []
    for f in friendships:
        is_initiator = f.get("openid") == openid
        friend_openid = f.get("friendOpenid") if is_initiator else f.get("openid")
        friend_info = f.get("friendInfo") if is_initiator else f.get("userInfo")
        
        # 获取学友的最新学习统计
        stats = await _get_user_stats(db, friend_openid)
        
        friends.append({
            "_id": str(f.get("_id") or f.get("id")),
            "friendOpenid": friend_openid,
            "friendInfo": friend_info,
            "remark": f.get("remark", ""),
            "acceptedAt": f.get("acceptedAt"),
            "stats": stats,
        })
    
    return {
        "success": True,
        "data": {
            "friends": friends,
        }
    }


@router.get("/requests")
async def get_friend_requests(request: Request):
    """
    获取待处理的好友请求
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    # 查询收到的好友请求
    received = await db.query(
        "friendships",
        {"friendOpenid": openid, "status": "pending"},
        limit=100,
        order_by="createdAt",
        order_type="desc",
    )
    
    # 查询发出的好友请求
    sent = await db.query(
        "friendships",
        {"openid": openid, "status": "pending"},
        limit=100,
        order_by="createdAt",
        order_type="desc",
    )
    
    return {
        "success": True,
        "data": {
            "received": received,
            "sent": sent,
        }
    }


@router.post("/handle")
async def handle_friend_request(request: Request, body: HandleFriendRequest):
    """
    处理好友请求（接受/拒绝）
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    friendship_id = body.friendshipId
    action = body.action
    
    if action not in ["accept", "reject"]:
        raise HTTPException(status_code=400, detail="无效的操作")
    
    # 获取好友关系
    friendship = await db.get_by_id("friendships", friendship_id)
    if not friendship:
        raise HTTPException(status_code=404, detail="好友请求不存在")
    
    # 检查是否是接收方
    if friendship.get("friendOpenid") != openid:
        raise HTTPException(status_code=403, detail="无权操作此请求")
    
    if friendship.get("status") != "pending":
        raise HTTPException(status_code=400, detail="该请求已处理")
    
    # 获取请求发起者的 openid
    requester_openid = friendship.get("openid")
    
    now = datetime.now(timezone.utc).isoformat()
    
    if action == "accept":
        await db.update_by_id(
            "friendships",
            friendship_id,
            {
                "status": "accepted",
                "acceptedAt": {"$date": now},
                "updatedAt": {"$date": now},
            }
        )
        # WebSocket 通知请求发起者
        await notify_friend_request_handled(friendship_id, openid, requester_openid, action)
        return {
            "success": True,
            "message": "已添加学友",
        }
    else:
        await db.update_by_id(
            "friendships",
            friendship_id,
            {
                "status": "rejected",
                "updatedAt": {"$date": now},
            }
        )
        # WebSocket 通知请求发起者
        await notify_friend_request_handled(friendship_id, openid, requester_openid, action)
        return {
            "success": True,
            "message": "已拒绝",
        }


@router.post("/delete")
async def delete_friend(request: Request):
    """
    删除学友
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    try:
        body = await request.json()
    except:
        body = {}
    
    friend_openid = body.get("friendOpenid")
    if not friend_openid:
        raise HTTPException(status_code=400, detail="缺少 friendOpenid")
    
    # 查找并删除关系
    friendship = await db.get_one(
        "friendships",
        {
            "$or": [
                {"openid": openid, "friendOpenid": friend_openid, "status": "accepted"},
                {"openid": friend_openid, "friendOpenid": openid, "status": "accepted"},
            ]
        }
    )
    
    if not friendship:
        raise HTTPException(status_code=404, detail="学友关系不存在")
    
    friendship_id = str(friendship.get("_id") or friendship.get("id"))
    await db.delete_by_id("friendships", friendship_id)
    
    # 同时删除相关的监督和学伴关系
    # 监督关系
    await db.delete(
        "study_supervisors",
        {
            "$or": [
                {"supervisorOpenid": openid, "supervisedOpenid": friend_openid},
                {"supervisorOpenid": friend_openid, "supervisedOpenid": openid},
            ]
        }
    )
    
    # 学伴关系
    await db.delete(
        "study_buddies",
        {
            "$or": [
                {"planOwnerOpenid": openid, "buddyOpenid": friend_openid},
                {"planOwnerOpenid": friend_openid, "buddyOpenid": openid},
            ]
        }
    )
    
    return {
        "success": True,
        "message": "已删除学友",
    }


@router.post("/update-remark")
async def update_friend_remark(request: Request, body: UpdateRemarkRequest):
    """
    更新学友备注名
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    friendship_id = body.friendshipId
    remark = body.remark.strip()
    
    # 获取好友关系
    friendship = await db.get_by_id("friendships", friendship_id)
    if not friendship:
        raise HTTPException(status_code=404, detail="学友关系不存在")
    
    # 检查是否有权限
    if friendship.get("openid") != openid and friendship.get("friendOpenid") != openid:
        raise HTTPException(status_code=403, detail="无权操作")
    
    now = datetime.now(timezone.utc).isoformat()
    await db.update_by_id(
        "friendships",
        friendship_id,
        {
            "remark": remark,
            "updatedAt": {"$date": now},
        }
    )
    
    return {
        "success": True,
        "message": "备注已更新",
    }


# ==================== 监督者 API ====================

@router.post("/supervisor/invite")
async def invite_supervisor(request: Request, body: InviteSupervisorRequest):
    """
    邀请学友作为监督者
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    friend_openid = body.friendOpenid
    plan_id = body.planId
    message = body.message or ""
    
    # 检查是否是学友
    friendship = await db.get_one(
        "friendships",
        {
            "$or": [
                {"openid": openid, "friendOpenid": friend_openid, "status": "accepted"},
                {"openid": friend_openid, "friendOpenid": openid, "status": "accepted"},
            ]
        }
    )
    
    if not friendship:
        raise HTTPException(status_code=400, detail="只能邀请学友作为监督者")
    
    # 检查是否已有监督关系
    existing = await db.get_one(
        "study_supervisors",
        {
            "supervisorOpenid": friend_openid,
            "supervisedOpenid": openid,
            "status": {"$in": ["pending", "accepted"]},
        }
    )
    
    if existing:
        if existing.get("status") == "pending":
            raise HTTPException(status_code=400, detail="已发送监督邀请，等待确认")
        else:
            raise HTTPException(status_code=400, detail="该学友已是你的监督者")
    
    # 获取用户信息
    supervisor_info = await _get_user_info(db, friend_openid)
    supervised_info = await _get_user_info(db, openid)
    
    # 创建监督关系
    now = datetime.now(timezone.utc).isoformat()
    relation = {
        "supervisorOpenid": friend_openid,
        "supervisedOpenid": openid,
        "planId": plan_id,
        "status": "pending",
        "supervisorInfo": supervisor_info,
        "supervisedInfo": supervised_info,
        "settings": {
            "reminderEnabled": True,
            "reminderTime": "20:00",  # 默认晚上8点提醒
        },
        "inviteMessage": message.strip(),
        "createdAt": {"$date": now},
    }
    
    relation_id = await db.add("study_supervisors", relation)
    relation["_id"] = relation_id
    
    # WebSocket 实时通知被邀请的监督者
    await notify_supervisor_invite(openid, friend_openid, relation)
    
    return {
        "success": True,
        "message": "监督邀请已发送",
        "data": {
            "relation": relation,
        }
    }


@router.get("/supervisor/list")
async def get_supervisors(request: Request):
    """
    获取我的监督者列表和我监督的人
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    # 我的监督者（别人监督我）
    my_supervisors = await db.query(
        "study_supervisors",
        {"supervisedOpenid": openid, "status": "accepted"},
        limit=100,
    )
    
    # 我监督的人（我监督别人）
    i_supervise = await db.query(
        "study_supervisors",
        {"supervisorOpenid": openid, "status": "accepted"},
        limit=100,
    )
    
    # 获取被监督者的最新学习数据
    for s in i_supervise:
        supervised_openid = s.get("supervisedOpenid")
        stats = await _get_user_stats(db, supervised_openid)
        s["supervisedStats"] = stats
        
        # 获取今日任务完成情况
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tasks = await db.query(
            "plan_tasks",
            {
                "openid": supervised_openid,
                "dateStr": today,
            },
            limit=20,
        )
        total_tasks = len(tasks)
        completed_tasks = len([t for t in tasks if t.get("completed")])
        s["todayTasks"] = {
            "total": total_tasks,
            "completed": completed_tasks,
            "rate": round(completed_tasks / total_tasks * 100) if total_tasks > 0 else 0,
        }
    
    return {
        "success": True,
        "data": {
            "mySupervisors": my_supervisors,
            "iSupervise": i_supervise,
        }
    }


@router.get("/supervisor/requests")
async def get_supervisor_requests(request: Request):
    """
    获取监督邀请（收到的和发出的）
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    # 收到的监督邀请（别人邀请我监督他们）
    received = await db.query(
        "study_supervisors",
        {"supervisorOpenid": openid, "status": "pending"},
        limit=50,
    )
    
    # 发出的监督邀请（我邀请别人监督我）
    sent = await db.query(
        "study_supervisors",
        {"supervisedOpenid": openid, "status": "pending"},
        limit=50,
    )
    
    return {
        "success": True,
        "data": {
            "received": received,
            "sent": sent,
        }
    }


@router.post("/supervisor/handle")
async def handle_supervisor_request(request: Request, body: HandleSupervisorRequest):
    """
    处理监督邀请
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    relation_id = body.relationId
    action = body.action
    
    if action not in ["accept", "reject"]:
        raise HTTPException(status_code=400, detail="无效的操作")
    
    relation = await db.get_by_id("study_supervisors", relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="邀请不存在")
    
    # 检查是否是被邀请的监督者
    if relation.get("supervisorOpenid") != openid:
        raise HTTPException(status_code=403, detail="无权操作")
    
    if relation.get("status") != "pending":
        raise HTTPException(status_code=400, detail="该邀请已处理")
    
    # 获取邀请发起者（被监督者）的 openid
    inviter_openid = relation.get("supervisedOpenid")
    
    now = datetime.now(timezone.utc).isoformat()
    
    if action == "accept":
        await db.update_by_id(
            "study_supervisors",
            relation_id,
            {
                "status": "accepted",
                "acceptedAt": {"$date": now},
            }
        )
        # WebSocket 通知邀请发起者
        await notify_supervisor_invite_handled(relation_id, openid, inviter_openid, action)
        return {
            "success": True,
            "message": "已成为监督者",
        }
    else:
        await db.update_by_id(
            "study_supervisors",
            relation_id,
            {"status": "rejected"}
        )
        # WebSocket 通知邀请发起者
        await notify_supervisor_invite_handled(relation_id, openid, inviter_openid, action)
        return {
            "success": True,
            "message": "已拒绝",
        }


@router.post("/supervisor/end")
async def end_supervision(request: Request):
    """
    结束监督关系
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    try:
        body = await request.json()
    except:
        body = {}
    
    relation_id = body.get("relationId")
    if not relation_id:
        raise HTTPException(status_code=400, detail="缺少 relationId")
    
    relation = await db.get_by_id("study_supervisors", relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="监督关系不存在")
    
    # 检查权限（监督者或被监督者都可以结束）
    if relation.get("supervisorOpenid") != openid and relation.get("supervisedOpenid") != openid:
        raise HTTPException(status_code=403, detail="无权操作")
    
    await db.update_by_id(
        "study_supervisors",
        relation_id,
        {"status": "ended"}
    )
    
    return {
        "success": True,
        "message": "监督关系已结束",
    }


@router.post("/supervisor/remind")
async def send_reminder(request: Request, body: SendReminderRequest):
    """
    监督者发送提醒
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    supervised_openid = body.supervisedOpenid
    reminder_type = body.reminderType
    content = body.content
    
    if reminder_type not in ["daily_checkin", "task_progress", "encouragement"]:
        raise HTTPException(status_code=400, detail="无效的提醒类型")
    
    if not content.strip():
        raise HTTPException(status_code=400, detail="请输入提醒内容")
    
    # 检查是否有监督关系
    relation = await db.get_one(
        "study_supervisors",
        {
            "supervisorOpenid": openid,
            "supervisedOpenid": supervised_openid,
            "status": "accepted",
        }
    )
    
    if not relation:
        raise HTTPException(status_code=400, detail="你不是该用户的监督者")
    
    relation_id = str(relation.get("_id") or relation.get("id"))
    
    # 创建提醒记录
    now = datetime.now(timezone.utc).isoformat()
    reminder = {
        "supervisorOpenid": openid,
        "supervisedOpenid": supervised_openid,
        "relationId": relation_id,
        "reminderType": reminder_type,
        "content": content.strip(),
        "isRead": False,
        "createdAt": {"$date": now},
    }
    
    reminder_id = await db.add("supervisor_reminders", reminder)
    reminder["_id"] = reminder_id
    
    # 同时创建一条私聊消息（让被监督者能在聊天中看到）
    # 先获取或创建私聊会话
    participants = sorted([openid, supervised_openid])
    chat = await db.get_one(
        "private_chats",
        {"participants": participants}
    )
    
    if not chat:
        supervisor_info = await _get_user_info(db, openid)
        supervised_info = await _get_user_info(db, supervised_openid)
        chat = {
            "participants": participants,
            "participantInfos": {
                openid: supervisor_info,
                supervised_openid: supervised_info,
            },
            "unreadCount": {openid: 0, supervised_openid: 0},
            "createdAt": {"$date": now},
            "updatedAt": {"$date": now},
        }
        chat_id = await db.add("private_chats", chat)
        chat["_id"] = chat_id
    else:
        chat_id = str(chat.get("_id") or chat.get("id"))
    
    # 创建系统消息
    reminder_type_text = {
        "daily_checkin": "打卡提醒",
        "task_progress": "学习进度提醒",
        "encouragement": "加油鼓励",
    }
    
    message = {
        "chatId": chat_id,
        "senderOpenid": openid,
        "receiverOpenid": supervised_openid,
        "content": f"【{reminder_type_text.get(reminder_type, '提醒')}】{content.strip()}",
        "messageType": "system",
        "reference": {
            "type": "reminder",
            "reminderId": reminder_id,
            "reminderType": reminder_type,
        },
        "isRead": False,
        "createdAt": {"$date": now},
    }
    
    await db.add("private_messages", message)
    
    # 更新会话的最新消息
    await db.update_by_id(
        "private_chats",
        chat_id,
        {
            "lastMessage": {
                "content": f"【{reminder_type_text.get(reminder_type, '提醒')}】{content.strip()[:20]}...",
                "senderOpenid": openid,
                "messageType": "system",
            },
            "lastMessageAt": {"$date": now},
            f"unreadCount.{supervised_openid}": (chat.get("unreadCount", {}).get(supervised_openid, 0) or 0) + 1,
            "updatedAt": {"$date": now},
        }
    )
    
    # WebSocket 实时推送监督提醒给被监督者
    await notify_supervisor_reminder(openid, supervised_openid, reminder)
    
    return {
        "success": True,
        "message": "提醒已发送",
        "data": {
            "reminder": reminder,
        }
    }


@router.get("/supervisor/reminders")
async def get_reminders(request: Request):
    """
    获取收到的监督提醒
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    reminders = await db.query(
        "supervisor_reminders",
        {"supervisedOpenid": openid},
        limit=50,
        order_by="createdAt",
        order_type="desc",
    )
    
    # 获取监督者信息
    for r in reminders:
        supervisor_info = await _get_user_info(db, r.get("supervisorOpenid"))
        r["supervisorInfo"] = supervisor_info
    
    return {
        "success": True,
        "data": {
            "reminders": reminders,
        }
    }


@router.get("/supervisor/supervised/{supervised_openid}")
async def get_supervised_detail(request: Request, supervised_openid: str):
    """
    获取被监督者的详细学习数据（仅监督者可访问）
    包括：学习统计、当前计划、计划进度、今日任务、近期打卡记录、学习时长趋势等
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    # 验证监督关系
    relation = await db.get_one(
        "study_supervisors",
        {
            "supervisorOpenid": openid,
            "supervisedOpenid": supervised_openid,
            "status": "accepted",
        }
    )
    
    if not relation:
        raise HTTPException(status_code=403, detail="你不是该用户的监督者")
    
    # 获取用户基本信息
    user_info = await _get_user_info(db, supervised_openid)
    
    # 获取学习统计
    stats = await _get_user_stats(db, supervised_openid)
    
    # 获取当前活跃计划
    plan = await db.get_one(
        "study_plans",
        {"openid": supervised_openid, "status": "active"}
    )
    
    plan_info = None
    phases_progress = []
    if plan:
        # 兼容嵌套数据结构
        if "data" in plan and isinstance(plan.get("data"), dict):
            plan = {**plan.get("data"), "_id": plan.get("_id")}
        
        # 计算阶段进度
        phases = plan.get("phases", [])
        for i, phase in enumerate(phases):
            phase_progress = {
                "name": phase.get("name", f"阶段{i+1}"),
                "duration": phase.get("duration", ""),
                "status": phase.get("status", "pending"),
                "progress": phase.get("progress", 0),
                "goals": phase.get("goals", [])[:3],  # 只返回前3个目标
            }
            phases_progress.append(phase_progress)
        
        plan_info = {
            "_id": str(plan.get("_id") or plan.get("id")),
            "goal": plan.get("goal", ""),
            "domain": plan.get("domain", ""),
            "domainName": plan.get("domainName", ""),
            "totalDuration": plan.get("totalDuration", ""),
            "progress": plan.get("progress", 0),
            "todayProgress": plan.get("todayProgress", 0),
            "dailyHours": plan.get("dailyHours", 2),
            "createdAt": plan.get("createdAt"),
            "phases": phases_progress,
            "currentPhaseIndex": next((i for i, p in enumerate(phases) if p.get("status") == "current"), 0),
        }
    
    # 获取今日任务
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_tasks = await db.query(
        "plan_tasks",
        {
            "openid": supervised_openid,
            "dateStr": today,
        },
        limit=20,
        order_by="order",
    )
    
    tasks_info = []
    for t in today_tasks:
        tasks_info.append({
            "title": t.get("title", ""),
            "duration": t.get("duration", ""),
            "completed": t.get("completed", False),
            "phase": t.get("phase", ""),
            "order": t.get("order", 0),
        })
    
    total_tasks = len(tasks_info)
    completed_tasks = len([t for t in tasks_info if t.get("completed")])
    
    # 获取近7天打卡记录
    from datetime import timedelta
    checkin_records = []
    for i in range(7):
        date = datetime.now(timezone.utc) - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        
        checkin = await db.get_one(
            "checkin_records",
            {
                "openid": supervised_openid,
                "dateStr": date_str,
            }
        )
        
        # 如果没有打卡记录，检查任务完成情况
        if not checkin:
            day_tasks = await db.query(
                "plan_tasks",
                {
                    "openid": supervised_openid,
                    "dateStr": date_str,
                },
                limit=20,
            )
            has_completed = any(t.get("completed") for t in day_tasks)
            checkin_records.append({
                "date": date_str,
                "checked": has_completed,
                "studyMinutes": 0,
                "note": "",
            })
        else:
            checkin_records.append({
                "date": date_str,
                "checked": True,
                "studyMinutes": checkin.get("studyMinutes", 0),
                "note": checkin.get("note", ""),
                "mood": checkin.get("mood", ""),
            })
    
    # 获取本周学习时长统计
    week_start = datetime.now(timezone.utc) - timedelta(days=datetime.now(timezone.utc).weekday())
    week_start_str = week_start.strftime("%Y-%m-%d")
    
    week_checkins = await db.query(
        "checkin_records",
        {
            "openid": supervised_openid,
            "dateStr": {"$gte": week_start_str},
        },
        limit=7,
    )
    
    week_study_minutes = sum(c.get("studyMinutes", 0) for c in week_checkins)
    
    # 获取监督关系信息
    relation_info = {
        "_id": str(relation.get("_id") or relation.get("id")),
        "createdAt": relation.get("createdAt"),
        "acceptedAt": relation.get("acceptedAt"),
        "settings": relation.get("settings", {}),
    }
    
    return {
        "success": True,
        "data": {
            "userInfo": user_info,
            "stats": {
                **stats,
                "weekStudyMinutes": week_study_minutes,
            },
            "plan": plan_info,
            "todayTasks": {
                "total": total_tasks,
                "completed": completed_tasks,
                "rate": round(completed_tasks / total_tasks * 100) if total_tasks > 0 else 0,
                "tasks": tasks_info,
            },
            "recentCheckins": checkin_records,
            "relation": relation_info,
        }
    }


# ==================== 学伴 API ====================

@router.post("/buddy/invite")
async def invite_buddy(request: Request, body: InviteBuddyRequest):
    """
    邀请学友作为学伴，共同学习某个计划
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    friend_openid = body.friendOpenid
    plan_id = body.planId
    message = body.message or ""
    
    # 检查是否是学友
    friendship = await db.get_one(
        "friendships",
        {
            "$or": [
                {"openid": openid, "friendOpenid": friend_openid, "status": "accepted"},
                {"openid": friend_openid, "friendOpenid": openid, "status": "accepted"},
            ]
        }
    )
    
    if not friendship:
        raise HTTPException(status_code=400, detail="只能邀请学友作为学伴")
    
    # 检查计划是否存在
    plan = await db.get_by_id("study_plans", plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="学习计划不存在")
    
    # 兼容嵌套数据结构
    if "data" in plan and isinstance(plan.get("data"), dict):
        plan = {**plan.get("data"), "_id": plan.get("_id")}
    
    if plan.get("openid") != openid:
        raise HTTPException(status_code=403, detail="只能邀请学友加入自己的计划")
    
    # 检查是否已有学伴关系
    existing = await db.get_one(
        "study_buddies",
        {
            "planId": plan_id,
            "buddyOpenid": friend_openid,
            "status": {"$in": ["pending", "accepted"]},
        }
    )
    
    if existing:
        if existing.get("status") == "pending":
            raise HTTPException(status_code=400, detail="已发送学伴邀请，等待确认")
        else:
            raise HTTPException(status_code=400, detail="该学友已是此计划的学伴")
    
    # 获取用户信息
    owner_info = await _get_user_info(db, openid)
    buddy_info = await _get_user_info(db, friend_openid)
    
    # 创建学伴关系
    now = datetime.now(timezone.utc).isoformat()
    relation = {
        "planId": plan_id,
        "planOwnerOpenid": openid,
        "buddyOpenid": friend_openid,
        "status": "pending",
        "planOwnerInfo": owner_info,
        "buddyInfo": buddy_info,
        "inviteMessage": message.strip(),
        "createdAt": {"$date": now},
    }
    
    relation_id = await db.add("study_buddies", relation)
    relation["_id"] = relation_id
    
    # 附加计划信息
    relation["plan"] = {
        "goal": plan.get("goal", ""),
        "domain": plan.get("domain", ""),
        "domainName": plan.get("domainName", ""),
        "totalDuration": plan.get("totalDuration", ""),
    }
    
    # WebSocket 实时通知被邀请的学伴
    await notify_buddy_invite(openid, friend_openid, relation, plan)
    
    return {
        "success": True,
        "message": "学伴邀请已发送",
        "data": {
            "relation": relation,
        }
    }


@router.get("/buddy/list")
async def get_buddies(request: Request):
    """
    获取学伴列表
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    # 我创建的计划的学伴
    my_plan_buddies = await db.query(
        "study_buddies",
        {"planOwnerOpenid": openid, "status": "accepted"},
        limit=100,
    )
    
    # 我加入的计划（作为学伴）
    joined_plans = await db.query(
        "study_buddies",
        {"buddyOpenid": openid, "status": "accepted"},
        limit=100,
    )
    
    # 获取相关计划信息
    for b in my_plan_buddies + joined_plans:
        plan = await db.get_by_id("study_plans", b.get("planId"))
        if plan:
            if "data" in plan and isinstance(plan.get("data"), dict):
                plan = {**plan.get("data"), "_id": plan.get("_id")}
            b["plan"] = {
                "_id": str(plan.get("_id") or plan.get("id")),
                "goal": plan.get("goal", ""),
                "domain": plan.get("domain", ""),
                "domainName": plan.get("domainName", ""),
                "totalDuration": plan.get("totalDuration", ""),
                "progress": plan.get("progress", 0),
            }
        
        # 获取学伴的学习统计
        buddy_openid = b.get("buddyOpenid") if b.get("planOwnerOpenid") == openid else b.get("planOwnerOpenid")
        stats = await _get_user_stats(db, buddy_openid)
        b["buddyStats"] = stats
    
    return {
        "success": True,
        "data": {
            "myPlanBuddies": my_plan_buddies,
            "joinedPlans": joined_plans,
        }
    }


@router.get("/buddy/requests")
async def get_buddy_requests(request: Request):
    """
    获取学伴邀请
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    # 收到的学伴邀请
    received = await db.query(
        "study_buddies",
        {"buddyOpenid": openid, "status": "pending"},
        limit=50,
    )
    
    # 发出的学伴邀请
    sent = await db.query(
        "study_buddies",
        {"planOwnerOpenid": openid, "status": "pending"},
        limit=50,
    )
    
    # 获取计划信息
    for b in received + sent:
        plan = await db.get_by_id("study_plans", b.get("planId"))
        if plan:
            if "data" in plan and isinstance(plan.get("data"), dict):
                plan = {**plan.get("data"), "_id": plan.get("_id")}
            b["plan"] = {
                "_id": str(plan.get("_id") or plan.get("id")),
                "goal": plan.get("goal", ""),
                "domain": plan.get("domain", ""),
                "domainName": plan.get("domainName", ""),
                "totalDuration": plan.get("totalDuration", ""),
            }
    
    return {
        "success": True,
        "data": {
            "received": received,
            "sent": sent,
        }
    }


@router.post("/buddy/handle")
async def handle_buddy_request(request: Request, body: HandleBuddyRequest):
    """
    处理学伴邀请
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    relation_id = body.relationId
    action = body.action
    
    if action not in ["accept", "reject"]:
        raise HTTPException(status_code=400, detail="无效的操作")
    
    relation = await db.get_by_id("study_buddies", relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="邀请不存在")
    
    if relation.get("buddyOpenid") != openid:
        raise HTTPException(status_code=403, detail="无权操作")
    
    if relation.get("status") != "pending":
        raise HTTPException(status_code=400, detail="该邀请已处理")
    
    # 获取邀请发起者（计划所有者）的 openid
    inviter_openid = relation.get("planOwnerOpenid")
    
    now = datetime.now(timezone.utc).isoformat()
    
    if action == "accept":
        await db.update_by_id(
            "study_buddies",
            relation_id,
            {
                "status": "accepted",
                "acceptedAt": {"$date": now},
            }
        )
        
        # 为学伴复制计划
        plan = await db.get_by_id("study_plans", relation.get("planId"))
        if plan:
            if "data" in plan and isinstance(plan.get("data"), dict):
                plan = {**plan.get("data"), "_id": plan.get("_id")}
            
            # 将学伴的现有活跃计划置为 archived
            await db.update(
                "study_plans",
                {"openid": openid, "status": "active"},
                {"status": "archived"},
            )
            
            # 复制计划
            new_plan = {
                "openid": openid,
                "goal": plan.get("goal", ""),
                "domain": plan.get("domain", ""),
                "domainName": plan.get("domainName", ""),
                "deadline": plan.get("deadline"),
                "dailyHours": plan.get("dailyHours", 2),
                "currentLevel": plan.get("currentLevel", "beginner"),
                "personalization": plan.get("personalization", {}),
                "status": "active",
                "progress": 0,
                "todayProgress": 0,
                "completedDays": 0,
                "phases": plan.get("phases", []),
                "totalDuration": plan.get("totalDuration", ""),
                "dailySchedule": plan.get("dailySchedule", []),
                "tips": plan.get("tips", []),
                # 标记为学伴计划
                "isBuddyPlan": True,
                "buddyRelationId": relation_id,
                "originalPlanId": str(plan.get("_id") or plan.get("id")),
                "originalOwnerOpenid": relation.get("planOwnerOpenid"),
                "createdAt": {"$date": now},
                "updatedAt": {"$date": now},
            }
            
            await db.add("study_plans", new_plan)
        
        # WebSocket 通知邀请发起者
        await notify_buddy_invite_handled(relation_id, openid, inviter_openid, action)
        return {
            "success": True,
            "message": "已加入学习计划",
        }
    else:
        await db.update_by_id(
            "study_buddies",
            relation_id,
            {"status": "rejected"}
        )
        # WebSocket 通知邀请发起者
        await notify_buddy_invite_handled(relation_id, openid, inviter_openid, action)
        return {
            "success": True,
            "message": "已拒绝",
        }


@router.post("/buddy/leave")
async def leave_buddy_plan(request: Request):
    """
    退出学伴计划
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    try:
        body = await request.json()
    except:
        body = {}
    
    relation_id = body.get("relationId")
    if not relation_id:
        raise HTTPException(status_code=400, detail="缺少 relationId")
    
    relation = await db.get_by_id("study_buddies", relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="学伴关系不存在")
    
    # 只有学伴可以退出，计划所有者需要删除
    if relation.get("buddyOpenid") != openid:
        raise HTTPException(status_code=403, detail="无权操作")
    
    await db.update_by_id(
        "study_buddies",
        relation_id,
        {"status": "left"}
    )
    
    return {
        "success": True,
        "message": "已退出学伴计划",
    }


# ==================== 用户资料 API ====================

@router.get("/profile/{target_openid}")
async def get_friend_profile(request: Request, target_openid: str):
    """
    获取学友的详细资料（包括学习统计、当前计划等）
    仅对学友可见
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    # 检查是否是学友
    friendship = await db.get_one(
        "friendships",
        {
            "$or": [
                {"openid": openid, "friendOpenid": target_openid, "status": "accepted"},
                {"openid": target_openid, "friendOpenid": openid, "status": "accepted"},
            ]
        }
    )
    
    if not friendship:
        raise HTTPException(status_code=403, detail="只能查看学友的资料")
    
    # 获取用户信息
    user_info = await _get_user_info(db, target_openid)
    
    # 获取学习统计
    stats = await _get_user_stats(db, target_openid)
    
    # 获取当前活跃计划
    plan = await db.get_one(
        "study_plans",
        {"openid": target_openid, "status": "active"}
    )
    
    plan_info = None
    if plan:
        if "data" in plan and isinstance(plan.get("data"), dict):
            plan = {**plan.get("data"), "_id": plan.get("_id")}
        plan_info = {
            "_id": str(plan.get("_id") or plan.get("id")),
            "goal": plan.get("goal", ""),
            "domain": plan.get("domain", ""),
            "domainName": plan.get("domainName", ""),
            "totalDuration": plan.get("totalDuration", ""),
            "progress": plan.get("progress", 0),
            "todayProgress": plan.get("todayProgress", 0),
        }
    
    # 检查与该学友的监督/学伴关系
    supervisor_relation = await db.get_one(
        "study_supervisors",
        {
            "$or": [
                {"supervisorOpenid": openid, "supervisedOpenid": target_openid, "status": "accepted"},
                {"supervisorOpenid": target_openid, "supervisedOpenid": openid, "status": "accepted"},
            ]
        }
    )
    
    buddy_relation = await db.get_one(
        "study_buddies",
        {
            "$or": [
                {"planOwnerOpenid": openid, "buddyOpenid": target_openid, "status": "accepted"},
                {"planOwnerOpenid": target_openid, "buddyOpenid": openid, "status": "accepted"},
            ]
        }
    )
    
    return {
        "success": True,
        "data": {
            "userInfo": user_info,
            "stats": stats,
            "currentPlan": plan_info,
            "relations": {
                "isSupervisor": supervisor_relation.get("supervisorOpenid") == openid if supervisor_relation else False,
                "isSupervised": supervisor_relation.get("supervisedOpenid") == openid if supervisor_relation else False,
                "isBuddy": buddy_relation is not None,
            },
            "remark": friendship.get("remark", ""),
        }
    }


# ==================== 在线状态 API ====================

@router.get("/online-status")
async def get_friends_online_status(request: Request):
    """
    获取所有学友的在线状态
    返回每个学友的在线状态和最后活跃时间
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    # 导入 WebSocket 管理器
    from .websocket import manager
    
    # 获取用户的所有学友
    friendships = await db.query(
        "friendships",
        {
            "$or": [
                {"openid": openid, "status": "accepted"},
                {"friendOpenid": openid, "status": "accepted"},
            ]
        },
        limit=500,
    )
    
    # 收集学友的 openid 并获取在线状态
    friends_status = {}
    for f in friendships:
        friend_openid = f.get("friendOpenid") if f.get("openid") == openid else f.get("openid")
        if friend_openid:
            is_online = manager.is_user_online(friend_openid)
            last_active = manager.get_user_last_active(friend_openid)
            friends_status[friend_openid] = {
                "isOnline": is_online,
                "lastActiveAt": last_active.isoformat() if last_active else None,
            }
    
    return {
        "success": True,
        "data": {
            "friendsStatus": friends_status,
        }
    }


@router.post("/online-status/batch")
async def get_batch_online_status(request: Request):
    """
    批量获取指定用户的在线状态
    """
    openid = _get_openid_from_request(request)
    
    try:
        body = await request.json()
    except:
        body = {}
    
    openids = body.get("openids", [])
    if not openids or not isinstance(openids, list):
        return {
            "success": True,
            "data": {
                "status": {},
            }
        }
    
    # 导入 WebSocket 管理器
    from .websocket import manager
    
    # 批量获取在线状态
    status = manager.get_users_online_status(openids)
    
    return {
        "success": True,
        "data": {
            "status": status,
        }
    }
