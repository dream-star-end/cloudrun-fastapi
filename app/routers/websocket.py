"""
WebSocket 实时消息通道

功能：
- 用户连接管理
- 实时消息推送
- 未读消息数更新
- 已读状态同步
- 学友请求通知
- 监督/学伴邀请通知
- 监督提醒推送
- 社区互动通知（点赞、评论）
"""
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Set, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from ..db.wxcloud import get_db

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

router = APIRouter(prefix="/ws", tags=["WebSocket"])


class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        # openid -> set of WebSocket connections (一个用户可能多个设备连接)
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # WebSocket -> openid 反向映射
        self.connection_user: Dict[WebSocket, str] = {}
        # 用户最后活跃时间 openid -> datetime
        self.last_active_time: Dict[str, datetime] = {}
        # 锁，用于线程安全操作
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, openid: str):
        """接受新连接"""
        logger.info(f"[WebSocket] 开始接受连接: openid={openid[:8]}...")
        try:
            await websocket.accept()
            logger.info(f"[WebSocket] accept() 完成: openid={openid[:8]}...")
        except Exception as e:
            logger.error(f"[WebSocket] accept() 失败: openid={openid[:8]}..., error={type(e).__name__}: {e}")
            raise
        
        was_offline = openid not in self.active_connections or len(self.active_connections.get(openid, set())) == 0
        
        async with self._lock:
            if openid not in self.active_connections:
                self.active_connections[openid] = set()
            self.active_connections[openid].add(websocket)
            self.connection_user[websocket] = openid
            self.last_active_time[openid] = datetime.now(timezone.utc)
        
        logger.info(f"[WebSocket] 用户 {openid[:8]}... 已连接，当前连接数: {len(self.active_connections[openid])}, 总在线用户: {len(self.active_connections)}")
        
        # 如果用户从离线变为在线，通知其学友
        if was_offline:
            asyncio.create_task(self._notify_friends_online_status(openid, True))
    
    async def disconnect(self, websocket: WebSocket):
        """断开连接"""
        openid = None
        is_now_offline = False
        
        async with self._lock:
            openid = self.connection_user.get(websocket)
            if openid:
                if openid in self.active_connections:
                    self.active_connections[openid].discard(websocket)
                    if not self.active_connections[openid]:
                        del self.active_connections[openid]
                        is_now_offline = True
                        # 更新最后活跃时间
                        self.last_active_time[openid] = datetime.now(timezone.utc)
                del self.connection_user[websocket]
                logger.info(f"[WebSocket] 用户 {openid[:8]}... 已断开, 完全离线: {is_now_offline}, 剩余在线用户: {len(self.active_connections)}")
        
        # 如果用户完全离线，通知其学友
        if openid and is_now_offline:
            asyncio.create_task(self._notify_friends_online_status(openid, False))
    
    async def _notify_friends_online_status(self, openid: str, is_online: bool):
        """通知用户的学友其在线状态变化"""
        try:
            logger.debug(f"[WebSocket] 通知学友在线状态: openid={openid[:8]}..., is_online={is_online}")
            db = get_db()
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
            logger.debug(f"[WebSocket] 找到 {len(friendships)} 个学友关系")
            
            # 获取用户信息
            user_info = await get_user_info(db, openid)
            last_active = self.last_active_time.get(openid)
            last_active_str = last_active.isoformat() if last_active else None
            
            # 通知每个在线的学友
            notified_count = 0
            for f in friendships:
                friend_openid = f.get("friendOpenid") if f.get("openid") == openid else f.get("openid")
                if friend_openid and self.is_user_online(friend_openid):
                    await self.send_to_user(friend_openid, {
                        "type": "friend_status_change",
                        "data": {
                            "friendOpenid": openid,
                            "friendInfo": user_info,
                            "isOnline": is_online,
                            "lastActiveAt": last_active_str,
                        },
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                    notified_count += 1
            logger.debug(f"[WebSocket] 已通知 {notified_count} 个在线学友")
        except Exception as e:
            logger.error(f"[WebSocket] 通知学友在线状态失败: {type(e).__name__}: {e}")
    
    async def send_to_user(self, openid: str, message: dict):
        """发送消息给指定用户的所有连接"""
        if openid in self.active_connections:
            disconnected = []
            conn_count = len(self.active_connections[openid])
            logger.debug(f"[WebSocket] 发送消息给 {openid[:8]}..., 连接数: {conn_count}, type: {message.get('type')}")
            for connection in self.active_connections[openid]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.warning(f"[WebSocket] 发送消息失败: {type(e).__name__}: {e}")
                    disconnected.append(connection)
            
            # 清理断开的连接
            for conn in disconnected:
                await self.disconnect(conn)
        else:
            logger.debug(f"[WebSocket] 用户 {openid[:8]}... 不在线，跳过发送")
    
    async def broadcast_to_users(self, openids: list, message: dict):
        """广播消息给多个用户"""
        for openid in openids:
            await self.send_to_user(openid, message)
    
    def is_user_online(self, openid: str) -> bool:
        """检查用户是否在线"""
        return openid in self.active_connections and len(self.active_connections[openid]) > 0
    
    def get_online_users(self) -> list:
        """获取所有在线用户"""
        return list(self.active_connections.keys())
    
    def get_user_last_active(self, openid: str) -> Optional[datetime]:
        """获取用户最后活跃时间"""
        return self.last_active_time.get(openid)
    
    def get_users_online_status(self, openids: list) -> dict:
        """批量获取用户在线状态"""
        result = {}
        for openid in openids:
            is_online = self.is_user_online(openid)
            last_active = self.last_active_time.get(openid)
            result[openid] = {
                "isOnline": is_online,
                "lastActiveAt": last_active.isoformat() if last_active else None,
            }
        return result
    
    async def update_user_activity(self, openid: str):
        """更新用户活跃时间"""
        async with self._lock:
            self.last_active_time[openid] = datetime.now(timezone.utc)


# 全局连接管理器
manager = ConnectionManager()


async def get_user_info(db, openid: str) -> dict:
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


async def get_unread_count(db, openid: str) -> int:
    """获取用户未读消息总数"""
    chats = await db.query(
        "private_chats",
        {"participants": openid},
        limit=1000,
    )
    
    total = 0
    for chat in chats:
        unread = chat.get("unreadCount", {}).get(openid, 0) or 0
        total += unread
    
    return total


async def get_friends_online_status(db, openid: str) -> dict:
    """获取用户所有学友的在线状态"""
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
    
    # 收集学友的 openid
    friend_openids = []
    for f in friendships:
        friend_openid = f.get("friendOpenid") if f.get("openid") == openid else f.get("openid")
        if friend_openid:
            friend_openids.append(friend_openid)
    
    # 批量获取在线状态
    return manager.get_users_online_status(friend_openids)


@router.websocket("/chat")
async def websocket_endpoint(
    websocket: WebSocket,
    openid: str = Query(..., description="用户openid")
):
    """
    WebSocket 聊天端点
    
    连接参数：
    - openid: 用户的openid（必需）
    
    消息格式（客户端发送）：
    - ping: {"type": "ping"}
    - 进入聊天: {"type": "enter_chat", "chatId": "xxx"}
    - 离开聊天: {"type": "leave_chat"}
    - 标记已读: {"type": "mark_read", "chatId": "xxx"}
    
    消息格式（服务端推送）：
    - pong: {"type": "pong", "timestamp": "xxx"}
    - 新消息: {"type": "new_message", "message": {...}, "chatId": "xxx"}
    - 未读数更新: {"type": "unread_update", "totalUnread": 10, "chatUnread": {"chatId": 5}}
    - 已读更新: {"type": "read_update", "chatId": "xxx", "readAt": "xxx"}
    - 连接成功: {"type": "connected", "totalUnread": 10}
    """
    logger.info(f"[WebSocket] 收到连接请求: openid={openid[:8] if openid else 'None'}...")
    
    if not openid:
        logger.warning("[WebSocket] 拒绝连接: 缺少 openid")
        await websocket.close(code=4001, reason="Missing openid")
        return
    
    try:
        await manager.connect(websocket, openid)
    except Exception as e:
        logger.error(f"[WebSocket] 连接失败: {type(e).__name__}: {e}")
        return
    
    try:
        # 发送连接成功消息和当前未读数
        logger.debug(f"[WebSocket] 开始获取用户数据: openid={openid[:8]}...")
        db = get_db()
        
        try:
            total_unread = await get_unread_count(db, openid)
            logger.debug(f"[WebSocket] 未读数: {total_unread}")
        except Exception as e:
            logger.error(f"[WebSocket] 获取未读数失败: {type(e).__name__}: {e}")
            total_unread = 0
        
        try:
            # 获取学友的在线状态
            friends_status = await get_friends_online_status(db, openid)
            logger.debug(f"[WebSocket] 学友在线状态: {len(friends_status)} 个学友")
        except Exception as e:
            logger.error(f"[WebSocket] 获取学友在线状态失败: {type(e).__name__}: {e}")
            friends_status = {}
        
        connected_msg = {
            "type": "connected",
            "totalUnread": total_unread,
            "friendsStatus": friends_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(f"[WebSocket] 发送 connected 消息: openid={openid[:8]}..., unread={total_unread}")
        await websocket.send_json(connected_msg)
        
        # 当前用户正在查看的聊天
        current_chat_id = None
        
        while True:
            try:
                # 接收消息，设置超时避免长时间阻塞
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=60.0  # 60秒超时
                )
                
                msg_type = data.get("type")
                logger.debug(f"[WebSocket] 收到消息: openid={openid[:8]}..., type={msg_type}")
                
                if msg_type == "ping":
                    # 心跳响应
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                
                elif msg_type == "enter_chat":
                    # 进入聊天，记录当前查看的会话
                    current_chat_id = data.get("chatId")
                    logger.debug(f"[WebSocket] 进入聊天: chatId={current_chat_id}")
                    if current_chat_id:
                        # 自动标记已读
                        await mark_chat_read(db, openid, current_chat_id)
                        # 推送更新后的未读数
                        total_unread = await get_unread_count(db, openid)
                        await websocket.send_json({
                            "type": "unread_update",
                            "totalUnread": total_unread,
                        })
                
                elif msg_type == "leave_chat":
                    # 离开聊天
                    logger.debug(f"[WebSocket] 离开聊天: chatId={current_chat_id}")
                    current_chat_id = None
                
                elif msg_type == "mark_read":
                    # 手动标记已读
                    chat_id = data.get("chatId")
                    logger.debug(f"[WebSocket] 标记已读: chatId={chat_id}")
                    if chat_id:
                        await mark_chat_read(db, openid, chat_id)
                        # 推送更新后的未读数
                        total_unread = await get_unread_count(db, openid)
                        await websocket.send_json({
                            "type": "unread_update",
                            "totalUnread": total_unread,
                        })
                
            except asyncio.TimeoutError:
                # 超时，发送心跳检测
                logger.debug(f"[WebSocket] 接收超时，发送心跳: openid={openid[:8]}...")
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception as e:
                    logger.warning(f"[WebSocket] 发送心跳失败: {type(e).__name__}: {e}")
                    break
                    
    except WebSocketDisconnect as e:
        logger.info(f"[WebSocket] 用户 {openid[:8]}... 主动断开, code={e.code}")
    except Exception as e:
        logger.error(f"[WebSocket] 错误: {type(e).__name__}: {e}")
    finally:
        await manager.disconnect(websocket)
        logger.info(f"[WebSocket] 连接清理完成: openid={openid[:8]}...")


async def mark_chat_read(db, openid: str, chat_id: str):
    """标记会话已读"""
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
    
    # 通知发送者消息已读
    chat = await db.get_by_id("private_chats", chat_id)
    if chat:
        participants = chat.get("participants", [])
        for p in participants:
            if p != openid:
                await manager.send_to_user(p, {
                    "type": "read_update",
                    "chatId": chat_id,
                    "readBy": openid,
                    "readAt": now,
                })
                break


async def notify_new_message(message: dict, sender_openid: str, receiver_openid: str):
    """
    通知新消息
    
    这个函数会被 chat_private.py 的 send_message 调用
    """
    db = get_db()
    
    # 获取发送者信息
    sender_info = await get_user_info(db, sender_openid)
    
    # 获取接收者的未读总数
    total_unread = await get_unread_count(db, receiver_openid)
    
    # 推送给接收者
    await manager.send_to_user(receiver_openid, {
        "type": "new_message",
        "message": {
            **message,
            "senderInfo": sender_info,
        },
        "chatId": message.get("chatId"),
        "totalUnread": total_unread,
    })
    
    # 同时推送给发送者（用于多设备同步）
    await manager.send_to_user(sender_openid, {
        "type": "message_sent",
        "message": message,
        "chatId": message.get("chatId"),
    })


async def notify_message_recalled(chat_id: str, message_id: str, participants: list):
    """
    通知消息撤回
    """
    for openid in participants:
        await manager.send_to_user(openid, {
            "type": "message_recalled",
            "chatId": chat_id,
            "messageId": message_id,
        })


def get_connection_manager() -> ConnectionManager:
    """获取连接管理器实例"""
    return manager


# ==================== 学习社区实时通知 ====================

async def notify_friend_request(from_openid: str, to_openid: str, friendship: dict):
    """
    通知新的学友请求
    
    Args:
        from_openid: 发送请求的用户
        to_openid: 接收请求的用户
        friendship: 好友关系数据
    """
    db = get_db()
    from_user = await get_user_info(db, from_openid)
    
    await manager.send_to_user(to_openid, {
        "type": "friend_request",
        "data": {
            "friendshipId": str(friendship.get("_id") or friendship.get("id")),
            "fromUser": from_user,
            "remark": friendship.get("remark", ""),
            "createdAt": friendship.get("createdAt"),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def notify_friend_request_handled(friendship_id: str, handler_openid: str, requester_openid: str, action: str):
    """
    通知学友请求处理结果
    
    Args:
        friendship_id: 好友关系ID
        handler_openid: 处理请求的用户
        requester_openid: 发起请求的用户
        action: accept 或 reject
    """
    db = get_db()
    handler_info = await get_user_info(db, handler_openid)
    
    await manager.send_to_user(requester_openid, {
        "type": "friend_request_handled",
        "data": {
            "friendshipId": friendship_id,
            "handler": handler_info,
            "action": action,
            "accepted": action == "accept",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def notify_supervisor_invite(from_openid: str, to_openid: str, relation: dict):
    """
    通知监督邀请
    
    Args:
        from_openid: 发起邀请的用户（被监督者）
        to_openid: 被邀请的用户（监督者）
        relation: 监督关系数据
    """
    db = get_db()
    from_user = await get_user_info(db, from_openid)
    
    await manager.send_to_user(to_openid, {
        "type": "supervisor_invite",
        "data": {
            "relationId": str(relation.get("_id") or relation.get("id")),
            "fromUser": from_user,
            "message": relation.get("inviteMessage", ""),
            "planId": relation.get("planId"),
            "createdAt": relation.get("createdAt"),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def notify_supervisor_invite_handled(relation_id: str, handler_openid: str, inviter_openid: str, action: str):
    """
    通知监督邀请处理结果
    """
    db = get_db()
    handler_info = await get_user_info(db, handler_openid)
    
    await manager.send_to_user(inviter_openid, {
        "type": "supervisor_invite_handled",
        "data": {
            "relationId": relation_id,
            "handler": handler_info,
            "action": action,
            "accepted": action == "accept",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def notify_buddy_invite(from_openid: str, to_openid: str, relation: dict, plan: dict = None):
    """
    通知学伴邀请
    
    Args:
        from_openid: 发起邀请的用户（计划所有者）
        to_openid: 被邀请的用户（学伴）
        relation: 学伴关系数据
        plan: 计划信息
    """
    db = get_db()
    from_user = await get_user_info(db, from_openid)
    
    plan_info = None
    if plan:
        plan_info = {
            "goal": plan.get("goal", ""),
            "domain": plan.get("domain", ""),
            "domainName": plan.get("domainName", ""),
            "totalDuration": plan.get("totalDuration", ""),
        }
    
    await manager.send_to_user(to_openid, {
        "type": "buddy_invite",
        "data": {
            "relationId": str(relation.get("_id") or relation.get("id")),
            "fromUser": from_user,
            "message": relation.get("inviteMessage", ""),
            "plan": plan_info,
            "createdAt": relation.get("createdAt"),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def notify_buddy_invite_handled(relation_id: str, handler_openid: str, inviter_openid: str, action: str):
    """
    通知学伴邀请处理结果
    """
    db = get_db()
    handler_info = await get_user_info(db, handler_openid)
    
    await manager.send_to_user(inviter_openid, {
        "type": "buddy_invite_handled",
        "data": {
            "relationId": relation_id,
            "handler": handler_info,
            "action": action,
            "accepted": action == "accept",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def notify_supervisor_reminder(supervisor_openid: str, supervised_openid: str, reminder: dict):
    """
    通知监督提醒（实时推送给被监督者）
    
    Args:
        supervisor_openid: 监督者
        supervised_openid: 被监督者
        reminder: 提醒内容
    """
    db = get_db()
    supervisor_info = await get_user_info(db, supervisor_openid)
    
    reminder_type_text = {
        "daily_checkin": "打卡提醒",
        "task_progress": "学习进度提醒",
        "encouragement": "加油鼓励",
    }
    
    await manager.send_to_user(supervised_openid, {
        "type": "supervisor_reminder",
        "data": {
            "reminderId": str(reminder.get("_id") or reminder.get("id")),
            "supervisor": supervisor_info,
            "reminderType": reminder.get("reminderType"),
            "reminderTypeText": reminder_type_text.get(reminder.get("reminderType"), "提醒"),
            "content": reminder.get("content"),
            "createdAt": reminder.get("createdAt"),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def notify_community_like(liker_openid: str, plan_owner_openid: str, plan: dict):
    """
    通知社区计划被点赞
    
    Args:
        liker_openid: 点赞的用户
        plan_owner_openid: 计划所有者
        plan: 计划信息
    """
    # 不通知自己给自己点赞
    if liker_openid == plan_owner_openid:
        return
    
    db = get_db()
    liker_info = await get_user_info(db, liker_openid)
    
    await manager.send_to_user(plan_owner_openid, {
        "type": "community_like",
        "data": {
            "liker": liker_info,
            "planId": str(plan.get("_id") or plan.get("id")),
            "planTitle": plan.get("title") or plan.get("goal", ""),
            "likeCount": plan.get("likeCount", 0),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def notify_community_comment(commenter_openid: str, plan_owner_openid: str, plan: dict, comment: dict):
    """
    通知社区计划收到评论
    
    Args:
        commenter_openid: 评论的用户
        plan_owner_openid: 计划所有者
        plan: 计划信息
        comment: 评论内容
    """
    # 不通知自己给自己评论
    if commenter_openid == plan_owner_openid:
        return
    
    db = get_db()
    commenter_info = await get_user_info(db, commenter_openid)
    
    await manager.send_to_user(plan_owner_openid, {
        "type": "community_comment",
        "data": {
            "commenter": commenter_info,
            "planId": str(plan.get("_id") or plan.get("id")),
            "planTitle": plan.get("title") or plan.get("goal", ""),
            "commentId": str(comment.get("_id") or comment.get("id")),
            "content": comment.get("content", "")[:50],  # 只发送前50字
            "commentCount": plan.get("commentCount", 0),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def notify_plan_used(user_openid: str, plan_owner_openid: str, plan: dict):
    """
    通知社区计划被使用
    
    Args:
        user_openid: 使用计划的用户
        plan_owner_openid: 计划所有者
        plan: 计划信息
    """
    # 不通知自己使用自己的计划
    if user_openid == plan_owner_openid:
        return
    
    db = get_db()
    user_info = await get_user_info(db, user_openid)
    
    await manager.send_to_user(plan_owner_openid, {
        "type": "plan_used",
        "data": {
            "user": user_info,
            "planId": str(plan.get("_id") or plan.get("id")),
            "planTitle": plan.get("title") or plan.get("goal", ""),
            "useCount": plan.get("useCount", 0),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

