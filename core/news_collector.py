"""
新闻采集器模块

定义 NewsSource 抽象基类，实现多个财经新闻源采集器。
NewsCollector 管理多源并行采集（ThreadPoolExecutor）、去重，返回统一 NewsItem 列表。
"""

import hashlib
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


class SinaFinanceCollector(NewsSource):
    """新浪财经黄金新闻采集器"""

    # 新浪财经黄金频道 RSS / 页面
    RSS_URL = "https://finance.sina.com.cn/money/nmetal/hjzx.shtml"

    def get_source_name(self) -> str:
        return "sina_finance"

    def fetch(self) -> List[NewsItem]:
        """从新浪财经采集黄金相关新闻"""
        news_list = []
        try:
            resp = requests.get(
                self.RSS_URL,
                headers=self.headers,
                timeout=self.timeout
            )
            resp.encoding = 'utf-8'
            soup = BeautifulSoup(resp.text, 'lxml')

            # 解析新闻列表
            articles = soup.select('.news-item, .feed-card-item, .listBlk a, ul.list01 li a')
            for article in articles[:20]:  # 最多取 20 条
                try:
                    # 尝试不同的页面结构
                    if article.name == 'a':
                        title = article.get_text(strip=True)
                        url = article.get('href', '')
                    else:
                        link = article.select_one('a')
                        if not link:
                            continue
                        title = link.get_text(strip=True)
                        url = link.get('href', '')

                    if not title or not url or len(title) < 5:
                        continue

                    # 过滤非黄金相关
                    gold_keywords = ['黄金', '金价', '贵金属', 'gold', '避险', '美联储',
                                     '降息', '加息', '通胀', 'CPI', '非农']
                    if not any(kw in title for kw in gold_keywords):
                        continue

                    # 补全 URL
                    if url.startswith('//'):
                        url = 'https:' + url
                    elif url.startswith('/'):
                        url = 'https://finance.sina.com.cn' + url

                    news_list.append(NewsItem(
                        id=self._generate_id(url),
                        title=title,
                        content=title,  # 摘要暂用标题
                        source=self.get_source_name(),
                        url=url,
                        published_at=datetime.now(),
                        keywords=self._extract_keywords(title)
                    ))
                except Exception as e:
                    logger.debug("解析新浪新闻条目失败: %s", e)
                    continue

            logger.info("新浪财经采集完成，获取 %d 条新闻", len(news_list))
        except Exception as e:
            logger.error("新浪财经采集失败: %s", e)
        return news_list

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
            'GDP': 'GDP', 'PMI': 'PMI',
        }
        for kw, label in keyword_map.items():
            if kw in text and label not in keywords:
                keywords.append(label)
        return keywords


class Jin10Collector(NewsSource):
    """金十数据新闻采集器"""

    # 金十数据快讯页面
    BASE_URL = "https://www.jin10.com"
    FLASH_URL = "https://flash-api.jin10.com/get_flash_list"

    def get_source_name(self) -> str:
        return "jin10"

    def fetch(self) -> List[NewsItem]:
        """从金十数据采集快讯"""
        news_list = []
        try:
            # 尝试通过 API 获取快讯
            resp = requests.get(
                self.FLASH_URL,
                headers={**self.headers, 'x-app-id': 'bVBF4FyRTn5NJF5n'},
                timeout=self.timeout,
                params={'max_time': '', 'channel': '-8200'}
            )

            if resp.status_code == 200:
                data = resp.json()
                items = data.get('data', [])
                for item in items[:20]:
                    try:
                        content = item.get('data', {}).get('content', '')
                        # 清理 HTML 标签
                        content = re.sub(r'<[^>]+>', '', content).strip()
                        if not content:
                            continue

                        # 过滤黄金相关
                        gold_keywords = ['黄金', '金价', '贵金属', 'gold', '避险',
                                         '美联储', '降息', '加息', '通胀', '利率']
                        if not any(kw in content for kw in gold_keywords):
                            continue

                        time_str = item.get('time', '')
                        pub_time = datetime.now()
                        if time_str:
                            try:
                                pub_time = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                            except (ValueError, TypeError):
                                pass

                        url = f"{self.BASE_URL}/flash/{item.get('id', '')}"
                        news_list.append(NewsItem(
                            id=self._generate_id(url),
                            title=content[:80],
                            content=content,
                            source=self.get_source_name(),
                            url=url,
                            published_at=pub_time,
                            keywords=SinaFinanceCollector._extract_keywords(content)
                        ))
                    except Exception as e:
                        logger.debug("解析金十快讯条目失败: %s", e)
                        continue

            logger.info("金十数据采集完成，获取 %d 条新闻", len(news_list))
        except Exception as e:
            logger.error("金十数据采集失败: %s", e)
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
                        gold_keywords = ['黄金', '金价', '贵金属', 'gold', '避险',
                                         '美联储', '降息', '加息', '通胀', '利率',
                                         '央行', '非农', '美元', 'CPI']
                        if not any(kw in text for kw in gold_keywords):
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
                            keywords=SinaFinanceCollector._extract_keywords(text)
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
        'sina_finance': SinaFinanceCollector,
        'jin10': Jin10Collector,
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
