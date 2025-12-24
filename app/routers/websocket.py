"""
WebSocket 实时消息通道

功能：
- 用户连接管理
- 实时消息推送
- 未读消息数更新
- 已读状态同步
"""
import json
import asyncio
from datetime import datetime, timezone
from typing import Dict, Set, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from ..db.wxcloud import get_db

router = APIRouter(prefix="/ws", tags=["WebSocket"])


class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        # openid -> set of WebSocket connections (一个用户可能多个设备连接)
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # WebSocket -> openid 反向映射
        self.connection_user: Dict[WebSocket, str] = {}
        # 锁，用于线程安全操作
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, openid: str):
        """接受新连接"""
        await websocket.accept()
        async with self._lock:
            if openid not in self.active_connections:
                self.active_connections[openid] = set()
            self.active_connections[openid].add(websocket)
            self.connection_user[websocket] = openid
        print(f"[WebSocket] 用户 {openid[:8]}... 已连接，当前连接数: {len(self.active_connections[openid])}")
    
    async def disconnect(self, websocket: WebSocket):
        """断开连接"""
        async with self._lock:
            openid = self.connection_user.get(websocket)
            if openid:
                if openid in self.active_connections:
                    self.active_connections[openid].discard(websocket)
                    if not self.active_connections[openid]:
                        del self.active_connections[openid]
                del self.connection_user[websocket]
                print(f"[WebSocket] 用户 {openid[:8]}... 已断开")
    
    async def send_to_user(self, openid: str, message: dict):
        """发送消息给指定用户的所有连接"""
        if openid in self.active_connections:
            disconnected = []
            for connection in self.active_connections[openid]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    print(f"[WebSocket] 发送消息失败: {e}")
                    disconnected.append(connection)
            
            # 清理断开的连接
            for conn in disconnected:
                await self.disconnect(conn)
    
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
    if not openid:
        await websocket.close(code=4001, reason="Missing openid")
        return
    
    await manager.connect(websocket, openid)
    
    try:
        # 发送连接成功消息和当前未读数
        db = get_db()
        total_unread = await get_unread_count(db, openid)
        
        await websocket.send_json({
            "type": "connected",
            "totalUnread": total_unread,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        
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
                
                if msg_type == "ping":
                    # 心跳响应
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                
                elif msg_type == "enter_chat":
                    # 进入聊天，记录当前查看的会话
                    current_chat_id = data.get("chatId")
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
                    current_chat_id = None
                
                elif msg_type == "mark_read":
                    # 手动标记已读
                    chat_id = data.get("chatId")
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
                try:
                    await websocket.send_json({"type": "ping"})
                except:
                    break
                    
    except WebSocketDisconnect:
        print(f"[WebSocket] 用户 {openid[:8]}... 主动断开")
    except Exception as e:
        print(f"[WebSocket] 错误: {e}")
    finally:
        await manager.disconnect(websocket)


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

