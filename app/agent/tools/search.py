"""
搜索相关工具
"""

import json
from typing import Optional, Type, List
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool

from ...config import settings


class SearchResourcesInput(BaseModel):
    """搜索资源的输入参数"""
    query: str = Field(description="搜索关键词")
    max_results: int = Field(default=5, description="最大返回结果数")


class SearchResourcesTool(BaseTool):
    """联网搜索学习资源"""
    
    name: str = "search_resources"
    description: str = """联网搜索学习相关的资源和信息。
    当用户需要查找学习资料、了解某个概念、或获取最新信息时使用此工具。
    可以搜索教程、文档、视频、文章等各类学习资源。"""
    args_schema: Type[BaseModel] = SearchResourcesInput
    
    def _run(self, query: str, max_results: int = 5) -> str:
        """同步执行"""
        import asyncio
        return asyncio.run(self._arun(query, max_results))
    
    async def _arun(self, query: str, max_results: int = 5) -> str:
        """异步搜索"""
        try:
            # 这里集成 Tavily 搜索 API
            if settings.TAVILY_API_KEY:
                from tavily import TavilyClient
                
                client = TavilyClient(api_key=settings.TAVILY_API_KEY)
                response = client.search(
                    query=query,
                    search_depth="basic",
                    max_results=max_results,
                )
                
                results = []
                for item in response.get("results", []):
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("content", "")[:200],
                    })
                
                if results:
                    output = "🔍 搜索结果：\n\n"
                    for i, r in enumerate(results, 1):
                        output += f"{i}. **{r['title']}**\n"
                        output += f"   {r['snippet']}...\n"
                        output += f"   🔗 {r['url']}\n\n"
                    return output
                else:
                    return "未找到相关结果，请尝试其他关键词。"
            else:
                return "搜索服务暂不可用（未配置 API Key）"
                
        except Exception as e:
            return f"搜索失败: {str(e)}"


class SearchLearningMaterialsInput(BaseModel):
    """搜索学习材料的输入参数"""
    topic: str = Field(description="学习主题")
    material_type: str = Field(
        default="all",
        description="资料类型：video(视频)/article(文章)/tutorial(教程)/book(书籍)/all(全部)"
    )
    difficulty: str = Field(
        default="all",
        description="难度级别：beginner/intermediate/advanced/all"
    )


class SearchLearningMaterialsTool(BaseTool):
    """搜索特定类型的学习材料"""
    
    name: str = "search_learning_materials"
    description: str = """搜索特定类型和难度的学习材料。
    当用户需要特定类型（如视频教程、入门书籍）的学习资源时使用。
    可以按资料类型和难度级别筛选。"""
    args_schema: Type[BaseModel] = SearchLearningMaterialsInput
    
    def _run(self, topic: str, material_type: str = "all", difficulty: str = "all") -> str:
        import asyncio
        return asyncio.run(self._arun(topic, material_type, difficulty))
    
    async def _arun(
        self,
        topic: str,
        material_type: str = "all",
        difficulty: str = "all",
    ) -> str:
        """异步搜索学习材料"""
        
        # 构建搜索查询
        type_keywords = {
            "video": "视频教程 video tutorial",
            "article": "文章 article blog",
            "tutorial": "教程 tutorial guide",
            "book": "书籍 book 推荐",
            "all": "",
        }
        
        difficulty_keywords = {
            "beginner": "入门 初学者 beginner",
            "intermediate": "进阶 intermediate",
            "advanced": "高级 advanced",
            "all": "",
        }
        
        query_parts = [topic]
        if material_type in type_keywords:
            query_parts.append(type_keywords[material_type])
        if difficulty in difficulty_keywords:
            query_parts.append(difficulty_keywords[difficulty])
        
        query = " ".join(filter(None, query_parts))
        
        try:
            if settings.TAVILY_API_KEY:
                from tavily import TavilyClient
                
                client = TavilyClient(api_key=settings.TAVILY_API_KEY)
                response = client.search(
                    query=query,
                    search_depth="advanced",
                    max_results=8,
                )
                
                results = response.get("results", [])
                
                if results:
                    output = f"📚 {topic} 学习资料推荐：\n\n"
                    for i, item in enumerate(results[:5], 1):
                        output += f"{i}. **{item.get('title', '')}**\n"
                        output += f"   {item.get('content', '')[:150]}...\n"
                        output += f"   🔗 {item.get('url', '')}\n\n"
                    return output
                else:
                    return f"未找到关于 {topic} 的学习资料。"
            else:
                return "搜索服务暂不可用"
                
        except Exception as e:
            return f"搜索失败: {str(e)}"

