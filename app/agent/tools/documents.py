"""
文档相关工具
支持 AI Agent 查询和操作用户的学习文档
用于文档伴读功能
"""

import logging
from typing import Optional, TYPE_CHECKING
from langchain_core.tools import tool, BaseTool

from ...db.wxcloud import DocumentRepository

if TYPE_CHECKING:
    from ..memory import AgentMemory

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def create_get_documents_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """获取文档列表工具"""
    
    @tool
    async def get_documents(
        doc_type: Optional[str] = None,
        limit: int = 10,
    ) -> str:
        """获取用户上传的学习文档列表。
        
        当用户询问"我的文档"、"上传过哪些文档"、"文档列表"、"学习资料"时调用此工具。
        
        Args:
            doc_type: 文档类型筛选，可选值：pdf/doc/docx/txt/md（可选）
            limit: 返回数量，默认10
        
        Returns:
            文档列表信息
        """
        logger.info(f"[get_documents] 获取文档列表, user_id={user_id}, type={doc_type}")
        
        try:
            repo = DocumentRepository()
            
            # 获取统计数据
            stats = await repo.get_document_stats(user_id)
            
            # 获取文档列表
            documents = await repo.get_documents(
                user_id, 
                doc_type=doc_type, 
                status="ready",
                limit=limit
            )
            
            total = stats.get("total", 0)
            ready = stats.get("ready", 0)
            total_pages = stats.get("totalPages", 0)
            
            result = f"""📚 我的文档

📊 统计概览：
- 文档总数：{total} 个
- 可阅读：{ready} 个
- 总页数：{total_pages} 页
"""
            
            # 按类型统计
            by_type = stats.get("byType", {})
            if by_type:
                result += "\n📁 按类型分布：\n"
                type_icons = {"pdf": "📕", "doc": "📘", "docx": "📘", "txt": "📄", "md": "📝"}
                for t, c in by_type.items():
                    icon = type_icons.get(t, "📄")
                    result += f"  - {icon} {t.upper()}：{c} 个\n"
            
            # 显示文档列表
            if documents:
                result += f"\n📋 {'全部' if not doc_type else doc_type.upper()} 文档列表：\n"
                for i, doc in enumerate(documents[:10], 1):
                    title = doc.get("title") or doc.get("name", "未命名文档")
                    if len(title) > 25:
                        title = title[:25] + "..."
                    
                    doc_type_str = doc.get("type", "").upper()
                    pages = doc.get("pages") or doc.get("totalPages") or 0
                    progress = doc.get("readProgress", 0)
                    
                    # 状态图标
                    type_icon = type_icons.get(doc.get("type", ""), "📄")
                    progress_str = f" ({progress}%)" if progress > 0 else ""
                    pages_str = f" {pages}页" if pages > 0 else ""
                    
                    result += f"  {i}. {type_icon} {title}{pages_str}{progress_str}\n"
            else:
                result += "\n📋 暂无文档\n"
            
            result += "\n💡 功能提示：\n"
            result += "  - 在小程序「文档伴读」中上传学习资料\n"
            result += "  - 支持 PDF、Word、TXT、Markdown 格式\n"
            result += "  - 阅读时可以圈选提问，AI 帮你解答\n"
            
            logger.info(f"[get_documents] 获取成功，共 {len(documents)} 个文档")
            return result
            
        except Exception as e:
            logger.error(f"[get_documents] 获取失败: {e}")
            return f"""📚 我的文档

⚠️ 获取文档列表失败，请在小程序中查看。

💡 文档伴读功能：
- 📄 上传 PDF/Word/TXT 等学习资料
- 📖 沉浸式阅读，支持手势翻页
- ✏️ 圈选内容，AI 智能识别
- 📝 添加书签和笔记

🔗 前往小程序「文档伴读」使用完整功能！"""
    
    return get_documents


def create_search_documents_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """搜索文档工具"""
    
    @tool
    async def search_documents(
        keyword: str,
    ) -> str:
        """搜索用户的学习文档。
        
        当用户说"找一下xxx文档"、"搜索文档"、"有没有关于xxx的资料"时调用此工具。
        
        Args:
            keyword: 搜索关键词
        
        Returns:
            匹配的文档列表
        """
        logger.info(f"[search_documents] 搜索文档, user_id={user_id}, keyword={keyword}")
        
        try:
            repo = DocumentRepository()
            
            documents = await repo.search_documents(user_id, keyword, limit=10)
            
            if not documents:
                return f"""🔍 搜索结果

未找到包含「{keyword}」的文档。

💡 建议：
- 尝试使用其他关键词
- 检查文档是否已上传
- 在小程序「文档伴读」中上传新资料

需要我帮你搜索网上的学习资源吗？"""
            
            result = f"""🔍 搜索「{keyword}」的结果

找到 {len(documents)} 个相关文档：
"""
            type_icons = {"pdf": "📕", "doc": "📘", "docx": "📘", "txt": "📄", "md": "📝"}
            
            for i, doc in enumerate(documents, 1):
                title = doc.get("title") or doc.get("name", "未命名文档")
                doc_type = doc.get("type", "")
                pages = doc.get("pages") or doc.get("totalPages") or 0
                icon = type_icons.get(doc_type, "📄")
                pages_str = f" ({pages}页)" if pages > 0 else ""
                
                result += f"  {i}. {icon} {title}{pages_str}\n"
            
            result += "\n💡 在小程序「文档伴读」中打开文档开始阅读！"
            
            logger.info(f"[search_documents] 搜索成功，找到 {len(documents)} 个")
            return result
            
        except Exception as e:
            logger.error(f"[search_documents] 搜索失败: {e}")
            return f"""🔍 搜索文档

⚠️ 搜索失败，请在小程序中查看。

错误信息：{str(e)}"""
    
    return search_documents


def create_get_document_stats_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """获取文档统计工具"""
    
    @tool
    async def get_document_stats() -> str:
        """获取用户的文档统计信息。
        
        当用户询问"文档统计"、"我有多少文档"、"文档概况"时调用此工具。
        
        Returns:
            文档统计信息
        """
        logger.info(f"[get_document_stats] 获取文档统计, user_id={user_id}")
        
        try:
            repo = DocumentRepository()
            
            stats = await repo.get_document_stats(user_id)
            recent = await repo.get_recent_documents(user_id, limit=3)
            
            total = stats.get("total", 0)
            ready = stats.get("ready", 0)
            total_pages = stats.get("totalPages", 0)
            by_type = stats.get("byType", {})
            by_status = stats.get("byStatus", {})
            
            result = f"""📊 文档统计

📚 总览：
- 文档总数：{total} 个
- 可阅读：{ready} 个
- 处理中：{by_status.get('processing', 0)} 个
- 总页数：{total_pages} 页
"""
            
            # 类型分布
            if by_type:
                result += "\n📁 类型分布：\n"
                type_icons = {"pdf": "📕", "doc": "📘", "docx": "📘", "txt": "📄", "md": "📝"}
                for t, c in sorted(by_type.items(), key=lambda x: x[1], reverse=True):
                    icon = type_icons.get(t, "📄")
                    percent = round(c / total * 100) if total > 0 else 0
                    result += f"  - {icon} {t.upper()}：{c} 个 ({percent}%)\n"
            
            # 最近文档
            if recent:
                result += "\n📖 最近阅读：\n"
                for doc in recent:
                    title = doc.get("title") or doc.get("name", "未命名")
                    if len(title) > 20:
                        title = title[:20] + "..."
                    result += f"  - {title}\n"
            
            if total == 0:
                result += "\n💡 提示：还没有上传文档，在小程序「文档伴读」中上传学习资料吧！"
            else:
                result += "\n💡 继续在「文档伴读」中阅读和学习！"
            
            logger.info(f"[get_document_stats] 获取成功")
            return result
            
        except Exception as e:
            logger.error(f"[get_document_stats] 获取失败: {e}")
            return f"""📊 文档统计

⚠️ 获取统计失败

请在小程序「文档伴读」中查看您的文档。

错误信息：{str(e)}"""
    
    return get_document_stats


def create_get_recent_documents_tool(user_id: str, memory: "AgentMemory") -> BaseTool:
    """获取最近文档工具"""
    
    @tool
    async def get_recent_documents(limit: int = 5) -> str:
        """获取最近阅读或上传的文档。
        
        当用户说"最近看的文档"、"继续阅读"、"最近学习的资料"时调用此工具。
        
        Args:
            limit: 返回数量，默认5
        
        Returns:
            最近文档列表
        """
        logger.info(f"[get_recent_documents] 获取最近文档, user_id={user_id}")
        
        try:
            repo = DocumentRepository()
            
            documents = await repo.get_recent_documents(user_id, limit=limit)
            
            if not documents:
                return """📖 最近阅读

暂无阅读记录。

💡 开始你的学习之旅：
1. 打开小程序「文档伴读」
2. 上传 PDF/Word/TXT 等学习资料
3. 开始沉浸式阅读

有问题随时圈选提问，AI 帮你解答！"""
            
            result = "📖 最近阅读\n\n"
            
            type_icons = {"pdf": "📕", "doc": "📘", "docx": "📘", "txt": "📄", "md": "📝"}
            
            for i, doc in enumerate(documents, 1):
                title = doc.get("title") or doc.get("name", "未命名文档")
                doc_type = doc.get("type", "")
                pages = doc.get("pages") or doc.get("totalPages") or 0
                progress = doc.get("readProgress", 0)
                icon = type_icons.get(doc_type, "📄")
                
                result += f"{i}. {icon} {title}\n"
                if pages > 0:
                    result += f"   📄 {pages} 页"
                    if progress > 0:
                        result += f" · 已读 {progress}%"
                    result += "\n"
            
            result += "\n💡 在小程序「文档伴读」中继续阅读！"
            
            logger.info(f"[get_recent_documents] 获取成功，共 {len(documents)} 个")
            return result
            
        except Exception as e:
            logger.error(f"[get_recent_documents] 获取失败: {e}")
            return f"""📖 最近阅读

⚠️ 获取失败，请在小程序中查看。

错误信息：{str(e)}"""
    
    return get_recent_documents

