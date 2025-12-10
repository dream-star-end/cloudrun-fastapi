"""
联网搜索服务
使用 Tavily API 进行网络搜索
"""
import httpx
from typing import List, Dict, Optional
from ..config import settings


class SearchService:
    """搜索服务类"""
    
    @classmethod
    async def search(
        cls,
        query: str,
        search_depth: str = "basic",
        max_results: int = 5,
        include_domains: List[str] = None,
    ) -> Dict:
        """
        执行网络搜索
        
        Args:
            query: 搜索关键词
            search_depth: 搜索深度 (basic/advanced)
            max_results: 最大结果数
            include_domains: 限定搜索域名
        
        Returns:
            搜索结果字典
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.TAVILY_BASE_URL}/search",
                json={
                    "api_key": settings.TAVILY_API_KEY,
                    "query": query,
                    "search_depth": search_depth,
                    "include_domains": include_domains or [],
                    "max_results": max_results,
                    "include_answer": True,
                    "include_raw_content": False,
                },
            )
            
            response.raise_for_status()
            data = response.json()
            
            if data.get("results"):
                # 格式化搜索结果
                formatted_results = [
                    {
                        "index": i + 1,
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "content": cls._truncate_content(r.get("content", ""), 300),
                        "score": r.get("score"),
                    }
                    for i, r in enumerate(data["results"])
                ]
                
                return {
                    "success": True,
                    "query": query,
                    "answer": data.get("answer", ""),
                    "results": formatted_results,
                }
            
            return {
                "success": False,
                "query": query,
                "answer": "",
                "results": [],
            }
    
    @classmethod
    async def search_learning_resources(
        cls,
        topic: str,
        resource_type: str = "all",
    ) -> Dict:
        """
        搜索学习资源
        
        Args:
            topic: 学习主题
            resource_type: 资源类型 (all/video/article/course)
        
        Returns:
            学习资源列表
        """
        # 根据资源类型调整搜索词
        search_queries = {
            "video": f"{topic} 教学视频 教程",
            "article": f"{topic} 教程 文章 博客",
            "course": f"{topic} 在线课程 学习",
            "all": f"{topic} 学习资源 教程",
        }
        
        query = search_queries.get(resource_type, search_queries["all"])
        
        # 学习资源相关的域名
        learning_domains = [
            "bilibili.com",
            "zhihu.com",
            "csdn.net",
            "juejin.cn",
            "runoob.com",
            "jianshu.com",
            "cnblogs.com",
        ]
        
        return await cls.search(
            query=query,
            search_depth="basic",
            max_results=8,
            include_domains=learning_domains if resource_type != "all" else [],
        )
    
    @staticmethod
    def _truncate_content(content: str, max_length: int = 300) -> str:
        """截断内容"""
        if len(content) <= max_length:
            return content
        return content[:max_length] + "..."
    
    @classmethod
    def format_search_result_message(cls, result: Dict) -> str:
        """
        将搜索结果格式化为易读的消息
        
        Args:
            result: 搜索结果字典
        
        Returns:
            格式化后的消息字符串
        """
        if not result.get("success"):
            return "❌ 搜索失败，请稍后重试"
        
        message = f"🔍 搜索「{result['query']}」的结果：\n\n"
        
        if result.get("answer"):
            message += f"📝 **摘要**：{result['answer']}\n\n"
        
        message += "📚 **相关资源**：\n"
        
        for r in result.get("results", []):
            message += f"\n{r['index']}. **{r['title']}**\n"
            message += f"   {r['content']}\n"
            message += f"   🔗 {r['url']}\n"
        
        return message

