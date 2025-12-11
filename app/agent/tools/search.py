"""
搜索相关工具
基于 LangChain 1.0 的 @tool 装饰器
"""

from langchain_core.tools import tool, BaseTool

from ...config import settings


@tool
async def search_resources(
    query: str,
    max_results: int = 5,
) -> str:
    """联网搜索学习相关的资源和信息。
    
    当用户需要查找学习资料、了解某个概念、或获取最新信息时使用此工具。
    可以搜索教程、文档、视频、文章等各类学习资源。
    
    Args:
        query: 搜索关键词
        max_results: 最大返回结果数，默认5
    
    Returns:
        搜索结果列表
    """
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


def search_resources_tool() -> BaseTool:
    """返回搜索资源工具"""
    return search_resources


@tool
async def search_learning_materials(
    topic: str,
    material_type: str = "all",
    difficulty: str = "all",
) -> str:
    """搜索特定类型和难度的学习材料。
    
    当用户需要特定类型（如视频教程、入门书籍）的学习资源时使用。
    可以按资料类型和难度级别筛选。
    
    Args:
        topic: 学习主题
        material_type: 资料类型 video/article/tutorial/book/all，默认all
        difficulty: 难度级别 beginner/intermediate/advanced/all，默认all
    
    Returns:
        学习材料推荐列表
    """
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


def search_learning_materials_tool() -> BaseTool:
    """返回学习材料搜索工具"""
    return search_learning_materials
