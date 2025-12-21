"""
DB Proxy client (Python -> Node DB 子服务)

通过环境变量 DB_PROXY_URL 指向 cloudrun-nodedb 的内网地址。
该模块实现与 WxCloudDB 类似的方法签名（get_one/query/add/update/delete...），
以便业务层 Repository 不需要改动。
"""

import os
import json
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class DbProxy:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 10.0):
        self.base_url = (base_url or os.environ.get("DB_PROXY_URL", "")).rstrip("/")
        if not self.base_url:
            raise ValueError("未配置 DB_PROXY_URL（db 子服务内网地址）")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self):
        await self._client.aclose()

    async def _post(self, path: str, payload: Dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        resp = await self._client.post(url, json=payload)
        data = resp.json()
        if resp.status_code >= 400 or not data.get("success", False):
            raise Exception(f"DbProxy 请求失败: {resp.status_code} {json.dumps(data, ensure_ascii=False)}")
        return data.get("data")

    async def query(
        self,
        collection: str,
        query: Dict[str, Any],
        limit: int = 100,
        skip: int = 0,
        order_by: Optional[str] = None,
        order_type: str = "desc",
    ) -> List[Dict[str, Any]]:
        return await self._post(
            "/db/query",
            {
                "collection": collection,
                "where": query,
                "limit": limit,
                "skip": skip,
                "orderBy": order_by,
                "order": "desc" if order_type == "desc" else "asc",
            },
        )

    async def get_one(self, collection: str, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return await self._post("/db/get_one", {"collection": collection, "where": query})

    async def add(self, collection: str, data: Dict[str, Any]) -> str:
        r = await self._post("/db/add", {"collection": collection, "data": data})
        # @cloudbase/node-sdk 返回的字段一般包含 id
        if isinstance(r, dict) and "id" in r:
            return r["id"]
        return ""

    async def update(self, collection: str, query: Dict[str, Any], data: Dict[str, Any]) -> int:
        r = await self._post("/db/update", {"collection": collection, "where": query, "data": data})
        # node-sdk 通常返回 updated/modified 等字段
        if isinstance(r, dict):
            return int(r.get("updated", r.get("modified", 0)) or 0)
        return 0

    async def update_by_id(self, collection: str, doc_id: str, data: Dict[str, Any]) -> bool:
        r = await self._post("/db/update_by_id", {"collection": collection, "doc_id": doc_id, "data": data})
        if isinstance(r, dict):
            return bool((r.get("updated") or r.get("modified") or 0) > 0)
        return False

    async def delete(self, collection: str, query: Dict[str, Any]) -> int:
        r = await self._post("/db/delete", {"collection": collection, "where": query})
        if isinstance(r, dict):
            return int(r.get("deleted", 0) or 0)
        return 0

    async def delete_by_id(self, collection: str, doc_id: str) -> bool:
        r = await self._post("/db/delete_by_id", {"collection": collection, "doc_id": doc_id})
        if isinstance(r, dict):
            return bool((r.get("deleted") or 0) > 0)
        return False





