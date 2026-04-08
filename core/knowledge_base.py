"""
知识库管理模块

封装 ChromaDB 操作，提供经验存储（add_experience）和相似案例检索（search_similar）功能。
管理用户反馈的存储和检索，按多维度标签结构化存储知识条目。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import get_config
from db.chroma_db import ChromaDB
from models.schemas import AnalysisResult, KeyEvent, UserFeedback

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """知识库管理器，封装经验存储与检索"""

    def __init__(self, chroma: ChromaDB):
        """
        初始化知识库

        Args:
            chroma: ChromaDB 实例
        """
        self.chroma = chroma
        self.config = get_config()
        self.top_k = self.config.get('knowledge_base.top_k', 5)
        logger.info("知识库初始化完成，已有 %d 条经验记录", self.chroma.get_count())

    def store_analysis_experience(
        self,
        analysis: AnalysisResult,
        feedback: Optional[UserFeedback] = None,
        news_summary: str = ''
    ) -> str:
        """
        将分析结果存储为知识库经验

        Args:
            analysis: AI 分析结果
            feedback: 用户反馈（可选）
            news_summary: 关联新闻摘要

        Returns:
            知识库记录 ID
        """
        # 构建经验文本（用于向量化检索）
        document_parts = [
            f"分析方向: {analysis.direction}",
            f"置信率: {analysis.confidence}%",
            f"事件类别: {analysis.event_category}",
            f"影响等级: {analysis.impact_level}",
            f"分析理由: {analysis.reasoning}",
            f"关键因素: {', '.join(analysis.key_factors)}",
        ]
        if news_summary:
            document_parts.append(f"新闻摘要: {news_summary}")
        if feedback:
            document_parts.append(f"用户反馈: {'准确' if feedback.is_accurate else '不准确'}")
            if feedback.comment:
                document_parts.append(f"反馈备注: {feedback.comment}")

        document = "\n".join(document_parts)

        # 构建多维度元数据标签
        metadata: Dict[str, Any] = {
            'direction': analysis.direction,
            'confidence': analysis.confidence,
            'event_category': analysis.event_category,
            'impact_level': analysis.impact_level,
            'suggested_action': analysis.suggested_action,
            'key_factors': ', '.join(analysis.key_factors),
            'created_at': (analysis.created_at or datetime.now()).isoformat(),
        }

        # 如果有用户反馈，添加反馈信息
        if feedback:
            metadata['has_feedback'] = True
            metadata['is_accurate'] = feedback.is_accurate
            metadata['feedback_comment'] = feedback.comment or ''
        else:
            metadata['has_feedback'] = False

        # 存入 ChromaDB
        doc_id = self.chroma.add_experience(
            document=document,
            metadata=metadata,
            doc_id=analysis.id
        )

        logger.info(
            "经验已存入知识库: 类别=%s, 方向=%s, 置信率=%.0f%%",
            analysis.event_category, analysis.direction, analysis.confidence
        )
        return doc_id

    def store_event_experience(self, event: KeyEvent, actual_outcome: str = '') -> str:
        """
        将关键事件存储为知识库经验

        Args:
            event: 关键事件
            actual_outcome: 实际结果描述（事后补充）

        Returns:
            知识库记录 ID
        """
        document = (
            f"关键事件: {event.title}\n"
            f"事件摘要: {event.summary}\n"
            f"影响方向: {event.direction}\n"
            f"影响等级: {event.impact_level}\n"
            f"事件类别: {event.event_category}\n"
        )
        if actual_outcome:
            document += f"实际结果: {actual_outcome}\n"

        metadata = {
            'type': 'key_event',
            'direction': event.direction,
            'impact_level': event.impact_level,
            'event_category': event.event_category,
            'confidence': event.confidence,
            'created_at': (event.published_at or datetime.now()).isoformat(),
        }

        return self.chroma.add_experience(
            document=document,
            metadata=metadata,
            doc_id=event.id
        )

    def update_with_feedback(
        self,
        analysis_id: str,
        feedback: UserFeedback
    ) -> None:
        """
        使用用户反馈更新知识库记录

        Args:
            analysis_id: 分析结果 ID
            feedback: 用户反馈
        """
        try:
            self.chroma.update_experience(
                doc_id=analysis_id,
                metadata={
                    'has_feedback': True,
                    'is_accurate': feedback.is_accurate,
                    'feedback_comment': feedback.comment or '',
                    'feedback_at': datetime.now().isoformat(),
                }
            )
            logger.info(
                "知识库记录已更新反馈: %s, 准确=%s",
                analysis_id, feedback.is_accurate
            )
        except Exception as e:
            logger.error("更新知识库反馈失败: %s", e)

    def search_similar_cases(
        self,
        query: str,
        event_category: Optional[str] = None,
        top_k: Optional[int] = None
    ) -> List[str]:
        """
        检索相似的历史经验

        Args:
            query: 查询文本（通常是新闻摘要）
            event_category: 按事件类别过滤（可选）
            top_k: 返回数量（默认使用配置值）

        Returns:
            历史经验文本列表
        """
        k = top_k or self.top_k
        where = None
        if event_category:
            where = {'event_category': event_category}

        results = self.chroma.search_similar(
            query=query,
            top_k=k,
            where=where
        )

        # 提取文档文本
        contexts = []
        for r in results:
            doc = r.get('document', '')
            meta = r.get('metadata', {})
            distance = r.get('distance', 0)

            # 格式化为上下文文本
            feedback_info = ""
            if meta.get('has_feedback'):
                accuracy = "准确" if meta.get('is_accurate') else "不准确"
                feedback_info = f" [用户反馈: {accuracy}]"

            context = f"[相似度: {1-distance:.2f}] {doc}{feedback_info}"
            contexts.append(context)

        if contexts:
            logger.info("知识库检索到 %d 条相似案例", len(contexts))
        return contexts

    def get_stats(self) -> Dict[str, Any]:
        """获取知识库统计信息"""
        total = self.chroma.get_count()
        return {
            'total_experiences': total,
            'status': '运行中' if total >= 0 else '异常',
        }
