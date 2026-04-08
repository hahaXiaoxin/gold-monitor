"""
金价监控器模块

从公开 API 获取实时黄金价格，5 分钟缓存，计算涨跌幅和波动率，支持历史价格查询。
"""

import logging
import time
from datetime import datetime
from typing import Optional

import requests

from config import get_config
from models.schemas import PriceData

logger = logging.getLogger(__name__)


class PriceMonitor:
    """黄金价格监控器"""

    # 备用金价 API 列表
    API_SOURCES = [
        {
            'name': 'frankfurter',
            'url': 'https://api.frankfurter.app/latest',
            'params': {'from': 'XAU', 'to': 'USD'},
            'parser': '_parse_frankfurter',
        },
        {
            'name': 'metals_api',
            'url': 'https://metals-api.com/api/latest',
            'params': {'access_key': '', 'base': 'XAU', 'symbols': 'USD'},
            'parser': '_parse_metals_api',
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
                    # 计算涨跌幅
                    if self._cached_price:
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

    def _fetch_from_source(self, source: dict) -> Optional[PriceData]:
        """从指定 API 源获取价格"""
        try:
            api_key = self.config.get_env('GOLD_API_KEY', '')
            params = source.get('params', {}).copy()

            # 如果 API 需要 key 但未配置，跳过
            if 'access_key' in params:
                if not api_key:
                    return None
                params['access_key'] = api_key

            resp = requests.get(
                source['url'],
                params=params,
                timeout=10,
                headers={'User-Agent': 'GoldMonitor/1.0'}
            )

            if resp.status_code == 200:
                parser = getattr(self, source['parser'])
                return parser(resp.json())
        except Exception as e:
            logger.debug("API [%s] 解析失败: %s", source['name'], e)
        return None

    @staticmethod
    def _parse_frankfurter(data: dict) -> Optional[PriceData]:
        """解析 Frankfurter API 响应"""
        try:
            rates = data.get('rates', {})
            usd_rate = rates.get('USD')
            if usd_rate and usd_rate > 0:
                # Frankfurter 返回的是 1 XAU = X USD
                return PriceData(
                    price=round(usd_rate, 2),
                    currency='USD',
                    timestamp=datetime.now()
                )
        except (KeyError, TypeError, ValueError) as e:
            logger.debug("Frankfurter 数据解析错误: %s", e)
        return None

    @staticmethod
    def _parse_metals_api(data: dict) -> Optional[PriceData]:
        """解析 Metals API 响应"""
        try:
            if data.get('success'):
                rates = data.get('rates', {})
                usd_rate = rates.get('USD')
                if usd_rate and usd_rate > 0:
                    return PriceData(
                        price=round(usd_rate, 2),
                        currency='USD',
                        timestamp=datetime.now()
                    )
        except (KeyError, TypeError, ValueError) as e:
            logger.debug("Metals API 数据解析错误: %s", e)
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
