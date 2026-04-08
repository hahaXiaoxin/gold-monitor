"""
通知器模块

实现 Webhook 通知发送，支持飞书、企业微信、钉钉消息格式。
Markdown 格式化，发送失败自动重试。
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from config import get_config
from models.schemas import AnalysisResult, DailySummary

logger = logging.getLogger(__name__)

# 方向中文映射
DIRECTION_MAP = {
    'bullish': '🟢 利好（看涨）',
    'bearish': '🔴 利空（看跌）',
    'neutral': '⚪ 中性（观望）',
}

ACTION_MAP = {
    'buy': '💰 建议买入',
    'sell': '📉 建议卖出',
    'hold': '⏸️ 建议持有',
}

IMPACT_MAP = {
    'high': '🔥 高影响',
    'medium': '⚡ 中影响',
    'low': '💤 低影响',
}

CATEGORY_MAP = {
    'geopolitical': '🌍 地缘政治',
    'economic_data': '📊 经济数据',
    'central_bank': '🏦 央行政策',
    'usd_trend': '💵 美元走势',
    'market_sentiment': '📈 市场情绪',
    'technical': '📐 技术面',
    'general': '📰 综合',
}


class Notifier:
    """通知器，管理 Webhook 消息发送"""

    def __init__(self):
        self.config = get_config()
        self.max_retries = self.config.get('notification.max_retries', 3)
        self.enabled_channels = self.config.get('notification.enabled_channels', [])

        # 加载各渠道 Webhook URL
        self.webhooks = {
            'feishu': self.config.get_env('FEISHU_WEBHOOK_URL'),
            'wecom': self.config.get_env('WECOM_WEBHOOK_URL'),
            'dingtalk': self.config.get_env('DINGTALK_WEBHOOK_URL'),
        }

        active = [ch for ch in self.enabled_channels if self.webhooks.get(ch)]
        logger.info("通知器初始化完成，已启用渠道: %s", active or '无')

    def notify_analysis(self, analysis: AnalysisResult, price: float = 0) -> bool:
        """
        发送分析结果通知

        Args:
            analysis: 分析结果
            price: 当前金价

        Returns:
            是否发送成功
        """
        direction = DIRECTION_MAP.get(analysis.direction, analysis.direction)
        action = ACTION_MAP.get(analysis.suggested_action, analysis.suggested_action)
        impact = IMPACT_MAP.get(analysis.impact_level, analysis.impact_level)
        category = CATEGORY_MAP.get(analysis.event_category, analysis.event_category)

        title = f"⚜️ 黄金分析提醒 - {direction}"
        content_lines = [
            f"**{title}**",
            "",
            f"📍 分析方向: {direction}",
            f"📊 置信率: **{analysis.confidence:.0f}%**",
            f"🎯 操作建议: {action}",
            f"🏷️ 事件类别: {category}",
            f"⚡ 影响等级: {impact}",
        ]

        if price > 0:
            content_lines.append(f"💰 当前金价: **${price:.2f}**/盎司")

        content_lines.extend([
            "",
            f"📝 分析理由:",
            f"> {analysis.reasoning}",
            "",
            f"🔑 关键因素: {', '.join(analysis.key_factors[:5])}",
            "",
            f"⏰ 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ])

        content = "\n".join(content_lines)
        return self._send_to_all(title, content)

    def notify_daily_summary(self, summary: DailySummary) -> bool:
        """
        发送每日总结通知

        Args:
            summary: 每日总结

        Returns:
            是否发送成功
        """
        title = f"📋 黄金每日总结 - {summary.date}"

        content_lines = [
            f"**{title}**",
            "",
            f"💰 金价变动: **{summary.price_change:+.2f}** ({summary.price_change_percent:+.2f}%)",
            f"📊 今日分析次数: {summary.total_analyses}",
        ]

        if summary.accuracy_rate > 0:
            content_lines.append(f"🎯 预测准确率: {summary.accuracy_rate:.1f}%")

        content_lines.extend(["", "---", "", "📰 **今日关键事件:**", ""])

        for i, event in enumerate(summary.key_events[:5], 1):
            impact = IMPACT_MAP.get(event.impact_level, '')
            direction = '🟢' if event.direction == 'bullish' else ('🔴' if event.direction == 'bearish' else '⚪')
            content_lines.append(f"{i}. {direction} {event.title} {impact}")
            if event.summary:
                content_lines.append(f"   > {event.summary}")

        content_lines.extend(["", "---", "", "📝 **综合总结:**", "", summary.summary[:500]])

        # 添加维度分析
        if summary.dimensions:
            content_lines.extend(["", "---", "", "🔍 **多维度分析:**", ""])
            for dim_key, dim_text in summary.dimensions.items():
                dim_name = CATEGORY_MAP.get(dim_key, dim_key)
                content_lines.append(f"**{dim_name}**: {dim_text}")

        content_lines.extend([
            "",
            f"⏰ 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ])

        content = "\n".join(content_lines)
        return self._send_to_all(title, content)

    def _send_to_all(self, title: str, content: str) -> bool:
        """发送到所有启用的渠道"""
        success = False
        for channel in self.enabled_channels:
            webhook_url = self.webhooks.get(channel)
            if not webhook_url:
                continue

            try:
                if channel == 'feishu':
                    result = self._send_feishu(webhook_url, title, content)
                elif channel == 'wecom':
                    result = self._send_wecom(webhook_url, content)
                elif channel == 'dingtalk':
                    result = self._send_dingtalk(webhook_url, title, content)
                else:
                    logger.warning("未知的通知渠道: %s", channel)
                    continue

                if result:
                    success = True
                    logger.info("通知发送成功: [%s]", channel)
                else:
                    logger.error("通知发送失败: [%s]", channel)
            except Exception as e:
                logger.error("通知发送异常 [%s]: %s", channel, e)

        return success

    def _send_feishu(self, url: str, title: str, content: str) -> bool:
        """发送飞书 Webhook 消息"""
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "gold"
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": content
                    }
                ]
            }
        }
        return self._post_webhook(url, payload)

    def _send_wecom(self, url: str, content: str) -> bool:
        """发送企业微信 Webhook 消息"""
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": content}
        }
        return self._post_webhook(url, payload)

    def _send_dingtalk(self, url: str, title: str, content: str) -> bool:
        """发送钉钉 Webhook 消息"""
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": content
            }
        }
        return self._post_webhook(url, payload)

    def _post_webhook(self, url: str, payload: dict) -> bool:
        """POST 发送 Webhook，带重试机制"""
        for attempt in range(self.max_retries):
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=10
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # 各平台成功判断
                    if data.get('code') == 0 or data.get('errcode') == 0 or data.get('StatusCode') == 0:
                        return True
                    # 有些平台直接返回 200 就是成功
                    return True

                logger.warning(
                    "Webhook 响应异常 (尝试 %d/%d): status=%d, body=%s",
                    attempt + 1, self.max_retries, resp.status_code, resp.text[:100]
                )
            except Exception as e:
                logger.warning(
                    "Webhook 发送失败 (尝试 %d/%d): %s",
                    attempt + 1, self.max_retries, e
                )

            if attempt < self.max_retries - 1:
                time.sleep(2 ** attempt)

        return False
