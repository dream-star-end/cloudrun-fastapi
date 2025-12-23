"""
私聊消息 API 路由

功能：
- 获取会话列表
- 获取消息列表
- 发送消息
- 标记已读
- 获取未读数
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..db.wxcloud import get_db

router = APIRouter(prefix="/api/chat/private", tags=["私聊消息"])


# ==================== 请求/响应模型 ====================

class SendMessageRequest(BaseModel):
    receiverOpenid: str
    content: str
    messageType: str = "text"  # text, image, voice, progress
    voiceDuration: Optional[int] = None  # 语音时长（秒）
    reference: Optional[dict] = None  # 关联内容


class GetMessagesRequest(BaseModel):
    chatId: str
    page: int = 0
    pageSize: int = 30


class MarkReadRequest(BaseModel):
    chatId: str


class DeleteConversationRequest(BaseModel):
    chatId: str


class ClearChatRequest(BaseModel):
    chatId: str


class RecallMessageRequest(BaseModel):
    messageId: str


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


async def _get_or_create_chat(db, openid1: str, openid2: str) -> dict:
    """获取或创建私聊会话"""
    participants = sorted([openid1, openid2])
    
    chat = await db.get_one(
        "private_chats",
        {"participants": participants}
    )
    
    if chat:
        return chat
    
    # 创建新会话
    now = datetime.now(timezone.utc).isoformat()
    user1_info = await _get_user_info(db, openid1)
    user2_info = await _get_user_info(db, openid2)
    
    new_chat = {
        "participants": participants,
        "participantInfos": {
            openid1: user1_info,
            openid2: user2_info,
        },
        "unreadCount": {openid1: 0, openid2: 0},
        # 使用空对象而非 None，避免 CloudBase 更新嵌套字段时报错
        # "Cannot create field 'xxx' in element {lastMessage: null}"
        "lastMessage": {},
        "lastMessageAt": None,
        "createdAt": {"$date": now},
        "updatedAt": {"$date": now},
    }
    
    chat_id = await db.add("private_chats", new_chat)
    new_chat["_id"] = chat_id
    
    return new_chat


# ==================== API 路由 ====================

@router.get("/conversations")
async def get_conversations(request: Request):
    """
    获取会话列表
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    # 查询包含当前用户的所有会话
    chats = await db.query(
        "private_chats",
        {"participants": openid},
        limit=100,
        order_by="lastMessageAt",
        order_type="desc",
    )
    
    # 组装会话列表
    conversations = []
    for chat in chats:
        chat_id = str(chat.get("_id") or chat.get("id"))
        participants = chat.get("participants", [])
        participant_infos = chat.get("participantInfos", {})
        
        # 获取对方信息
        other_openid = None
        for p in participants:
            if p != openid:
                other_openid = p
                break
        
        if not other_openid:
            continue
        
        other_info = participant_infos.get(other_openid, {})
        
        # 如果没有用户信息，重新获取
        if not other_info or not other_info.get("nickName"):
            other_info = await _get_user_info(db, other_openid)
            # 更新会话中的用户信息
            await db.update_by_id(
                "private_chats",
                chat_id,
                {f"participantInfos.{other_openid}": other_info}
            )
        
        unread_count = chat.get("unreadCount", {}).get(openid, 0) or 0
        
        conversations.append({
            "_id": chat_id,
            "otherUser": other_info,
            "lastMessage": chat.get("lastMessage"),
            "lastMessageAt": chat.get("lastMessageAt"),
            "unreadCount": unread_count,
        })
    
    return {
        "success": True,
        "data": {
            "conversations": conversations,
        }
    }


@router.post("/messages")
async def get_messages(request: Request, body: GetMessagesRequest):
    """
    获取消息列表
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    chat_id = body.chatId
    page = body.page
    page_size = body.pageSize
    
    # 验证会话权限
    chat = await db.get_by_id("private_chats", chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    if openid not in chat.get("participants", []):
        raise HTTPException(status_code=403, detail="无权访问此会话")
    
    # 获取消息
    messages = await db.query(
        "private_messages",
        {"chatId": chat_id},
        limit=page_size,
        skip=page * page_size,
        order_by="createdAt",
        order_type="desc",
    )
    
    # 反转顺序，使消息按时间正序排列
    messages = list(reversed(messages))
    
    # 获取对方信息
    participants = chat.get("participants", [])
    other_openid = None
    for p in participants:
        if p != openid:
            other_openid = p
            break
    
    other_info = chat.get("participantInfos", {}).get(other_openid, {})
    if not other_info:
        other_info = await _get_user_info(db, other_openid)
    
    return {
        "success": True,
        "data": {
            "messages": messages,
            "otherUser": other_info,
            "hasMore": len(messages) >= page_size,
        }
    }


@router.post("/send")
async def send_message(request: Request, body: SendMessageRequest):
    """
    发送消息
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    receiver_openid = body.receiverOpenid
    content = body.content
    message_type = body.messageType
    voice_duration = body.voiceDuration
    reference = body.reference
    
    # 语音和图片消息可以为空内容（存储的是文件ID）
    if message_type == "text" and not content.strip():
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    
    if len(content) > 2000:
        raise HTTPException(status_code=400, detail="消息内容不能超过2000字")
    
    if openid == receiver_openid:
        raise HTTPException(status_code=400, detail="不能给自己发消息")
    
    # 检查是否是学友
    friendship = await db.get_one(
        "friendships",
        {
            "$or": [
                {"openid": openid, "friendOpenid": receiver_openid, "status": "accepted"},
                {"openid": receiver_openid, "friendOpenid": openid, "status": "accepted"},
            ]
        }
    )
    
    if not friendship:
        raise HTTPException(status_code=400, detail="只能给学友发送消息")
    
    # 获取或创建会话
    chat = await _get_or_create_chat(db, openid, receiver_openid)
    chat_id = str(chat.get("_id") or chat.get("id"))
    
    # 创建消息
    now = datetime.now(timezone.utc).isoformat()
    message = {
        "chatId": chat_id,
        "senderOpenid": openid,
        "receiverOpenid": receiver_openid,
        "content": content.strip() if message_type == "text" else content,
        "messageType": message_type,
        "reference": reference,
        "isRead": False,
        "createdAt": {"$date": now},
    }
    
    # 添加语音时长
    if message_type == "voice" and voice_duration:
        message["voiceDuration"] = voice_duration
    
    # 添加图片URL（用于前端展示）
    if message_type == "image":
        message["imageUrl"] = content
    
    message_id = await db.add("private_messages", message)
    message["_id"] = message_id
    
    # 更新会话
    current_unread = chat.get("unreadCount", {}).get(receiver_openid, 0) or 0
    
    # 构建最后一条消息预览
    if message_type == "voice":
        preview_content = f"[语音] {voice_duration}″"
    elif message_type == "image":
        preview_content = "[图片]"
    elif message_type == "progress":
        preview_content = "[学习进度]"
    else:
        preview_content = content.strip()
        if len(preview_content) > 30:
            preview_content = preview_content[:30] + "..."
    
    await db.update_by_id(
        "private_chats",
        chat_id,
        {
            "lastMessage": {
                "content": preview_content,
                "senderOpenid": openid,
                "messageType": message_type,
            },
            "lastMessageAt": {"$date": now},
            f"unreadCount.{receiver_openid}": current_unread + 1,
            "updatedAt": {"$date": now},
        }
    )
    
    # 获取发送者信息
    sender_info = await _get_user_info(db, openid)
    message["senderInfo"] = sender_info
    
    return {
        "success": True,
        "data": {
            "message": message,
        }
    }


@router.post("/read")
async def mark_read(request: Request, body: MarkReadRequest):
    """
    标记会话消息已读
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    chat_id = body.chatId
    
    # 验证会话权限
    chat = await db.get_by_id("private_chats", chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    if openid not in chat.get("participants", []):
        raise HTTPException(status_code=403, detail="无权访问此会话")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # 标记消息已读
    await db.update(
        "private_messages",
        {
            "chatId": chat_id,
            "receiverOpenid": openid,
            "isRead": False,
        },
        {
            "isRead": True,
            "readAt": {"$date": now},
        }
    )
    
    # 清空未读数
    await db.update_by_id(
        "private_chats",
        chat_id,
        {f"unreadCount.{openid}": 0}
    )
    
    return {
        "success": True,
        "message": "已标记已读",
    }


@router.get("/unread-count")
async def get_unread_count(request: Request):
    """
    获取总未读消息数和最新未读消息（用于通知）
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    # 查询包含当前用户的所有会话
    chats = await db.query(
        "private_chats",
        {"participants": openid},
        limit=1000,
    )
    
    total_unread = 0
    for chat in chats:
        unread = chat.get("unreadCount", {}).get(openid, 0) or 0
        total_unread += unread
    
    # 获取最新的未读消息（用于弹出通知）
    # 只获取最近1分钟内收到的未读消息
    from datetime import datetime, timezone, timedelta
    one_minute_ago = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    
    new_messages = []
    try:
        # 查询最近收到的未读消息
        recent_messages = await db.query(
            "private_messages",
            {
                "receiverOpenid": openid,
                "isRead": False,
                "createdAt": {"$gte": {"$date": one_minute_ago}},
            },
            sort=[("createdAt", -1)],
            limit=5,
        )
        
        # 获取发送者信息
        for msg in recent_messages:
            sender_openid = msg.get("senderOpenid")
            if sender_openid:
                # 获取发送者用户信息
                sender = await db.get_one("users", {"openid": sender_openid})
                if sender:
                    msg["senderNickName"] = sender.get("nickName", "学友")
                    msg["senderAvatarUrl"] = sender.get("avatarUrl", "")
                new_messages.append(msg)
    except Exception as e:
        print(f"获取新消息失败: {e}")
    
    return {
        "success": True,
        "data": {
            "totalUnread": total_unread,
            "unreadCount": total_unread,  # 兼容旧版本
            "newMessages": new_messages,
        }
    }


@router.post("/start")
async def start_conversation(request: Request):
    """
    开始/获取与某个学友的会话
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
        raise HTTPException(status_code=400, detail="只能与学友聊天")
    
    # 获取或创建会话
    chat = await _get_or_create_chat(db, openid, friend_openid)
    chat_id = str(chat.get("_id") or chat.get("id"))
    
    # 获取对方信息
    friend_info = await _get_user_info(db, friend_openid)
    
    return {
        "success": True,
        "data": {
            "chatId": chat_id,
            "friendInfo": friend_info,
        }
    }


@router.post("/share-progress")
async def share_progress(request: Request):
    """
    分享学习进度给学友
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    try:
        body = await request.json()
    except:
        body = {}
    
    receiver_openid = body.get("receiverOpenid")
    if not receiver_openid:
        raise HTTPException(status_code=400, detail="缺少 receiverOpenid")
    
    # 检查是否是学友
    friendship = await db.get_one(
        "friendships",
        {
            "$or": [
                {"openid": openid, "friendOpenid": receiver_openid, "status": "accepted"},
                {"openid": receiver_openid, "friendOpenid": openid, "status": "accepted"},
            ]
        }
    )
    
    if not friendship:
        raise HTTPException(status_code=400, detail="只能给学友分享进度")
    
    # 获取当前用户的学习数据
    stats = await db.get_one("user_stats", {"openid": openid})
    plan = await db.get_one("study_plans", {"openid": openid, "status": "active"})
    
    if plan and "data" in plan and isinstance(plan.get("data"), dict):
        plan = {**plan.get("data"), "_id": plan.get("_id")}
    
    # 构建进度信息
    progress_data = {
        "stats": {
            "studyDays": stats.get("studyDays", 0) if stats else 0,
            "totalMinutes": stats.get("totalMinutes", 0) if stats else 0,
            "currentStreak": stats.get("currentStreak", 0) if stats else 0,
            "todayChecked": stats.get("todayChecked", False) if stats else False,
        },
        "plan": None,
    }
    
    if plan:
        progress_data["plan"] = {
            "goal": plan.get("goal", ""),
            "domain": plan.get("domain", ""),
            "domainName": plan.get("domainName", ""),
            "progress": plan.get("progress", 0),
            "todayProgress": plan.get("todayProgress", 0),
        }
    
    # 获取用户信息
    user_info = await _get_user_info(db, openid)
    
    # 构建消息内容
    content_parts = []
    content_parts.append(f"📊 我的学习进度")
    content_parts.append(f"📅 累计学习 {progress_data['stats']['studyDays']} 天")
    content_parts.append(f"⏱️ 总学习 {progress_data['stats']['totalMinutes']} 分钟")
    content_parts.append(f"🔥 连续打卡 {progress_data['stats']['currentStreak']} 天")
    
    if progress_data["plan"]:
        content_parts.append(f"📋 当前目标：{progress_data['plan']['goal']}")
        content_parts.append(f"📈 计划进度：{progress_data['plan']['progress']}%")
    
    content = "\n".join(content_parts)
    
    # 获取或创建会话
    chat = await _get_or_create_chat(db, openid, receiver_openid)
    chat_id = str(chat.get("_id") or chat.get("id"))
    
    # 发送消息
    now = datetime.now(timezone.utc).isoformat()
    message = {
        "chatId": chat_id,
        "senderOpenid": openid,
        "receiverOpenid": receiver_openid,
        "content": content,
        "messageType": "text",
        "reference": {
            "type": "progress",
            "data": progress_data,
        },
        "isRead": False,
        "createdAt": {"$date": now},
    }
    
    message_id = await db.add("private_messages", message)
    message["_id"] = message_id
    message["senderInfo"] = user_info
    
    # 更新会话
    current_unread = chat.get("unreadCount", {}).get(receiver_openid, 0) or 0
    await db.update_by_id(
        "private_chats",
        chat_id,
        {
            "lastMessage": {
                "content": "📊 分享了学习进度",
                "senderOpenid": openid,
                "messageType": "text",
            },
            "lastMessageAt": {"$date": now},
            f"unreadCount.{receiver_openid}": current_unread + 1,
            "updatedAt": {"$date": now},
        }
    )
    
    return {
        "success": True,
        "message": "进度已分享",
        "data": {
            "message": message,
        }
    }


@router.post("/delete-conversation")
async def delete_conversation(request: Request, body: DeleteConversationRequest):
    """
    删除会话（仅从自己的列表中隐藏）
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    chat_id = body.chatId
    
    # 验证会话权限
    chat = await db.get_by_id("private_chats", chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    if openid not in chat.get("participants", []):
        raise HTTPException(status_code=403, detail="无权操作此会话")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # 标记用户删除了此会话（软删除）
    deleted_by = chat.get("deletedBy", [])
    if openid not in deleted_by:
        deleted_by.append(openid)
    
    await db.update_by_id(
        "private_chats",
        chat_id,
        {
            "deletedBy": deleted_by,
            "updatedAt": {"$date": now},
        }
    )
    
    return {
        "success": True,
        "message": "会话已删除",
    }


@router.post("/clear-history")
async def clear_chat_history(request: Request, body: ClearChatRequest):
    """
    清空聊天记录（仅清空自己能看到的）
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    chat_id = body.chatId
    
    # 验证会话权限
    chat = await db.get_by_id("private_chats", chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    if openid not in chat.get("participants", []):
        raise HTTPException(status_code=403, detail="无权操作此会话")
    
    now = datetime.now(timezone.utc).isoformat()
    
    # 记录用户清空聊天的时间点，之前的消息不再显示
    await db.update_by_id(
        "private_chats",
        chat_id,
        {
            f"clearedAt.{openid}": {"$date": now},
            "updatedAt": {"$date": now},
        }
    )
    
    return {
        "success": True,
        "message": "聊天记录已清空",
    }


@router.post("/recall")
async def recall_message(request: Request, body: RecallMessageRequest):
    """
    撤回消息（2分钟内可撤回）
    """
    openid = _get_openid_from_request(request)
    db = get_db()
    
    message_id = body.messageId
    
    # 获取消息
    message = await db.get_by_id("private_messages", message_id)
    if not message:
        raise HTTPException(status_code=404, detail="消息不存在")
    
    # 验证是否是发送者
    if message.get("senderOpenid") != openid:
        raise HTTPException(status_code=403, detail="只能撤回自己发送的消息")
    
    # 验证时间（2分钟内）
    created_at = message.get("createdAt")
    if isinstance(created_at, dict) and "$date" in created_at:
        created_at = created_at["$date"]
    
    if created_at:
        msg_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = (now - msg_time).total_seconds()
        
        if diff > 120:  # 2分钟
            raise HTTPException(status_code=400, detail="消息发送超过2分钟，无法撤回")
    
    now_str = datetime.now(timezone.utc).isoformat()
    
    # 标记消息为已撤回
    await db.update_by_id(
        "private_messages",
        message_id,
        {
            "isRecalled": True,
            "recalledAt": {"$date": now_str},
            "originalContent": message.get("content"),
            "originalMessageType": message.get("messageType"),
            "content": "",
            "messageType": "recalled",
        }
    )
    
    # 更新会话的最后消息（如果这是最后一条消息）
    chat_id = message.get("chatId")
    chat = await db.get_by_id("private_chats", chat_id)
    
    if chat:
        last_msg = chat.get("lastMessage", {})
        # 简单检查：如果最后消息是撤回的消息（通过发送者判断）
        if last_msg and last_msg.get("senderOpenid") == openid:
            await db.update_by_id(
                "private_chats",
                chat_id,
                {
                    "lastMessage": {
                        "content": "撤回了一条消息",
                        "senderOpenid": openid,
                        "messageType": "recalled",
                    },
                    "updatedAt": {"$date": now_str},
                }
            )
    
    return {
        "success": True,
        "message": "消息已撤回",
    }

