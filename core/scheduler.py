"""
调度器模块

基于 APScheduler，编排新闻采集 -> AI 分析 -> 通知的完整流程。
配置定时任务：新闻采集（每30分钟）、金价检查（每5分钟）、每日总结（每晚20:00）。
"""

import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import Config
from core.ai_analyzer import AIAnalyzer
from core.knowledge_base import KnowledgeBase
from core.news_collector import NewsCollector
from core.notifier import Notifier
from core.price_monitor import PriceMonitor
from db.chroma_db import ChromaDB
from db.sqlite_db import SQLiteDB
from models.schemas import KeyEvent

logger = logging.getLogger(__name__)


class GoldScheduler:
    """黄金监控调度器，编排所有定时任务"""

    def __init__(self, db: SQLiteDB, chroma: ChromaDB, config: Config):
        """
        初始化调度器

        Args:
            db: SQLite 数据库实例
            chroma: ChromaDB 实例
            config: 配置实例
        """
        self.db = db
        self.config = config

        # 初始化各模块
        self.news_collector = NewsCollector()
        self.price_monitor = PriceMonitor()
        self.ai_analyzer = AIAnalyzer()
        self.knowledge_base = KnowledgeBase(chroma)
        self.notifier = Notifier()

        # 创建后台调度器
        self.scheduler = BackgroundScheduler(
            timezone='Asia/Shanghai',
            job_defaults={
                'coalesce': True,       # 合并错过的任务
                'max_instances': 1,     # 同一任务最多1个实例
                'misfire_grace_time': 60  # 错过任务的容忍时间（秒）
            }
        )

        logger.info("调度器初始化完成")

    def start(self) -> None:
        """启动调度器，注册所有定时任务"""
        # 新闻采集 + AI 分析（每30分钟）
        collect_interval = self.config.get('collector.interval_minutes', 30)
        self.scheduler.add_job(
            self._job_collect_and_analyze,
            trigger=IntervalTrigger(minutes=collect_interval),
            id='collect_and_analyze',
            name='新闻采集与AI分析',
            next_run_time=datetime.now()  # 启动后立即执行一次
        )

        # 金价检查（每5分钟）
        price_interval = self.config.get('price_monitor.interval_minutes', 5)
        self.scheduler.add_job(
            self._job_check_price,
            trigger=IntervalTrigger(minutes=price_interval),
            id='check_price',
            name='金价检查',
            next_run_time=datetime.now()
        )

        # 每日总结（每晚20:00）
        summary_hour = self.config.get('daily_summary.hour', 20)
        summary_minute = self.config.get('daily_summary.minute', 0)
        self.scheduler.add_job(
            self._job_daily_summary,
            trigger=CronTrigger(hour=summary_hour, minute=summary_minute),
            id='daily_summary',
            name='每日总结'
        )

        self.scheduler.start()
        logger.info(
            "调度器已启动 - 采集间隔: %d分钟, 金价检查: %d分钟, 每日总结: %02d:%02d",
            collect_interval, price_interval, summary_hour, summary_minute
        )

    def stop(self) -> None:
        """停止调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("调度器已停止")

    def _job_collect_and_analyze(self) -> None:
        """定时任务：采集新闻 -> AI 分析 -> 存储 -> 通知"""
        try:
            logger.info("=" * 40)
            logger.info("开始执行: 新闻采集与AI分析")

            # 1. 采集新闻
            news_items = self.news_collector.collect_all()
            if not news_items:
                logger.info("本次采集未获取到新闻，跳过分析")
                return

            # 2. 批量保存新闻
            self.db.save_news_batch(news_items)
            logger.info("已保存 %d 条新闻到数据库", len(news_items))

            # 3. 获取当前金价
            price_data = self.price_monitor.get_current_price()

            # 4. 从知识库检索相似案例
            query_text = " ".join([n.title for n in news_items[:10]])
            historical_context = self.knowledge_base.search_similar_cases(query_text)

            # 5. AI 分析
            analysis = self.ai_analyzer.analyze(
                news_items=news_items,
                price_data=price_data,
                historical_context=historical_context
            )

            # 6. 保存分析结果
            analysis_id = self.db.save_analysis(analysis)
            analysis.id = analysis_id

            # 7. 保存关键事件（高/中影响的）
            if analysis.impact_level in ('high', 'medium'):
                for news in news_items[:3]:  # 取前3条最相关的新闻
                    event = KeyEvent(
                        title=news.title,
                        summary=analysis.reasoning[:100],
                        url=news.url,
                        source=news.source,
                        direction=analysis.direction,
                        impact_level=analysis.impact_level,
                        event_category=analysis.event_category,
                        published_at=news.published_at,
                        confidence=analysis.confidence
                    )
                    self.db.save_key_event(event)

            # 8. 存储分析经验到知识库
            news_summary = " | ".join([n.title for n in news_items[:5]])
            self.knowledge_base.store_analysis_experience(
                analysis=analysis,
                news_summary=news_summary
            )

            # 9. 判断是否需要通知
            threshold = self.config.confidence_threshold
            notify_levels = self.config.get('analysis.notify_impact_levels', ['high', 'medium'])

            if (analysis.confidence >= threshold and
                    analysis.impact_level in notify_levels):
                current_price = price_data.price if price_data else 0
                self.notifier.notify_analysis(analysis, price=current_price)
                logger.info(
                    "已发送通知: %s, 置信率=%.0f%%, 建议=%s",
                    analysis.direction, analysis.confidence, analysis.suggested_action
                )
            else:
                logger.info(
                    "未达通知条件: 置信率=%.0f%%(阈值=%d), 影响=%s",
                    analysis.confidence, threshold, analysis.impact_level
                )

            logger.info("新闻采集与分析完成")

        except Exception as e:
            logger.error("新闻采集与分析任务异常: %s", e, exc_info=True)

    def _job_check_price(self) -> None:
        """定时任务：检查金价并存储"""
        try:
            price_data = self.price_monitor.get_current_price()
            if price_data:
                self.db.save_price(price_data)
                logger.info(
                    "金价更新: $%.2f, 变动: %+.2f%%",
                    price_data.price, price_data.change_percent_24h
                )
        except Exception as e:
            logger.error("金价检查任务异常: %s", e, exc_info=True)

    def _job_daily_summary(self) -> None:
        """定时任务：生成每日总结（每晚20:00）"""
        try:
            logger.info("=" * 40)
            logger.info("开始生成每日总结")

            # 获取今日数据
            analyses = self.db.get_recent_analyses(hours=24, limit=200)
            price_changes = self.db.get_price_history(hours=24)
            news_items = self.db.get_recent_news(hours=24, limit=200)

            if not analyses and not news_items:
                logger.info("今日无分析数据，跳过总结生成")
                return

            # 获取准确率统计
            stats = self.db.get_accuracy_stats(days=1)

            # AI 生成总结
            summary = self.ai_analyzer.summarize(
                analyses=analyses,
                price_changes=price_changes,
                news_items=news_items
            )

            # 补充准确率数据
            summary.accurate_count = stats.get('accurate', 0)
            summary.accuracy_rate = stats.get('accuracy_rate', 0)

            # 保存总结
            self.db.save_daily_summary(summary)

            # 发送通知
            self.notifier.notify_daily_summary(summary)

            logger.info(
                "每日总结已生成并推送: 日期=%s, 分析数=%d, 准确率=%.1f%%",
                summary.date, summary.total_analyses, summary.accuracy_rate
            )

        except Exception as e:
            logger.error("每日总结任务异常: %s", e, exc_info=True)
