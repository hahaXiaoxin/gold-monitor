"""
核心数据结构定义

使用 dataclass 定义系统中所有核心数据模型。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class NewsItem:
    """新闻数据项"""
    title: str                          # 新闻标题
    content: str                        # 新闻内容/摘要
    source: str                         # 来源（如 sina_finance, jin10）
    url: str                            # 原文链接
    published_at: datetime              # 发布时间
    keywords: List[str] = field(default_factory=list)  # 关键词
    id: Optional[str] = None            # 唯一标识（存储后生成）


@dataclass
class AnalysisResult:
    """AI 分析结果"""
    direction: str                      # "bullish"(利好) / "bearish"(利空) / "neutral"(中性)
    confidence: float                   # 置信率 0-100
    reasoning: str                      # 分析理由
    suggested_action: str               # "buy" / "sell" / "hold"
    key_factors: List[str] = field(default_factory=list)  # 关键影响因素
    impact_level: str = 'medium'        # "high" / "medium" / "low" 事件影响等级
    event_category: str = 'general'     # 事件类别
    news_ids: List[str] = field(default_factory=list)     # 关联的新闻 ID
    created_at: Optional[datetime] = None  # 分析时间
    id: Optional[str] = None            # 唯一标识


@dataclass
class PriceData:
    """黄金价格数据"""
    price: float                        # 当前价格（美元/盎司）
    currency: str = 'USD'               # 货币单位
    change_24h: float = 0.0             # 24小时涨跌额
    change_percent_24h: float = 0.0     # 24小时涨跌幅（%）
    high_24h: float = 0.0              # 24小时最高价
    low_24h: float = 0.0               # 24小时最低价
    volatility: float = 0.0            # 波动率
    timestamp: Optional[datetime] = None  # 数据时间


@dataclass
class KeyEvent:
    """关键事件（用于仪表盘事件卡片流）"""
    title: str                          # 事件标题
    summary: str                        # 一句话摘要
    url: str                            # 原文链接
    source: str                         # 来源
    direction: str                      # "bullish" / "bearish" / "neutral"
    impact_level: str                   # "high" / "medium" / "low"
    event_category: str                 # 事件类别
    published_at: Optional[datetime] = None  # 发布时间
    confidence: float = 0.0             # 置信率
    id: Optional[str] = None            # 唯一标识


@dataclass
class DailySummary:
    """每日总结报告"""
    date: str                           # 日期 YYYY-MM-DD
    summary: str                        # 综合总结文本
    key_events: List[KeyEvent] = field(default_factory=list)  # 当日关键事件
    dimensions: dict = field(default_factory=dict)  # 各维度分析详情
    price_change: float = 0.0           # 当日金价变动
    price_change_percent: float = 0.0   # 当日金价变动百分比
    total_analyses: int = 0             # 当日分析总数
    accurate_count: int = 0             # 准确预测数
    accuracy_rate: float = 0.0          # 准确率
    created_at: Optional[datetime] = None  # 创建时间
    id: Optional[str] = None            # 唯一标识


@dataclass
class UserFeedback:
    """用户反馈"""
    analysis_id: str                    # 关联的分析结果 ID
    is_accurate: bool                   # 是否准确
    comment: str = ''                   # 用户评论（可选）
    created_at: Optional[datetime] = None  # 反馈时间
    id: Optional[str] = None            # 唯一标识
