"""
SQLite 数据库管理模块

定义表结构（news_items, analysis_results, price_history, daily_summaries, user_feedback），
提供 CRUD 操作，使用 WAL 模式支持并发读，内置 schema 版本管理。
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from models.schemas import (
    AnalysisResult,
    DailySummary,
    KeyEvent,
    NewsItem,
    PriceData,
    UserFeedback,
)

logger = logging.getLogger(__name__)

# 当前数据库 schema 版本
SCHEMA_VERSION = 1


class SQLiteDB:
    """SQLite 数据库管理类"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        # 确保目录存在
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        logger.info("SQLite 数据库路径: %s", db_path)

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # 启用 WAL 模式，支持并发读
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_tables(self) -> None:
        """初始化所有数据表"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()

            # schema 版本管理表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
            """)

            # 新闻表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS news_items (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    url TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    keywords TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
            """)

            # 分析结果表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS analysis_results (
                    id TEXT PRIMARY KEY,
                    direction TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reasoning TEXT NOT NULL,
                    suggested_action TEXT NOT NULL,
                    key_factors TEXT DEFAULT '[]',
                    impact_level TEXT DEFAULT 'medium',
                    event_category TEXT DEFAULT 'general',
                    news_ids TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
            """)

            # 价格历史表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    price REAL NOT NULL,
                    currency TEXT DEFAULT 'USD',
                    change_24h REAL DEFAULT 0,
                    change_percent_24h REAL DEFAULT 0,
                    high_24h REAL DEFAULT 0,
                    low_24h REAL DEFAULT 0,
                    volatility REAL DEFAULT 0,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
            """)

            # 每日总结表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_summaries (
                    id TEXT PRIMARY KEY,
                    date TEXT NOT NULL UNIQUE,
                    summary TEXT NOT NULL,
                    key_events TEXT DEFAULT '[]',
                    dimensions TEXT DEFAULT '{}',
                    price_change REAL DEFAULT 0,
                    price_change_percent REAL DEFAULT 0,
                    total_analyses INTEGER DEFAULT 0,
                    accurate_count INTEGER DEFAULT 0,
                    accuracy_rate REAL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
            """)

            # 用户反馈表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_feedback (
                    id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL,
                    is_accurate INTEGER NOT NULL,
                    comment TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (analysis_id) REFERENCES analysis_results(id)
                )
            """)

            # 关键事件表（用于仪表盘事件卡片流）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS key_events (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    impact_level TEXT NOT NULL,
                    event_category TEXT NOT NULL,
                    published_at TEXT,
                    confidence REAL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
            """)

            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_analysis_created ON analysis_results(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_timestamp ON price_history(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_summary_date ON daily_summaries(date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_analysis ON user_feedback(analysis_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_created ON key_events(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_impact ON key_events(impact_level)")

            # 记录 schema 版本
            cursor.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, datetime.now().isoformat())
            )

            conn.commit()
            logger.info("数据库表初始化完成，schema 版本: %d", SCHEMA_VERSION)
        except Exception as e:
            logger.error("数据库初始化失败: %s", e, exc_info=True)
            raise
        finally:
            conn.close()

    # ==================== 新闻操作 ====================

    def save_news(self, news: NewsItem) -> str:
        """保存新闻，返回 ID"""
        news_id = news.id or str(uuid.uuid4())
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO news_items
                   (id, title, content, source, url, published_at, keywords)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    news_id, news.title, news.content, news.source,
                    news.url, news.published_at.isoformat(),
                    json.dumps(news.keywords, ensure_ascii=False)
                )
            )
            conn.commit()
            return news_id
        finally:
            conn.close()

    def save_news_batch(self, news_list: List[NewsItem]) -> List[str]:
        """批量保存新闻"""
        ids = []
        conn = self._get_conn()
        try:
            for news in news_list:
                news_id = news.id or str(uuid.uuid4())
                conn.execute(
                    """INSERT OR REPLACE INTO news_items
                       (id, title, content, source, url, published_at, keywords)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        news_id, news.title, news.content, news.source,
                        news.url, news.published_at.isoformat(),
                        json.dumps(news.keywords, ensure_ascii=False)
                    )
                )
                ids.append(news_id)
            conn.commit()
            return ids
        finally:
            conn.close()

    def get_recent_news(self, hours: int = 24, limit: int = 50) -> List[NewsItem]:
        """获取最近 N 小时内的新闻"""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM news_items
                   WHERE published_at >= ?
                   ORDER BY published_at DESC LIMIT ?""",
                (since, limit)
            ).fetchall()
            return [self._row_to_news(r) for r in rows]
        finally:
            conn.close()

    # ==================== 分析结果操作 ====================

    def save_analysis(self, result: AnalysisResult) -> str:
        """保存分析结果，返回 ID"""
        analysis_id = result.id or str(uuid.uuid4())
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO analysis_results
                   (id, direction, confidence, reasoning, suggested_action,
                    key_factors, impact_level, event_category, news_ids, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    analysis_id, result.direction, result.confidence,
                    result.reasoning, result.suggested_action,
                    json.dumps(result.key_factors, ensure_ascii=False),
                    result.impact_level, result.event_category,
                    json.dumps(result.news_ids, ensure_ascii=False),
                    (result.created_at or datetime.now()).isoformat()
                )
            )
            conn.commit()
            return analysis_id
        finally:
            conn.close()

    def get_recent_analyses(self, hours: int = 24, limit: int = 20) -> List[AnalysisResult]:
        """获取最近 N 小时的分析结果"""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM analysis_results
                   WHERE created_at >= ?
                   ORDER BY created_at DESC LIMIT ?""",
                (since, limit)
            ).fetchall()
            return [self._row_to_analysis(r) for r in rows]
        finally:
            conn.close()

    def get_latest_analysis(self) -> Optional[AnalysisResult]:
        """获取最新一条分析结果"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM analysis_results ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            return self._row_to_analysis(row) if row else None
        finally:
            conn.close()

    def get_analyses_by_date(self, date: str) -> List[AnalysisResult]:
        """获取指定日期的所有分析结果"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM analysis_results
                   WHERE date(created_at) = ?
                   ORDER BY created_at DESC""",
                (date,)
            ).fetchall()
            return [self._row_to_analysis(r) for r in rows]
        finally:
            conn.close()

    # ==================== 价格操作 ====================

    def save_price(self, price: PriceData) -> None:
        """保存价格数据"""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO price_history
                   (price, currency, change_24h, change_percent_24h,
                    high_24h, low_24h, volatility, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    price.price, price.currency, price.change_24h,
                    price.change_percent_24h, price.high_24h, price.low_24h,
                    price.volatility,
                    (price.timestamp or datetime.now()).isoformat()
                )
            )
            conn.commit()
        finally:
            conn.close()

    def get_latest_price(self) -> Optional[PriceData]:
        """获取最新价格"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM price_history ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            return self._row_to_price(row) if row else None
        finally:
            conn.close()

    def get_price_history(self, hours: int = 24) -> List[PriceData]:
        """获取价格历史"""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM price_history
                   WHERE timestamp >= ?
                   ORDER BY timestamp ASC""",
                (since,)
            ).fetchall()
            return [self._row_to_price(r) for r in rows]
        finally:
            conn.close()

    # ==================== 关键事件操作 ====================

    def save_key_event(self, event: KeyEvent) -> str:
        """保存关键事件"""
        event_id = event.id or str(uuid.uuid4())
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO key_events
                   (id, title, summary, url, source, direction,
                    impact_level, event_category, published_at, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id, event.title, event.summary, event.url,
                    event.source, event.direction, event.impact_level,
                    event.event_category,
                    event.published_at.isoformat() if event.published_at else None,
                    event.confidence
                )
            )
            conn.commit()
            return event_id
        finally:
            conn.close()

    def get_recent_events(self, hours: int = 48, limit: int = 20) -> List[KeyEvent]:
        """获取最近的关键事件"""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM key_events
                   WHERE created_at >= ?
                   ORDER BY created_at DESC LIMIT ?""",
                (since, limit)
            ).fetchall()
            return [self._row_to_event(r) for r in rows]
        finally:
            conn.close()

    # ==================== 每日总结操作 ====================

    def save_daily_summary(self, summary: DailySummary) -> str:
        """保存每日总结"""
        summary_id = summary.id or str(uuid.uuid4())
        conn = self._get_conn()
        try:
            # 序列化 key_events
            key_events_data = []
            for e in summary.key_events:
                key_events_data.append({
                    'title': e.title, 'summary': e.summary, 'url': e.url,
                    'source': e.source, 'direction': e.direction,
                    'impact_level': e.impact_level, 'event_category': e.event_category,
                    'published_at': e.published_at.isoformat() if e.published_at else None,
                    'confidence': e.confidence
                })

            conn.execute(
                """INSERT OR REPLACE INTO daily_summaries
                   (id, date, summary, key_events, dimensions,
                    price_change, price_change_percent,
                    total_analyses, accurate_count, accuracy_rate, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    summary_id, summary.date, summary.summary,
                    json.dumps(key_events_data, ensure_ascii=False),
                    json.dumps(summary.dimensions, ensure_ascii=False),
                    summary.price_change, summary.price_change_percent,
                    summary.total_analyses, summary.accurate_count,
                    summary.accuracy_rate,
                    (summary.created_at or datetime.now()).isoformat()
                )
            )
            conn.commit()
            return summary_id
        finally:
            conn.close()

    def get_daily_summaries(self, days: int = 30) -> List[DailySummary]:
        """获取最近 N 天的每日总结"""
        since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM daily_summaries
                   WHERE date >= ?
                   ORDER BY date DESC""",
                (since,)
            ).fetchall()
            return [self._row_to_summary(r) for r in rows]
        finally:
            conn.close()

    def get_daily_summary_by_date(self, date: str) -> Optional[DailySummary]:
        """获取指定日期的每日总结"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM daily_summaries WHERE date = ?", (date,)
            ).fetchone()
            return self._row_to_summary(row) if row else None
        finally:
            conn.close()

    # ==================== 用户反馈操作 ====================

    def save_feedback(self, feedback: UserFeedback) -> str:
        """保存用户反馈"""
        feedback_id = feedback.id or str(uuid.uuid4())
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO user_feedback
                   (id, analysis_id, is_accurate, comment, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    feedback_id, feedback.analysis_id,
                    1 if feedback.is_accurate else 0,
                    feedback.comment,
                    (feedback.created_at or datetime.now()).isoformat()
                )
            )
            conn.commit()
            return feedback_id
        finally:
            conn.close()

    def get_feedback_for_analysis(self, analysis_id: str) -> Optional[UserFeedback]:
        """获取某条分析的用户反馈"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM user_feedback WHERE analysis_id = ?",
                (analysis_id,)
            ).fetchone()
            return self._row_to_feedback(row) if row else None
        finally:
            conn.close()

    def get_accuracy_stats(self, days: int = 7) -> Dict[str, Any]:
        """获取准确率统计"""
        since = (datetime.now() - timedelta(days=days)).isoformat()
        conn = self._get_conn()
        try:
            # 总体统计
            total = conn.execute(
                """SELECT COUNT(*) as total,
                          SUM(CASE WHEN is_accurate = 1 THEN 1 ELSE 0 END) as accurate
                   FROM user_feedback WHERE created_at >= ?""",
                (since,)
            ).fetchone()

            # 按方向统计
            by_direction = conn.execute(
                """SELECT ar.direction,
                          COUNT(*) as total,
                          SUM(CASE WHEN uf.is_accurate = 1 THEN 1 ELSE 0 END) as accurate
                   FROM user_feedback uf
                   JOIN analysis_results ar ON uf.analysis_id = ar.id
                   WHERE uf.created_at >= ?
                   GROUP BY ar.direction""",
                (since,)
            ).fetchall()

            total_count = total['total'] or 0
            accurate_count = total['accurate'] or 0

            return {
                'total': total_count,
                'accurate': accurate_count,
                'accuracy_rate': round(accurate_count / total_count * 100, 1) if total_count > 0 else 0,
                'by_direction': {
                    row['direction']: {
                        'total': row['total'],
                        'accurate': row['accurate'],
                        'accuracy_rate': round(row['accurate'] / row['total'] * 100, 1) if row['total'] > 0 else 0
                    }
                    for row in by_direction
                }
            }
        finally:
            conn.close()

    # ==================== 辅助方法 ====================

    @staticmethod
    def _row_to_news(row: sqlite3.Row) -> NewsItem:
        """数据库行转 NewsItem"""
        return NewsItem(
            id=row['id'],
            title=row['title'],
            content=row['content'],
            source=row['source'],
            url=row['url'],
            published_at=datetime.fromisoformat(row['published_at']),
            keywords=json.loads(row['keywords']) if row['keywords'] else []
        )

    @staticmethod
    def _row_to_analysis(row: sqlite3.Row) -> AnalysisResult:
        """数据库行转 AnalysisResult"""
        return AnalysisResult(
            id=row['id'],
            direction=row['direction'],
            confidence=row['confidence'],
            reasoning=row['reasoning'],
            suggested_action=row['suggested_action'],
            key_factors=json.loads(row['key_factors']) if row['key_factors'] else [],
            impact_level=row['impact_level'] or 'medium',
            event_category=row['event_category'] or 'general',
            news_ids=json.loads(row['news_ids']) if row['news_ids'] else [],
            created_at=datetime.fromisoformat(row['created_at'])
        )

    @staticmethod
    def _row_to_price(row: sqlite3.Row) -> PriceData:
        """数据库行转 PriceData"""
        return PriceData(
            price=row['price'],
            currency=row['currency'],
            change_24h=row['change_24h'],
            change_percent_24h=row['change_percent_24h'],
            high_24h=row['high_24h'],
            low_24h=row['low_24h'],
            volatility=row['volatility'],
            timestamp=datetime.fromisoformat(row['timestamp'])
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> KeyEvent:
        """数据库行转 KeyEvent"""
        return KeyEvent(
            id=row['id'],
            title=row['title'],
            summary=row['summary'],
            url=row['url'],
            source=row['source'],
            direction=row['direction'],
            impact_level=row['impact_level'],
            event_category=row['event_category'],
            published_at=datetime.fromisoformat(row['published_at']) if row['published_at'] else None,
            confidence=row['confidence']
        )

    @staticmethod
    def _row_to_summary(row: sqlite3.Row) -> DailySummary:
        """数据库行转 DailySummary"""
        key_events_data = json.loads(row['key_events']) if row['key_events'] else []
        key_events = []
        for e in key_events_data:
            key_events.append(KeyEvent(
                title=e.get('title', ''),
                summary=e.get('summary', ''),
                url=e.get('url', ''),
                source=e.get('source', ''),
                direction=e.get('direction', 'neutral'),
                impact_level=e.get('impact_level', 'medium'),
                event_category=e.get('event_category', 'general'),
                published_at=datetime.fromisoformat(e['published_at']) if e.get('published_at') else None,
                confidence=e.get('confidence', 0)
            ))

        return DailySummary(
            id=row['id'],
            date=row['date'],
            summary=row['summary'],
            key_events=key_events,
            dimensions=json.loads(row['dimensions']) if row['dimensions'] else {},
            price_change=row['price_change'],
            price_change_percent=row['price_change_percent'],
            total_analyses=row['total_analyses'],
            accurate_count=row['accurate_count'],
            accuracy_rate=row['accuracy_rate'],
            created_at=datetime.fromisoformat(row['created_at'])
        )

    @staticmethod
    def _row_to_feedback(row: sqlite3.Row) -> UserFeedback:
        """数据库行转 UserFeedback"""
        return UserFeedback(
            id=row['id'],
            analysis_id=row['analysis_id'],
            is_accurate=bool(row['is_accurate']),
            comment=row['comment'] or '',
            created_at=datetime.fromisoformat(row['created_at'])
        )
