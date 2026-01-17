"""
MCP (Model Context Protocol) endpoint to expose FastAPI tools to CloudBase AI Agent.
Implements minimal JSON-RPC handling for initialize, tools/list, tools/call, ping.
"""
from __future__ import annotations

import json
import os
from urllib.parse import quote
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
import httpx

from app.config import get_http_client_kwargs

router = APIRouter()


TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "create_learning_plan",
        "description": "Create a personalized learning plan.",
        "inputSchema": {
            "type": "object",
            "required": ["openid", "goal", "domain"],
            "properties": {
                "openid": {"type": "string", "description": "User openid"},
                "goal": {"type": "string", "description": "Learning goal"},
                "domain": {"type": "string", "description": "Learning domain"},
                "daily_hours": {"type": "number", "description": "Daily hours", "default": 2},
                "current_level": {
                    "type": "string",
                    "description": "beginner/intermediate/advanced",
                    "default": "beginner",
                },
                "deadline": {
                    "type": "string",
                    "description": "YYYY-MM-DD",
                },
                "preferences": {
                    "type": "object",
                    "description": "Optional preferences",
                },
            },
        },
    },
    {
        "name": "get_today_tasks",
        "description": "Ensure today tasks exist and return them.",
        "inputSchema": {
            "type": "object",
            "required": ["openid"],
            "properties": {
                "openid": {"type": "string", "description": "User openid"},
            },
        },
    },
    {
        "name": "do_checkin",
        "description": "Perform daily check-in for user.",
        "inputSchema": {
            "type": "object",
            "required": ["openid"],
            "properties": {
                "openid": {"type": "string", "description": "User openid"},
            },
        },
    },
    {
        "name": "get_mistakes",
        "description": "List mistakes with optional filters.",
        "inputSchema": {
            "type": "object",
            "required": ["openid"],
            "properties": {
                "openid": {"type": "string", "description": "User openid"},
                "tag": {"type": "string", "description": "Filter by tag"},
                "status": {
                    "type": "string",
                    "description": "all/pending/mastered",
                    "default": "all",
                },
                "page": {"type": "number", "description": "Page index", "default": 0},
                "pageSize": {"type": "number", "description": "Page size", "default": 20},
            },
        },
    },
    {
        "name": "get_learning_stats",
        "description": "Get learning stats summary.",
        "inputSchema": {
            "type": "object",
            "required": ["openid"],
            "properties": {
                "openid": {"type": "string", "description": "User openid"},
                "period": {
                    "type": "string",
                    "description": "today/week/month/all",
                    "default": "today",
                },
            },
        },
    },
]


def _jsonrpc_result(message_id: Union[str, int], result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _jsonrpc_error(
    message_id: Optional[Union[str, int]],
    code: int,
    message: str,
    data: Optional[Any] = None,
) -> Dict[str, Any]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": message_id, "error": error}


def _text_content(value: Any) -> Dict[str, Any]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}]}


async def _call_fastapi(path: str, *, method: str, data: Optional[Dict[str, Any]], openid: str) -> Any:
    headers = {"content-type": "application/json", "x-wx-openid": openid}
    base_url = os.getenv("MCP_INTERNAL_BASE_URL", "http://127.0.0.1:80")
    url = f"{base_url}{path}"
    async with httpx.AsyncClient(**get_http_client_kwargs(timeout=30.0)) as client:
        if method.upper() == "GET":
            resp = await client.get(url, headers=headers)
        else:
            resp = await client.request(method.upper(), url, headers=headers, json=data or {})
    payload = None
    try:
        payload = resp.json()
    except Exception:
        payload = {"error": resp.text}
    if not resp.is_success:
        raise RuntimeError(f"FastAPI {resp.status_code}: {payload}")
    return payload


async def _handle_tool_call(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    openid = args.get("openid")
    if not openid:
        raise ValueError("Missing openid")

    if tool_name == "create_learning_plan":
        payload = {
            "goal": args.get("goal"),
            "domain": args.get("domain"),
            "daily_hours": args.get("daily_hours", 2),
            "current_level": args.get("current_level", "beginner"),
            "deadline": args.get("deadline"),
            "preferences": args.get("preferences"),
        }
        result = await _call_fastapi("/api/plan/generate", method="POST", data=payload, openid=openid)
        return _text_content(result)

    if tool_name == "get_today_tasks":
        result = await _call_fastapi("/api/tasks/today/ensure", method="POST", data={}, openid=openid)
        return _text_content(result)

    if tool_name == "do_checkin":
        result = await _call_fastapi("/api/agent-tools/checkin", method="POST", data={}, openid=openid)
        return _text_content(result)

    if tool_name == "get_mistakes":
        payload = {
            "tag": args.get("tag"),
            "status": args.get("status", "all"),
            "page": args.get("page", 0),
            "pageSize": args.get("pageSize", 20),
        }
        result = await _call_fastapi("/api/mistakes/list", method="POST", data=payload, openid=openid)
        return _text_content(result)

    if tool_name == "get_learning_stats":
        period = args.get("period", "today")
        result = await _call_fastapi(
            f"/api/agent-tools/stats?period={quote(str(period))}",
            method="GET",
            data=None,
            openid=openid,
        )
        return _text_content(result)

    raise ValueError(f"Unknown tool: {tool_name}")


@router.post("/messages")
async def mcp_messages(request: Request):
    """
    Minimal MCP JSON-RPC endpoint for PostClientTransport.
    """
    try:
        body = await request.json()
    except Exception as exc:
        return JSONResponse(_jsonrpc_error(None, -32700, "Parse error", str(exc)), status_code=400)

    messages: List[Dict[str, Any]] = body if isinstance(body, list) else [body]
    responses: List[Dict[str, Any]] = []

    for message in messages:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            responses.append(_jsonrpc_error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request"))
            continue

        method = message.get("method")
        message_id = message.get("id")

        if message_id is None:
            # Notification: no response required.
            continue

        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fastapi-mcp", "version": "1.0.0"},
                "instructions": "Use tools/list to discover tools and tools/call to invoke them.",
            }
            responses.append(_jsonrpc_result(message_id, result))
            continue

        if method == "tools/list":
            responses.append(_jsonrpc_result(message_id, {"tools": TOOL_SCHEMAS}))
            continue

        if method == "tools/call":
            params = message.get("params") or {}
            tool_name = params.get("name")
            args = params.get("arguments") or {}
            try:
                result = await _handle_tool_call(tool_name, args)
                responses.append(_jsonrpc_result(message_id, result))
            except Exception as exc:
                responses.append(_jsonrpc_error(message_id, -32602, "Tool call failed", str(exc)))
            continue

        if method == "ping":
            responses.append(_jsonrpc_result(message_id, {}))
            continue

        responses.append(_jsonrpc_error(message_id, -32601, f"Method not found: {method}"))

    if not responses:
        return Response(status_code=202)
    if len(responses) == 1:
        return JSONResponse(responses[0])
    return JSONResponse(responses)
