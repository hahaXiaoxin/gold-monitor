"""
新闻采集器模块

定义 NewsSource 抽象基类，实现多个财经新闻源采集器。
NewsCollector 管理多源并行采集（ThreadPoolExecutor）、去重，返回统一 NewsItem 列表。

当前可用数据源：
- eastmoney: 东方财富 7×24 快讯 API（稳定可用）
- sina_search: 新浪财经搜索（关键词搜索）
- rss_gold: RSS 通用采集（需可用的 RSS 源）
"""

import hashlib
import json
import logging
import re
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Optional, Set

import feedparser
import requests
from bs4 import BeautifulSoup

from config import get_config
from models.schemas import NewsItem

logger = logging.getLogger(__name__)


class NewsSource(ABC):
    """新闻源抽象基类"""

    def __init__(self):
        self.config = get_config()
        self.timeout = self.config.get('collector.request_timeout', 15)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

    @abstractmethod
    def fetch(self) -> List[NewsItem]:
        """采集新闻，返回 NewsItem 列表"""
        ...

    @abstractmethod
    def get_source_name(self) -> str:
        """返回新闻源名称"""
        ...

    def _generate_id(self, url: str) -> str:
        """根据 URL 生成唯一 ID"""
        return hashlib.md5(url.encode()).hexdigest()

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        """从文本中提取关键词"""
        keywords = []
        keyword_map = {
            '黄金': '黄金', '金价': '金价', '贵金属': '贵金属',
            '美联储': '美联储', 'Fed': '美联储', '降息': '降息',
            '加息': '加息', '通胀': '通胀', 'CPI': 'CPI',
            '非农': '非农', '避险': '避险', '美元': '美元',
            '地缘': '地缘政治', '战争': '地缘政治', '制裁': '地缘政治',
            'GDP': 'GDP', 'PMI': 'PMI', '央行': '央行',
            '利率': '利率', '关税': '关税', '贸易': '贸易',
            '石油': '石油', '原油': '原油', '通缩': '通缩',
        }
        for kw, label in keyword_map.items():
            if kw in text and label not in keywords:
                keywords.append(label)
        return keywords

    @staticmethod
    def _is_gold_related(text: str) -> bool:
        """判断文本是否与黄金/贵金属/宏观经济相关"""
        gold_keywords = [
            '黄金', '金价', '贵金属', 'gold', '避险',
            '美联储', '降息', '加息', '通胀', '利率',
            '央行', '非农', '美元', 'CPI', 'GDP',
            '关税', '制裁', '地缘', '战争', '停火',
            '原油', '石油', 'PMI', '就业', '通缩',
            '国债', '收益率', '衰退', '经济数据',
        ]
        return any(kw in text for kw in gold_keywords)


class EastMoneyCollector(NewsSource):
    """
    东方财富 7×24 快讯采集器

    使用东方财富快讯 API（稳定可用），获取全球财经快讯，
    筛选出与黄金/宏观经济相关的新闻。
    """

    # 东方财富快讯 API
    # 频道 102 = 全球（含黄金、外汇、宏观等）
    API_URL = "https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html"

    def get_source_name(self) -> str:
        return "eastmoney"

    def fetch(self) -> List[NewsItem]:
        """从东方财富采集全球财经快讯"""
        news_list = []
        try:
            resp = requests.get(
                self.API_URL,
                headers={
                    **self.headers,
                    'Referer': 'https://kuaixun.eastmoney.com/',
                },
                timeout=self.timeout
            )

            if resp.status_code != 200:
                logger.warning("东方财富 API 返回 HTTP %d", resp.status_code)
                return news_list

            # 解析 JSONP 格式：var ajaxResult={...};
            text = resp.text.strip()
            text = re.sub(r'^var\s+\w+\s*=\s*', '', text).rstrip(';')
            data = json.loads(text)

            items = data.get('LivesList', [])
            for item in items:
                try:
                    title = item.get('title', '').strip()
                    digest = item.get('digest', '').strip()
                    # 清理 HTML
                    digest = re.sub(r'<[^>]+>', '', digest).strip()
                    # 去掉常见的前缀标记如 【xxx】
                    content = digest if digest else title

                    if not title or len(title) < 5:
                        continue

                    # 筛选与黄金/宏观相关的新闻
                    check_text = title + content
                    if not self._is_gold_related(check_text):
                        continue

                    url = item.get('url_w', '') or item.get('url_m', '')
                    if not url:
                        continue

                    # 解析时间 - newsid 格式: 202604083698171753
                    pub_time = datetime.now()
                    news_id = item.get('newsid', '')
                    if news_id and len(news_id) >= 8:
                        try:
                            date_str = news_id[:8]
                            pub_time = datetime.strptime(date_str, '%Y%m%d')
                            pub_time = pub_time.replace(
                                hour=datetime.now().hour,
                                minute=datetime.now().minute
                            )
                        except ValueError:
                            pass

                    news_list.append(NewsItem(
                        id=self._generate_id(url),
                        title=title,
                        content=content[:500],
                        source=self.get_source_name(),
                        url=url,
                        published_at=pub_time,
                        keywords=self._extract_keywords(check_text)
                    ))
                except Exception as e:
                    logger.debug("解析东方财富条目失败: %s", e)
                    continue

            logger.info("东方财富采集完成，获取 %d 条相关新闻", len(news_list))
        except Exception as e:
            logger.error("东方财富采集失败: %s", e)
        return news_list


class SinaFinanceCollector(NewsSource):
    """
    新浪财经搜索采集器

    通过新浪实时行情 API 获取与黄金相关的新闻资讯。
    备用方案：解析新浪财经黄金频道页面。
    """

    # 新浪财经全球新闻 API
    API_URL = "https://feed.mix.sina.com.cn/api/roll/get"
    # 备用：新浪财经黄金频道
    GOLD_PAGE = "https://finance.sina.com.cn/gold/"

    def get_source_name(self) -> str:
        return "sina_finance"

    def fetch(self) -> List[NewsItem]:
        """从新浪财经采集黄金相关新闻"""
        news_list = []

        # 方案1：尝试 Feed API（多个频道）
        channels = [
            {'pageid': 118, 'lid': 1543, 'name': '外汇'},  # 外汇频道
            {'pageid': 155, 'lid': 2516, 'name': '贵金属'},  # 贵金属
        ]
        for ch in channels:
            try:
                resp = requests.get(
                    self.API_URL,
                    params={'pageid': ch['pageid'], 'lid': ch['lid'], 'num': 30, 'page': 1},
                    headers=self.headers,
                    timeout=self.timeout
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get('result', {}).get('data', [])
                    for item in items:
                        title = item.get('title', '').strip()
                        url = item.get('url', '')
                        if title and url and self._is_gold_related(title):
                            news_list.append(NewsItem(
                                id=self._generate_id(url),
                                title=title,
                                content=title,
                                source=self.get_source_name(),
                                url=url,
                                published_at=datetime.now(),
                                keywords=self._extract_keywords(title)
                            ))
            except Exception as e:
                logger.debug("新浪 Feed API [%s] 失败: %s", ch['name'], e)

        # 方案2：爬取黄金频道页面
        if not news_list:
            try:
                resp = requests.get(
                    self.GOLD_PAGE,
                    headers=self.headers,
                    timeout=self.timeout
                )
                resp.encoding = 'utf-8'
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    links = soup.find_all('a', href=True)
                    for a in links:
                        title = a.get_text(strip=True)
                        url = a.get('href', '')
                        if (title and url and len(title) >= 8
                                and self._is_gold_related(title)
                                and url.startswith('http')):
                            news_list.append(NewsItem(
                                id=self._generate_id(url),
                                title=title,
                                content=title,
                                source=self.get_source_name(),
                                url=url,
                                published_at=datetime.now(),
                                keywords=self._extract_keywords(title)
                            ))
            except Exception as e:
                logger.debug("新浪黄金频道页面采集失败: %s", e)

        logger.info("新浪财经采集完成，获取 %d 条新闻", len(news_list))
        return news_list


class RSSCollector(NewsSource):
    """通用 RSS 新闻源采集器"""

    # 黄金相关 RSS 源
    RSS_FEEDS = [
        {
            'url': 'https://rsshub.app/cls/subject/1046',
            'name': '财联社-贵金属',
        },
        {
            'url': 'https://rsshub.app/wallstreetcn/news/global',
            'name': '华尔街见闻-全球',
        },
        {
            'url': 'https://rsshub.app/eastmoney/report/strategyreport',
            'name': '东方财富-策略报告',
        },
    ]

    def get_source_name(self) -> str:
        return "rss_gold"

    def fetch(self) -> List[NewsItem]:
        """从 RSS 源采集新闻"""
        news_list = []
        for feed_config in self.RSS_FEEDS:
            try:
                feed = feedparser.parse(
                    feed_config['url'],
                    request_headers=self.headers
                )
                for entry in feed.entries[:15]:
                    try:
                        title = entry.get('title', '')
                        content = entry.get('summary', entry.get('description', title))
                        # 清理 HTML
                        content = re.sub(r'<[^>]+>', '', content).strip()
                        link = entry.get('link', '')

                        if not title or not link:
                            continue

                        # 过滤黄金相关
                        text = title + content
                        if not self._is_gold_related(text):
                            continue

                        # 解析发布时间
                        pub_time = datetime.now()
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            from time import mktime
                            pub_time = datetime.fromtimestamp(mktime(entry.published_parsed))

                        news_list.append(NewsItem(
                            id=self._generate_id(link),
                            title=title,
                            content=content[:500],
                            source=f"rss_{feed_config['name']}",
                            url=link,
                            published_at=pub_time,
                            keywords=self._extract_keywords(text)
                        ))
                    except Exception as e:
                        logger.debug("解析 RSS 条目失败: %s", e)
                        continue

                logger.info("RSS 源 [%s] 采集完成", feed_config['name'])
            except Exception as e:
                logger.error("RSS 源 [%s] 采集失败: %s", feed_config['name'], e)

        logger.info("RSS 采集完成，共获取 %d 条新闻", len(news_list))
        return news_list


class NewsCollector:
    """新闻采集管理器，管理多源并行采集并去重"""

    # 采集器注册表
    SOURCE_MAP = {
        'eastmoney': EastMoneyCollector,
        'sina_finance': SinaFinanceCollector,
        'rss_gold': RSSCollector,
    }

    def __init__(self):
        self.config = get_config()
        self.max_workers = self.config.get('collector.max_workers', 5)
        enabled = self.config.get('collector.enabled_sources', list(self.SOURCE_MAP.keys()))

        # 实例化启用的采集器
        self.sources: List[NewsSource] = []
        for name in enabled:
            if name in self.SOURCE_MAP:
                self.sources.append(self.SOURCE_MAP[name]())
                logger.info("已启用新闻源: %s", name)
            else:
                logger.warning("未知的新闻源: %s，已跳过", name)

    def collect_all(self) -> List[NewsItem]:
        """
        并行采集所有新闻源，去重后返回统一列表。
        单个源失败不影响其他源。
        """
        all_news: List[NewsItem] = []
        seen_ids: Set[str] = set()

        logger.info("开始并行采集，共 %d 个新闻源", len(self.sources))

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(source.fetch): source.get_source_name()
                for source in self.sources
            }

            for future in as_completed(futures):
                source_name = futures[future]
                try:
                    news_items = future.result(timeout=30)
                    for item in news_items:
                        # 去重：基于 ID（URL hash）
                        if item.id and item.id not in seen_ids:
                            seen_ids.add(item.id)
                            all_news.append(item)
                    logger.info("新闻源 [%s] 返回 %d 条（去重后）", source_name, len(news_items))
                except Exception as e:
                    logger.error("新闻源 [%s] 采集异常: %s", source_name, e)

        # 按发布时间倒序排列
        all_news.sort(key=lambda x: x.published_at, reverse=True)
        logger.info("全部采集完成，共获取 %d 条不重复新闻", len(all_news))
        return all_news
