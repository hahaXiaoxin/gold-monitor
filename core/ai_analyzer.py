"""
AI 分析器模块

采用策略模式（Strategy Pattern），定义 AIProvider 抽象基类，
实现 QwenProvider（通义千问 DashScope）和 OpenAIProvider（预留扩展）。
AIAnalyzer 作为调度类，通过工厂方法根据配置创建对应的 Provider。
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import get_config
from models.schemas import (
    AnalysisResult,
    DailySummary,
    KeyEvent,
    NewsItem,
    PriceData,
)

logger = logging.getLogger(__name__)

# ======================== 分析维度常量 ========================

EVENT_CATEGORIES = {
    'geopolitical': '地缘政治',
    'economic_data': '经济数据',
    'central_bank': '央行政策',
    'usd_trend': '美元走势',
    'market_sentiment': '市场情绪',
    'technical': '技术面',
    'general': '综合',
}

IMPACT_LEVELS = {
    'high': '高',
    'medium': '中',
    'low': '低',
}


# ======================== 策略模式：AI Provider ========================

class AIProvider(ABC):
    """AI 提供商抽象基类（策略模式接口）"""

    @abstractmethod
    def analyze_news(
        self,
        news_items: List[NewsItem],
        price_data: Optional[PriceData] = None,
        historical_context: Optional[List[str]] = None
    ) -> AnalysisResult:
        """
        分析新闻，返回结构化分析结果。

        Args:
            news_items: 待分析的新闻列表
            price_data: 当前金价数据（可选）
            historical_context: 知识库中检索到的历史经验（可选）

        Returns:
            AnalysisResult 分析结果
        """
        ...

    @abstractmethod
    def generate_daily_summary(
        self,
        analyses: List[AnalysisResult],
        price_changes: List[PriceData],
        news_items: List[NewsItem]
    ) -> DailySummary:
        """
        生成每日总结报告（多维度分析）。

        Args:
            analyses: 当日所有分析结果
            price_changes: 当日价格变动数据
            news_items: 当日所有新闻

        Returns:
            DailySummary 每日总结
        """
        ...

    @staticmethod
    def _sanitize_text(text: str) -> str:
        """清理文本中的 URL，避免触发 API 的 URL 检测"""
        import re
        # 移除 http/https URL
        text = re.sub(r'https?://\S+', '', text)
        # 移除 www 开头的链接
        text = re.sub(r'www\.\S+', '', text)
        return text.strip()

    def _build_analysis_prompt(
        self,
        news_items: List[NewsItem],
        price_data: Optional[PriceData],
        historical_context: Optional[List[str]]
    ) -> str:
        """构建新闻分析 prompt"""
        news_text = "\n".join([
            f"- [{item.source}] {self._sanitize_text(item.title)}: {self._sanitize_text(item.content[:200])}"
            for item in news_items
        ])

        price_info = ""
        if price_data:
            price_info = f"""
当前黄金价格信息:
- 价格: ${price_data.price}/盎司
- 24小时涨跌: {price_data.change_percent_24h:+.2f}%
- 波动率: {price_data.volatility:.4f}%
"""

        context_info = ""
        if historical_context:
            context_info = "\n历史相似案例参考:\n" + "\n".join([
                f"- {ctx}" for ctx in historical_context[:5]
            ])

        return f"""你是一位专业的黄金市场分析师。请分析以下新闻信息对黄金价格的影响。

{price_info}

近期新闻:
{news_text}

{context_info}

请以 JSON 格式返回分析结果，严格遵循以下结构:
{{
    "direction": "bullish/bearish/neutral",
    "confidence": 0-100的整数,
    "reasoning": "详细分析理由",
    "suggested_action": "buy/sell/hold",
    "key_factors": ["因素1", "因素2", ...],
    "impact_level": "high/medium/low",
    "event_category": "geopolitical/economic_data/central_bank/usd_trend/market_sentiment/technical/general"
}}

分析要求:
1. direction: bullish 表示利好（金价可能上涨），bearish 表示利空（金价可能下跌），neutral 表示中性
2. confidence: 置信率，0表示完全不确定，100表示非常确定
3. impact_level: 评估新闻事件对金价的影响程度
4. event_category: 将新闻归类到最匹配的维度
5. 分析时综合考虑地缘政治、经济数据、央行政策、美元走势、市场情绪等多个维度

只返回 JSON，不要包含其他文字。"""

    def _build_summary_prompt(
        self,
        analyses: List[AnalysisResult],
        price_changes: List[PriceData],
        news_items: List[NewsItem]
    ) -> str:
        """构建每日总结 prompt"""
        # 分析结果摘要
        analyses_text = "\n".join([
            f"- [{a.event_category}] {a.direction}(置信率{a.confidence}%): {a.reasoning[:100]}"
            for a in analyses
        ])

        # 价格变动
        price_text = ""
        if price_changes:
            first = price_changes[0]
            last = price_changes[-1]
            price_text = f"开盘 ${first.price} → 收盘 ${last.price}，变动 {last.change_percent_24h:+.2f}%"

        # 新闻标题列表（清理 URL）
        news_titles = "\n".join([f"- [{n.source}] {self._sanitize_text(n.title)}" for n in news_items[:20]])

        return f"""你是一位专业的黄金市场分析师。请为今日的黄金市场生成每日总结报告。

今日价格走势: {price_text}

今日分析记录:
{analyses_text}

今日重要新闻:
{news_titles}

请以 JSON 格式返回总结报告，严格遵循以下结构:
{{
    "summary": "200-500字的综合总结，涵盖今日市场概况和趋势判断",
    "key_events": [
        {{
            "title": "事件标题",
            "summary": "一句话描述事件影响",
            "impact_level": "high/medium/low",
            "event_category": "geopolitical/economic_data/central_bank/usd_trend/market_sentiment/technical",
            "direction": "bullish/bearish/neutral"
        }}
    ],
    "dimensions": {{
        "geopolitical": "地缘政治维度分析（无则写'今日无重大地缘政治事件'）",
        "economic_data": "经济数据维度分析",
        "central_bank": "央行政策维度分析",
        "usd_trend": "美元走势维度分析",
        "market_sentiment": "市场情绪维度分析",
        "technical": "技术面维度分析"
    }},
    "accuracy_review": "回顾今日给出的买卖建议是否与实际走势一致",
    "tomorrow_outlook": "对明日黄金走势的简要展望"
}}

要求:
1. key_events 提取今日最关键的 3-5 个事件
2. dimensions 从 6 个维度全面分析，每个维度 1-3 句话
3. 分析要客观专业，避免过度主观

只返回 JSON，不要包含其他文字。"""

    @staticmethod
    def _parse_analysis_response(response_text: str) -> AnalysisResult:
        """解析 AI 响应为 AnalysisResult"""
        try:
            # 尝试提取 JSON（处理可能包含 markdown 代码块的情况）
            text = response_text.strip()
            if '```json' in text:
                text = text.split('```json')[1].split('```')[0].strip()
            elif '```' in text:
                text = text.split('```')[1].split('```')[0].strip()

            data = json.loads(text)
            return AnalysisResult(
                direction=data.get('direction', 'neutral'),
                confidence=float(data.get('confidence', 50)),
                reasoning=data.get('reasoning', '分析数据不足'),
                suggested_action=data.get('suggested_action', 'hold'),
                key_factors=data.get('key_factors', []),
                impact_level=data.get('impact_level', 'medium'),
                event_category=data.get('event_category', 'general'),
                created_at=datetime.now()
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("AI 响应解析失败: %s，原始响应: %s", e, response_text[:200])
            return AnalysisResult(
                direction='neutral',
                confidence=0,
                reasoning=f'AI 响应解析失败: {str(e)}',
                suggested_action='hold',
                impact_level='low',
                event_category='general',
                created_at=datetime.now()
            )

    @staticmethod
    def _parse_summary_response(response_text: str, date: str) -> DailySummary:
        """解析 AI 响应为 DailySummary"""
        try:
            text = response_text.strip()
            if '```json' in text:
                text = text.split('```json')[1].split('```')[0].strip()
            elif '```' in text:
                text = text.split('```')[1].split('```')[0].strip()

            data = json.loads(text)

            # 解析关键事件
            key_events = []
            for e in data.get('key_events', []):
                key_events.append(KeyEvent(
                    title=e.get('title', ''),
                    summary=e.get('summary', ''),
                    url='',  # 总结中的事件可能没有 URL
                    source='daily_summary',
                    direction=e.get('direction', 'neutral'),
                    impact_level=e.get('impact_level', 'medium'),
                    event_category=e.get('event_category', 'general'),
                ))

            return DailySummary(
                date=date,
                summary=data.get('summary', '暂无总结'),
                key_events=key_events,
                dimensions=data.get('dimensions', {}),
                created_at=datetime.now()
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("每日总结解析失败: %s", e)
            return DailySummary(
                date=date,
                summary=f'总结生成失败: {str(e)}',
                created_at=datetime.now()
            )


class QwenProvider(AIProvider):
    """通义千问（阿里云 DashScope API）实现"""

    def __init__(self):
        self.config = get_config()
        self.api_key = self.config.dashscope_api_key
        self.model = self.config.qwen_model
        self.max_retries = self.config.get('ai.max_retries', 3)
        self.retry_delay = self.config.get('ai.retry_base_delay', 2)

        if not self.api_key:
            logger.warning("DashScope API Key 未配置，通义千问功能将不可用")

    def _call_api(self, prompt: str) -> str:
        """调用通义千问 API（含重试机制）"""
        import dashscope
        from dashscope import Generation

        dashscope.api_key = self.api_key

        for attempt in range(self.max_retries):
            try:
                # 使用 prompt + text 格式调用（稳定兼容）
                response = Generation.call(
                    model=self.model,
                    prompt=prompt,
                    result_format='text',
                    max_tokens=2000,
                    temperature=0.3,
                )

                # 检查响应状态
                status = getattr(response, 'status_code', None)
                if status and str(status) != '200' and 'OK' not in str(status):
                    logger.warning(
                        "通义千问返回非 200 状态: %s, code=%s, message=%s",
                        status, getattr(response, 'code', ''),
                        getattr(response, 'message', '')
                    )
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay * (2 ** attempt))
                    continue

                # 从 text 格式响应中提取文本
                output = response.output
                if output:
                    text = output.get('text', '') if hasattr(output, 'get') else getattr(output, 'text', '')
                    if text:
                        return text

                logger.warning(
                    "通义千问返回空响应，尝试 %d/%d, output=%s",
                    attempt + 1, self.max_retries, str(output)[:200] if output else 'None'
                )
            except Exception as e:
                logger.warning(
                    "通义千问 API 调用失败 (尝试 %d/%d): %s",
                    attempt + 1, self.max_retries, e
                )
            if attempt < self.max_retries - 1:
                delay = self.retry_delay * (2 ** attempt)  # 指数退避
                time.sleep(delay)

        raise RuntimeError(f"通义千问 API 调用失败，已重试 {self.max_retries} 次")

    def analyze_news(
        self,
        news_items: List[NewsItem],
        price_data: Optional[PriceData] = None,
        historical_context: Optional[List[str]] = None
    ) -> AnalysisResult:
        """使用通义千问分析新闻"""
        if not news_items:
            return AnalysisResult(
                direction='neutral', confidence=0,
                reasoning='无新闻数据', suggested_action='hold',
                impact_level='low', event_category='general',
                created_at=datetime.now()
            )

        prompt = self._build_analysis_prompt(news_items, price_data, historical_context)
        response = self._call_api(prompt)
        result = self._parse_analysis_response(response)

        # 关联新闻 ID
        result.news_ids = [n.id for n in news_items if n.id]
        logger.info(
            "AI 分析完成: 方向=%s, 置信率=%.0f%%, 类别=%s",
            result.direction, result.confidence, result.event_category
        )
        return result

    def generate_daily_summary(
        self,
        analyses: List[AnalysisResult],
        price_changes: List[PriceData],
        news_items: List[NewsItem]
    ) -> DailySummary:
        """使用通义千问生成每日总结"""
        today = datetime.now().strftime('%Y-%m-%d')
        prompt = self._build_summary_prompt(analyses, price_changes, news_items)
        response = self._call_api(prompt)
        summary = self._parse_summary_response(response, today)

        # 补充统计数据
        summary.total_analyses = len(analyses)
        if price_changes:
            first_price = price_changes[0].price
            last_price = price_changes[-1].price
            summary.price_change = round(last_price - first_price, 2)
            if first_price > 0:
                summary.price_change_percent = round(
                    (last_price - first_price) / first_price * 100, 2
                )

        logger.info("每日总结生成完成: %s", today)
        return summary


class OpenAIProvider(AIProvider):
    """OpenAI 兼容 API 实现（预留扩展）"""

    def __init__(self):
        self.config = get_config()
        self.api_key = self.config.openai_api_key
        self.base_url = self.config.openai_base_url
        self.model = self.config.openai_model
        self.max_retries = self.config.get('ai.max_retries', 3)
        self.retry_delay = self.config.get('ai.retry_base_delay', 2)

        if not self.api_key:
            logger.warning("OpenAI API Key 未配置")

    def _call_api(self, prompt: str) -> str:
        """调用 OpenAI 兼容 API（含重试机制）"""
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)

        for attempt in range(self.max_retries):
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "你是一位专业的黄金市场分析师，擅长从多维度分析黄金价格走势。"},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=2000,
                    temperature=0.3,
                )
                return response.choices[0].message.content or ''
            except Exception as e:
                logger.warning(
                    "OpenAI API 调用失败 (尝试 %d/%d): %s",
                    attempt + 1, self.max_retries, e
                )
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2 ** attempt)
                    time.sleep(delay)

        raise RuntimeError(f"OpenAI API 调用失败，已重试 {self.max_retries} 次")

    def analyze_news(
        self,
        news_items: List[NewsItem],
        price_data: Optional[PriceData] = None,
        historical_context: Optional[List[str]] = None
    ) -> AnalysisResult:
        """使用 OpenAI 分析新闻"""
        if not news_items:
            return AnalysisResult(
                direction='neutral', confidence=0,
                reasoning='无新闻数据', suggested_action='hold',
                impact_level='low', event_category='general',
                created_at=datetime.now()
            )

        prompt = self._build_analysis_prompt(news_items, price_data, historical_context)
        response = self._call_api(prompt)
        result = self._parse_analysis_response(response)
        result.news_ids = [n.id for n in news_items if n.id]
        logger.info(
            "AI 分析完成 (OpenAI): 方向=%s, 置信率=%.0f%%",
            result.direction, result.confidence
        )
        return result

    def generate_daily_summary(
        self,
        analyses: List[AnalysisResult],
        price_changes: List[PriceData],
        news_items: List[NewsItem]
    ) -> DailySummary:
        """使用 OpenAI 生成每日总结"""
        today = datetime.now().strftime('%Y-%m-%d')
        prompt = self._build_summary_prompt(analyses, price_changes, news_items)
        response = self._call_api(prompt)
        summary = self._parse_summary_response(response, today)
        summary.total_analyses = len(analyses)
        if price_changes:
            first_price = price_changes[0].price
            last_price = price_changes[-1].price
            summary.price_change = round(last_price - first_price, 2)
            if first_price > 0:
                summary.price_change_percent = round(
                    (last_price - first_price) / first_price * 100, 2
                )
        logger.info("每日总结生成完成 (OpenAI): %s", today)
        return summary


# ======================== AI 分析器调度类 ========================

class AIAnalyzer:
    """AI 分析器调度类，通过工厂方法创建对应的 Provider"""

    # Provider 注册表
    PROVIDER_MAP = {
        'qwen': QwenProvider,
        'openai': OpenAIProvider,
    }

    def __init__(self, provider_name: Optional[str] = None):
        """
        初始化 AI 分析器

        Args:
            provider_name: AI 提供商名称，为空时从配置读取
        """
        self.config = get_config()
        name = provider_name or self.config.ai_provider
        self.provider = self._create_provider(name)
        logger.info("AI 分析器初始化完成，当前提供商: %s", name)

    def _create_provider(self, name: str) -> AIProvider:
        """工厂方法：根据名称创建 Provider 实例"""
        provider_class = self.PROVIDER_MAP.get(name)
        if not provider_class:
            raise ValueError(
                f"不支持的 AI 提供商: {name}，可选: {list(self.PROVIDER_MAP.keys())}"
            )
        return provider_class()

    def switch_provider(self, name: str) -> None:
        """运行时切换 AI 提供商"""
        self.provider = self._create_provider(name)
        logger.info("AI 提供商已切换为: %s", name)

    def analyze(
        self,
        news_items: List[NewsItem],
        price_data: Optional[PriceData] = None,
        historical_context: Optional[List[str]] = None
    ) -> AnalysisResult:
        """执行新闻分析"""
        return self.provider.analyze_news(news_items, price_data, historical_context)

    def summarize(
        self,
        analyses: List[AnalysisResult],
        price_changes: List[PriceData],
        news_items: List[NewsItem]
    ) -> DailySummary:
        """生成每日总结"""
        return self.provider.generate_daily_summary(analyses, price_changes, news_items)
