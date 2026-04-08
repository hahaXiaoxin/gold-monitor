"""
核心模块单元测试

覆盖 AI 策略切换、新闻采集解析、知识库检索、通知发送、数据库操作等关键逻辑。
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.schemas import (
    AnalysisResult,
    DailySummary,
    KeyEvent,
    NewsItem,
    PriceData,
    UserFeedback,
)


class TestSchemas(unittest.TestCase):
    """测试数据模型"""

    def test_news_item_creation(self):
        """测试 NewsItem 创建"""
        news = NewsItem(
            title="黄金价格创新高",
            content="受美联储降息预期影响，黄金价格突破2000美元",
            source="sina_finance",
            url="https://example.com/news/1",
            published_at=datetime.now(),
            keywords=["黄金", "美联储", "降息"]
        )
        self.assertEqual(news.title, "黄金价格创新高")
        self.assertEqual(news.source, "sina_finance")
        self.assertEqual(len(news.keywords), 3)
        self.assertIsNone(news.id)

    def test_analysis_result_creation(self):
        """测试 AnalysisResult 创建"""
        result = AnalysisResult(
            direction="bullish",
            confidence=85.0,
            reasoning="美联储降息预期增强",
            suggested_action="buy",
            key_factors=["降息预期", "避险需求"],
            impact_level="high",
            event_category="central_bank"
        )
        self.assertEqual(result.direction, "bullish")
        self.assertEqual(result.confidence, 85.0)
        self.assertEqual(result.impact_level, "high")

    def test_price_data_defaults(self):
        """测试 PriceData 默认值"""
        price = PriceData(price=2050.50)
        self.assertEqual(price.currency, "USD")
        self.assertEqual(price.change_24h, 0.0)
        self.assertEqual(price.volatility, 0.0)

    def test_key_event_creation(self):
        """测试 KeyEvent 创建"""
        event = KeyEvent(
            title="美联储宣布降息25个基点",
            summary="美联储如期降息，金价应声上涨",
            url="https://example.com/news/fed",
            source="jin10",
            direction="bullish",
            impact_level="high",
            event_category="central_bank"
        )
        self.assertEqual(event.impact_level, "high")
        self.assertEqual(event.event_category, "central_bank")

    def test_daily_summary_defaults(self):
        """测试 DailySummary 默认值"""
        summary = DailySummary(
            date="2024-01-15",
            summary="今日黄金市场整体走高"
        )
        self.assertEqual(summary.total_analyses, 0)
        self.assertEqual(summary.accuracy_rate, 0.0)
        self.assertEqual(len(summary.key_events), 0)


class TestSQLiteDB(unittest.TestCase):
    """测试 SQLite 数据库操作"""

    def setUp(self):
        """创建临时数据库"""
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        from db.sqlite_db import SQLiteDB
        self.db = SQLiteDB(self.db_path)
        self.db.init_tables()

    def tearDown(self):
        """清理临时数据库"""
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_save_and_get_news(self):
        """测试新闻保存和查询"""
        news = NewsItem(
            title="测试新闻",
            content="测试内容",
            source="test",
            url="https://example.com/test",
            published_at=datetime.now(),
            keywords=["测试"]
        )
        news_id = self.db.save_news(news)
        self.assertIsNotNone(news_id)

        recent = self.db.get_recent_news(hours=1)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].title, "测试新闻")

    def test_save_and_get_analysis(self):
        """测试分析结果保存和查询"""
        result = AnalysisResult(
            direction="bullish",
            confidence=80.0,
            reasoning="测试理由",
            suggested_action="buy",
            key_factors=["因素1"],
            impact_level="high",
            event_category="economic_data",
            created_at=datetime.now()
        )
        aid = self.db.save_analysis(result)
        self.assertIsNotNone(aid)

        latest = self.db.get_latest_analysis()
        self.assertIsNotNone(latest)
        self.assertEqual(latest.direction, "bullish")
        self.assertEqual(latest.confidence, 80.0)

    def test_save_and_get_price(self):
        """测试价格保存和查询"""
        price = PriceData(
            price=2050.50,
            change_24h=15.30,
            change_percent_24h=0.75,
            timestamp=datetime.now()
        )
        self.db.save_price(price)

        latest = self.db.get_latest_price()
        self.assertIsNotNone(latest)
        self.assertAlmostEqual(latest.price, 2050.50)

    def test_save_and_get_key_event(self):
        """测试关键事件保存和查询"""
        event = KeyEvent(
            title="测试事件",
            summary="事件摘要",
            url="https://example.com",
            source="test",
            direction="bullish",
            impact_level="high",
            event_category="geopolitical",
            published_at=datetime.now()
        )
        eid = self.db.save_key_event(event)
        self.assertIsNotNone(eid)

        events = self.db.get_recent_events(hours=1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "测试事件")

    def test_save_feedback(self):
        """测试用户反馈保存"""
        # 先保存分析结果
        result = AnalysisResult(
            direction="bullish", confidence=75.0,
            reasoning="test", suggested_action="buy",
            created_at=datetime.now()
        )
        aid = self.db.save_analysis(result)

        # 保存反馈
        feedback = UserFeedback(
            analysis_id=aid,
            is_accurate=True,
            created_at=datetime.now()
        )
        fid = self.db.save_feedback(feedback)
        self.assertIsNotNone(fid)

        # 查询反馈
        fb = self.db.get_feedback_for_analysis(aid)
        self.assertIsNotNone(fb)
        self.assertTrue(fb.is_accurate)

    def test_accuracy_stats(self):
        """测试准确率统计"""
        stats = self.db.get_accuracy_stats(days=7)
        self.assertIn('total', stats)
        self.assertIn('accuracy_rate', stats)
        self.assertEqual(stats['total'], 0)

    def test_batch_save_news(self):
        """测试批量保存新闻"""
        news_list = [
            NewsItem(
                title=f"新闻{i}", content=f"内容{i}",
                source="test", url=f"https://example.com/{i}",
                published_at=datetime.now()
            )
            for i in range(5)
        ]
        ids = self.db.save_news_batch(news_list)
        self.assertEqual(len(ids), 5)

        recent = self.db.get_recent_news(hours=1, limit=10)
        self.assertEqual(len(recent), 5)


class TestAIAnalyzer(unittest.TestCase):
    """测试 AI 分析器策略模式"""

    def test_provider_map(self):
        """测试 Provider 注册表"""
        from core.ai_analyzer import AIAnalyzer
        self.assertIn('qwen', AIAnalyzer.PROVIDER_MAP)
        self.assertIn('openai', AIAnalyzer.PROVIDER_MAP)

    def test_invalid_provider(self):
        """测试无效的 Provider 名称"""
        from core.ai_analyzer import AIAnalyzer
        with self.assertRaises(ValueError):
            AIAnalyzer(provider_name='invalid_provider')

    def test_parse_analysis_response(self):
        """测试 AI 响应解析"""
        from core.ai_analyzer import AIProvider

        response = json.dumps({
            "direction": "bullish",
            "confidence": 85,
            "reasoning": "测试分析理由",
            "suggested_action": "buy",
            "key_factors": ["因素A", "因素B"],
            "impact_level": "high",
            "event_category": "economic_data"
        })

        result = AIProvider._parse_analysis_response(response)
        self.assertEqual(result.direction, "bullish")
        self.assertEqual(result.confidence, 85)
        self.assertEqual(result.impact_level, "high")
        self.assertEqual(len(result.key_factors), 2)

    def test_parse_analysis_with_markdown(self):
        """测试解析包含 markdown 代码块的 AI 响应"""
        from core.ai_analyzer import AIProvider

        response = '```json\n{"direction":"bearish","confidence":60,"reasoning":"test","suggested_action":"sell","key_factors":[],"impact_level":"medium","event_category":"geopolitical"}\n```'

        result = AIProvider._parse_analysis_response(response)
        self.assertEqual(result.direction, "bearish")
        self.assertEqual(result.suggested_action, "sell")

    def test_parse_invalid_response(self):
        """测试解析无效 AI 响应的容错"""
        from core.ai_analyzer import AIProvider

        result = AIProvider._parse_analysis_response("这不是JSON")
        self.assertEqual(result.direction, "neutral")
        self.assertEqual(result.confidence, 0)

    def test_event_categories(self):
        """测试事件类别常量"""
        from core.ai_analyzer import EVENT_CATEGORIES, IMPACT_LEVELS
        self.assertIn('geopolitical', EVENT_CATEGORIES)
        self.assertIn('economic_data', EVENT_CATEGORIES)
        self.assertIn('central_bank', EVENT_CATEGORIES)
        self.assertIn('high', IMPACT_LEVELS)


class TestNewsCollector(unittest.TestCase):
    """测试新闻采集器"""

    def test_source_map(self):
        """测试采集器注册表"""
        from core.news_collector import NewsCollector
        self.assertIn('sina_finance', NewsCollector.SOURCE_MAP)
        self.assertIn('jin10', NewsCollector.SOURCE_MAP)
        self.assertIn('rss_gold', NewsCollector.SOURCE_MAP)

    def test_keyword_extraction(self):
        """测试关键词提取"""
        from core.news_collector import SinaFinanceCollector
        keywords = SinaFinanceCollector._extract_keywords("美联储宣布降息，黄金价格大涨")
        self.assertIn("美联储", keywords)
        self.assertIn("降息", keywords)
        self.assertIn("黄金", keywords)

    def test_generate_id(self):
        """测试 ID 生成"""
        from core.news_collector import SinaFinanceCollector
        collector = SinaFinanceCollector()
        id1 = collector._generate_id("https://example.com/1")
        id2 = collector._generate_id("https://example.com/2")
        id3 = collector._generate_id("https://example.com/1")
        self.assertNotEqual(id1, id2)
        self.assertEqual(id1, id3)


class TestPriceMonitor(unittest.TestCase):
    """测试金价监控器"""

    def test_volatility_calculation(self):
        """测试波动率计算"""
        from core.price_monitor import PriceMonitor
        monitor = PriceMonitor()
        monitor._price_history = [2000, 2010, 1995, 2005, 2020]
        volatility = monitor._calculate_volatility(2020)
        self.assertGreater(volatility, 0)

    def test_24h_stats_empty(self):
        """测试空数据时的统计"""
        from core.price_monitor import PriceMonitor
        monitor = PriceMonitor()
        stats = monitor.get_24h_stats()
        self.assertEqual(stats['current'], 0)
        self.assertEqual(stats['high'], 0)

    def test_24h_stats_with_data(self):
        """测试有数据时的统计"""
        from core.price_monitor import PriceMonitor
        monitor = PriceMonitor()
        monitor._price_history = [2000, 2010, 1990, 2020, 2015]
        stats = monitor.get_24h_stats()
        self.assertEqual(stats['high'], 2020)
        self.assertEqual(stats['low'], 1990)
        self.assertEqual(stats['current'], 2015)


class TestNotifier(unittest.TestCase):
    """测试通知器"""

    @patch('core.notifier.requests.post')
    def test_webhook_post(self, mock_post):
        """测试 Webhook 发送"""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={'code': 0})
        )

        from core.notifier import Notifier
        notifier = Notifier()
        result = notifier._post_webhook("https://example.com/hook", {"test": True})
        self.assertTrue(result)
        mock_post.assert_called_once()

    @patch('core.notifier.requests.post')
    def test_webhook_retry(self, mock_post):
        """测试 Webhook 重试机制"""
        mock_post.side_effect = Exception("连接超时")

        from core.notifier import Notifier
        notifier = Notifier()
        notifier.max_retries = 2
        result = notifier._post_webhook("https://example.com/hook", {"test": True})
        self.assertFalse(result)
        self.assertEqual(mock_post.call_count, 2)


class TestConfig(unittest.TestCase):
    """测试配置管理"""

    def test_singleton(self):
        """测试配置单例"""
        from config import Config
        c1 = Config()
        c2 = Config()
        self.assertIs(c1, c2)

    def test_get_nested_config(self):
        """测试嵌套配置读取"""
        from config import get_config
        config = get_config()
        # config.yaml 中应有 ai.provider
        provider = config.get('ai.provider', 'qwen')
        self.assertIn(provider, ['qwen', 'openai'])

    def test_default_values(self):
        """测试默认值"""
        from config import get_config
        config = get_config()
        self.assertGreater(config.confidence_threshold, 0)
        self.assertGreater(config.web_port, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
