"""
ChromaDB 向量数据库封装模块

管理 ChromaDB 客户端初始化、集合创建、文档嵌入存储和相似度查询。
用于知识库的经验存储与检索。
"""

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)


class ChromaDB:
    """ChromaDB 向量数据库封装"""

    def __init__(self, persist_directory: str, collection_name: str = 'gold_monitor_experiences'):
        """
        初始化 ChromaDB 客户端

        Args:
            persist_directory: 数据持久化目录
            collection_name: 集合名称
        """
        self.persist_directory = persist_directory
        self.collection_name = collection_name

        # 确保目录存在
        Path(persist_directory).mkdir(parents=True, exist_ok=True)

        # 初始化客户端（内嵌模式，持久化存储）
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(anonymized_telemetry=False)
        )

        # 获取或创建集合
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"description": "黄金市场分析经验知识库"}
        )

        logger.info(
            "ChromaDB 初始化完成，持久化目录: %s，集合: %s，已有 %d 条记录",
            persist_directory, collection_name, self.collection.count()
        )

    def add_experience(
        self,
        document: str,
        metadata: Dict[str, Any],
        doc_id: Optional[str] = None
    ) -> str:
        """
        添加一条经验记录到知识库

        Args:
            document: 经验文本内容（用于向量化检索）
            metadata: 元数据（事件类型、影响方向、置信率、实际结果等）
            doc_id: 文档 ID（可选，默认自动生成）

        Returns:
            文档 ID
        """
        doc_id = doc_id or str(uuid.uuid4())

        # 确保 metadata 中的值都是基本类型（ChromaDB 要求）
        clean_metadata = {}
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool)):
                clean_metadata[k] = v
            elif isinstance(v, datetime):
                clean_metadata[k] = v.isoformat()
            elif isinstance(v, list):
                clean_metadata[k] = ', '.join(str(i) for i in v)
            else:
                clean_metadata[k] = str(v)

        # 添加创建时间
        if 'created_at' not in clean_metadata:
            clean_metadata['created_at'] = datetime.now().isoformat()

        try:
            self.collection.add(
                documents=[document],
                metadatas=[clean_metadata],
                ids=[doc_id]
            )
            logger.info("知识库添加经验记录: %s (类别: %s)", doc_id, clean_metadata.get('event_category', '未知'))
            return doc_id
        except Exception as e:
            logger.error("知识库添加记录失败: %s", e, exc_info=True)
            raise

    def search_similar(
        self,
        query: str,
        top_k: int = 5,
        where: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        检索相似的历史经验

        Args:
            query: 查询文本
            top_k: 返回最相似的 N 条记录
            where: 过滤条件（按元数据字段过滤）

        Returns:
            相似记录列表，每条包含 document, metadata, distance
        """
        try:
            # 如果集合为空，直接返回
            if self.collection.count() == 0:
                return []

            # 确保 top_k 不超过集合大小
            actual_k = min(top_k, self.collection.count())

            query_params = {
                'query_texts': [query],
                'n_results': actual_k,
            }
            if where:
                query_params['where'] = where

            results = self.collection.query(**query_params)

            # 组装返回结果
            experiences = []
            if results and results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    experience = {
                        'document': doc,
                        'metadata': results['metadatas'][0][i] if results['metadatas'] else {},
                        'distance': results['distances'][0][i] if results['distances'] else 0,
                        'id': results['ids'][0][i] if results['ids'] else ''
                    }
                    experiences.append(experience)

            logger.info("知识库检索完成，查询文本长度: %d，返回 %d 条结果", len(query), len(experiences))
            return experiences

        except Exception as e:
            logger.error("知识库检索失败: %s", e, exc_info=True)
            return []

    def update_experience(
        self,
        doc_id: str,
        document: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        更新知识库中的一条记录

        Args:
            doc_id: 文档 ID
            document: 新的文本内容（可选）
            metadata: 新的元数据（可选）
        """
        update_params: Dict[str, Any] = {'ids': [doc_id]}

        if document:
            update_params['documents'] = [document]
        if metadata:
            # 清理 metadata
            clean_metadata = {}
            for k, v in metadata.items():
                if isinstance(v, (str, int, float, bool)):
                    clean_metadata[k] = v
                elif isinstance(v, datetime):
                    clean_metadata[k] = v.isoformat()
                else:
                    clean_metadata[k] = str(v)
            update_params['metadatas'] = [clean_metadata]

        try:
            self.collection.update(**update_params)
            logger.info("知识库记录已更新: %s", doc_id)
        except Exception as e:
            logger.error("知识库更新失败: %s", e, exc_info=True)
            raise

    def delete_experience(self, doc_id: str) -> None:
        """删除知识库中的一条记录"""
        try:
            self.collection.delete(ids=[doc_id])
            logger.info("知识库记录已删除: %s", doc_id)
        except Exception as e:
            logger.error("知识库删除失败: %s", e, exc_info=True)
            raise

    def get_count(self) -> int:
        """获取知识库记录总数"""
        return self.collection.count()
