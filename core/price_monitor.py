"""
金价监控器模块

从新浪/腾讯行情 API 获取实时黄金价格（纽约金 COMEX GC），
5 分钟缓存，计算涨跌幅和波动率，支持历史价格查询。
"""

import logging
import re
import time
from datetime import datetime
from typing import List, Optional

import requests

from config import get_config
from models.schemas import PriceData

logger = logging.getLogger(__name__)


class PriceMonitor:
    """黄金价格监控器"""

    # 行情 API 源列表（优先级从高到低）
    API_SOURCES = [
        {
            'name': 'sina_hq',
            'url': 'https://hq.sinajs.cn/list=hf_GC',
            'headers': {'Referer': 'https://finance.sina.com.cn'},
            'parser': '_parse_sina_hq',
        },
        {
            'name': 'tencent_hq',
            'url': 'https://qt.gtimg.cn/q=hf_GC',
            'headers': {},
            'parser': '_parse_tencent_hq',
        },
    ]

    def __init__(self):
        self.config = get_config()
        self.cache_ttl = self.config.get('price_monitor.cache_ttl', 300)  # 5分钟缓存
        self._cached_price: Optional[PriceData] = None
        self._cache_time: float = 0
        self._price_history: list = []  # 内存中保存最近的价格历史

    def get_current_price(self) -> Optional[PriceData]:
        """
        获取当前黄金价格。
        使用缓存机制，5 分钟内复用缓存数据。
        API 不可用时返回最近缓存。
        """
        now = time.time()

        # 检查缓存是否有效
        if self._cached_price and (now - self._cache_time) < self.cache_ttl:
            return self._cached_price

        # 依次尝试各 API 源
        for source in self.API_SOURCES:
            try:
                price_data = self._fetch_from_source(source)
                if price_data:
                    price_data.source = source['name']

                    # 仅当解析器未返回有效涨跌数据时，才用缓存补算
                    if price_data.change_24h == 0 and self._cached_price:
                        price_data.change_24h = round(
                            price_data.price - self._cached_price.price, 2
                        )
                        if self._cached_price.price > 0:
                            price_data.change_percent_24h = round(
                                price_data.change_24h / self._cached_price.price * 100, 4
                            )

                    # 计算波动率（基于内存中的价格历史）
                    price_data.volatility = self._calculate_volatility(price_data.price)

                    # 更新缓存
                    self._cached_price = price_data
                    self._cache_time = now
                    self._price_history.append(price_data.price)

                    # 保留最近 288 条记录（24小时，每5分钟一条）
                    if len(self._price_history) > 288:
                        self._price_history = self._price_history[-288:]

                    logger.info(
                        "金价更新: $%.2f (来源: %s)",
                        price_data.price, source['name']
                    )
                    return price_data
            except Exception as e:
                logger.warning("金价 API [%s] 请求失败: %s", source['name'], e)
                continue

        # 所有 API 都失败，返回缓存
        if self._cached_price:
            logger.warning("所有金价 API 不可用，使用缓存数据")
            return self._cached_price

        logger.error("无法获取金价数据，且无可用缓存")
        return None

    def fetch_all_sources(self) -> List[PriceData]:
        """
        遍历所有 API 源，独立采集每个源的价格数据。
        返回带 source 标记的 PriceData 列表，各源互不覆盖。
        """
        results: List[PriceData] = []

        for source in self.API_SOURCES:
            try:
                price_data = self._fetch_from_source(source)
                if price_data:
                    price_data.source = source['name']
                    price_data.volatility = self._calculate_volatility(price_data.price)
                    results.append(price_data)
                    logger.info(
                        "金价采集 [%s]: $%.2f, 涨跌: %+.2f%%",
                        source['name'], price_data.price, price_data.change_percent_24h
                    )
            except Exception as e:
                logger.warning("金价 API [%s] 采集失败: %s", source['name'], e)
                continue

        # 同步更新缓存（取第一个成功的）
        if results:
            now = time.time()
            self._cached_price = results[0]
            self._cache_time = now
            self._price_history.append(results[0].price)
            if len(self._price_history) > 288:
                self._price_history = self._price_history[-288:]

        return results

    def _fetch_from_source(self, source: dict) -> Optional[PriceData]:
        """从指定 API 源获取价格"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
                **source.get('headers', {})
            }

            resp = requests.get(
                source['url'],
                timeout=10,
                headers=headers
            )
            resp.encoding = 'gbk'

            if resp.status_code == 200:
                parser = getattr(self, source['parser'])
                return parser(resp.text)
        except Exception as e:
            logger.debug("API [%s] 解析失败: %s", source['name'], e)
        return None

    @staticmethod
    def _parse_sina_hq(text: str) -> Optional[PriceData]:
        """
        解析新浪行情 API 响应
        格式: var hq_str_hf_GC="最新价,,昨收,开盘,最高,最低,时间,买价,卖价,...,日期,名称,0";
        """
        try:
            match = re.search(r'"([^"]+)"', text)
            if not match:
                return None

            fields = match.group(1).split(',')
            if len(fields) < 6:
                return None

            price = float(fields[0])
            if price <= 0:
                return None

            yesterday_close = float(fields[2]) if fields[2] else 0
            high = float(fields[4]) if fields[4] else price
            low = float(fields[5]) if fields[5] else price

            change = round(price - yesterday_close, 2) if yesterday_close > 0 else 0
            change_pct = round(change / yesterday_close * 100, 4) if yesterday_close > 0 else 0

            return PriceData(
                price=round(price, 2),
                currency='USD',
                timestamp=datetime.now(),
                change_24h=change,
                change_percent_24h=change_pct,
                high_24h=round(high, 2),
                low_24h=round(low, 2),
            )
        except (ValueError, IndexError) as e:
            logger.debug("新浪行情解析错误: %s", e)
        return None

    @staticmethod
    def _parse_tencent_hq(text: str) -> Optional[PriceData]:
        """
        解析腾讯行情 API 响应
        格式: v_hf_GC="最新价,涨跌,昨收,开盘,最高,最低,时间,买价,卖价,...,日期,名称";
        """
        try:
            match = re.search(r'"([^"]+)"', text)
            if not match:
                return None

            fields = match.group(1).split(',')
            if len(fields) < 6:
                return None

            price = float(fields[0])
            if price <= 0:
                return None

            change = float(fields[1]) if fields[1] else 0
            yesterday_close = float(fields[2]) if fields[2] else 0
            high = float(fields[4]) if fields[4] else price
            low = float(fields[5]) if fields[5] else price

            change_pct = round(change / yesterday_close * 100, 4) if yesterday_close > 0 else 0

            return PriceData(
                price=round(price, 2),
                currency='USD',
                timestamp=datetime.now(),
                change_24h=round(change, 2),
                change_percent_24h=change_pct,
                high_24h=round(high, 2),
                low_24h=round(low, 2),
            )
        except (ValueError, IndexError) as e:
            logger.debug("腾讯行情解析错误: %s", e)
        return None

    def _calculate_volatility(self, current_price: float) -> float:
        """
        计算短期波动率（简单标准差百分比）。
        基于内存中最近的价格历史。
        """
        if len(self._price_history) < 2:
            return 0.0

        prices = self._price_history[-24:]  # 最近 24 个数据点
        if not prices:
            return 0.0

        mean = sum(prices) / len(prices)
        if mean == 0:
            return 0.0

        variance = sum((p - mean) ** 2 for p in prices) / len(prices)
        std_dev = variance ** 0.5
        volatility = round(std_dev / mean * 100, 4)  # 百分比形式
        return volatility

    def get_24h_stats(self) -> dict:
        """获取 24 小时统计数据"""
        if not self._price_history:
            return {
                'high': 0, 'low': 0, 'open': 0,
                'current': 0, 'change': 0, 'change_percent': 0
            }

        prices = self._price_history
        current = prices[-1] if prices else 0
        open_price = prices[0] if prices else 0
        high = max(prices) if prices else 0
        low = min(prices) if prices else 0
        change = round(current - open_price, 2)
        change_pct = round(change / open_price * 100, 4) if open_price > 0 else 0

        return {
            'high': round(high, 2),
            'low': round(low, 2),
            'open': round(open_price, 2),
            'current': round(current, 2),
            'change': change,
            'change_percent': change_pct
        }
