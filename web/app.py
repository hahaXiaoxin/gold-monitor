"""
Flask Web 应用模块

提供 Web 仪表盘路由和 REST API 接口。
路由：仪表盘(/)、历史记录(/history)
API：/api/status, /api/analysis, /api/prices, /api/events, /api/feedback
"""

import logging
from datetime import datetime
from typing import Optional

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

from config import Config
from db.chroma_db import ChromaDB
from db.sqlite_db import SQLiteDB
from models.schemas import UserFeedback

logger = logging.getLogger(__name__)


def create_app(
    db: SQLiteDB,
    chroma: ChromaDB,
    config: Config
) -> Flask:
    """
    创建 Flask 应用实例

    Args:
        db: SQLite 数据库实例
        chroma: ChromaDB 实例
        config: 配置实例

    Returns:
        Flask 应用实例
    """
    app = Flask(
        __name__,
        template_folder='templates',
        static_folder='../static',
        static_url_path='/static'
    )

    # 启用 CORS（便于后续接入 hellocola-gateway）
    CORS(app)

    # 保存依赖到 app 上下文
    app.config['db'] = db
    app.config['chroma'] = chroma
    app.config['app_config'] = config
    app.config['start_time'] = datetime.now()

    # ==================== 页面路由 ====================

    @app.route('/')
    def dashboard():
        """仪表盘首页"""
        return render_template('dashboard.html')

    @app.route('/history')
    def history():
        """历史记录页"""
        return render_template('history.html')

    # ==================== REST API ====================

    @app.route('/api/status')
    def api_status():
        """系统状态接口"""
        try:
            from core.knowledge_base import KnowledgeBase
            kb = KnowledgeBase(chroma)
            kb_stats = kb.get_stats()
        except Exception:
            kb_stats = {'total_experiences': 0, 'status': '未知'}

        uptime = (datetime.now() - app.config['start_time']).total_seconds()
        return jsonify({
            'success': True,
            'data': {
                'status': 'running',
                'uptime_seconds': int(uptime),
                'ai_provider': config.ai_provider,
                'knowledge_base': kb_stats,
                'last_updated': datetime.now().isoformat(),
            }
        })

    @app.route('/api/prices')
    def api_prices():
        """金价数据接口"""
        try:
            latest = db.get_latest_price()
            history = db.get_price_history(hours=24)

            return jsonify({
                'success': True,
                'data': {
                    'current': {
                        'price': latest.price if latest else 0,
                        'change_24h': latest.change_24h if latest else 0,
                        'change_percent_24h': latest.change_percent_24h if latest else 0,
                        'volatility': latest.volatility if latest else 0,
                        'high_24h': latest.high_24h if latest else 0,
                        'low_24h': latest.low_24h if latest else 0,
                        'timestamp': latest.timestamp.isoformat() if latest and latest.timestamp else None,
                    } if latest else None,
                    'history': [
                        {
                            'price': p.price,
                            'timestamp': p.timestamp.isoformat() if p.timestamp else None,
                        }
                        for p in history
                    ]
                }
            })
        except Exception as e:
            logger.error("获取金价数据失败: %s", e)
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/analysis')
    def api_analysis():
        """分析结果接口"""
        try:
            hours = request.args.get('hours', 24, type=int)
            limit = request.args.get('limit', 20, type=int)
            analyses = db.get_recent_analyses(hours=hours, limit=limit)

            # 获取每条分析的反馈状态
            results = []
            for a in analyses:
                feedback = db.get_feedback_for_analysis(a.id) if a.id else None
                results.append({
                    'id': a.id,
                    'direction': a.direction,
                    'confidence': a.confidence,
                    'reasoning': a.reasoning,
                    'suggested_action': a.suggested_action,
                    'key_factors': a.key_factors,
                    'impact_level': a.impact_level,
                    'event_category': a.event_category,
                    'news_ids': a.news_ids,
                    'created_at': a.created_at.isoformat() if a.created_at else None,
                    'feedback': {
                        'is_accurate': feedback.is_accurate,
                        'comment': feedback.comment,
                    } if feedback else None,
                })

            # 最新一条
            latest = results[0] if results else None

            return jsonify({
                'success': True,
                'data': {
                    'latest': latest,
                    'list': results,
                    'total': len(results),
                }
            })
        except Exception as e:
            logger.error("获取分析数据失败: %s", e)
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/events')
    def api_events():
        """关键事件接口"""
        try:
            hours = request.args.get('hours', 48, type=int)
            limit = request.args.get('limit', 20, type=int)
            events = db.get_recent_events(hours=hours, limit=limit)

            return jsonify({
                'success': True,
                'data': {
                    'events': [
                        {
                            'id': e.id,
                            'title': e.title,
                            'summary': e.summary,
                            'url': e.url,
                            'source': e.source,
                            'direction': e.direction,
                            'impact_level': e.impact_level,
                            'event_category': e.event_category,
                            'published_at': e.published_at.isoformat() if e.published_at else None,
                            'confidence': e.confidence,
                        }
                        for e in events
                    ],
                    'total': len(events),
                }
            })
        except Exception as e:
            logger.error("获取关键事件失败: %s", e)
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/feedback', methods=['POST'])
    def api_feedback():
        """用户反馈接口"""
        try:
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'error': '请求体为空'}), 400

            analysis_id = data.get('analysis_id')
            is_accurate = data.get('is_accurate')
            comment = data.get('comment', '')

            if not analysis_id or is_accurate is None:
                return jsonify({'success': False, 'error': '缺少必要参数'}), 400

            feedback = UserFeedback(
                analysis_id=analysis_id,
                is_accurate=bool(is_accurate),
                comment=comment,
                created_at=datetime.now()
            )

            # 保存反馈到数据库
            feedback_id = db.save_feedback(feedback)

            # 更新知识库
            try:
                from core.knowledge_base import KnowledgeBase
                kb = KnowledgeBase(chroma)
                kb.update_with_feedback(analysis_id, feedback)
            except Exception as e:
                logger.warning("更新知识库反馈失败（非致命）: %s", e)

            return jsonify({
                'success': True,
                'data': {'feedback_id': feedback_id}
            })
        except Exception as e:
            logger.error("提交反馈失败: %s", e)
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/summaries')
    def api_summaries():
        """每日总结列表接口"""
        try:
            days = request.args.get('days', 30, type=int)
            summaries = db.get_daily_summaries(days=days)

            return jsonify({
                'success': True,
                'data': {
                    'summaries': [
                        {
                            'id': s.id,
                            'date': s.date,
                            'summary': s.summary,
                            'key_events': [
                                {
                                    'title': e.title,
                                    'summary': e.summary,
                                    'direction': e.direction,
                                    'impact_level': e.impact_level,
                                    'event_category': e.event_category,
                                }
                                for e in s.key_events[:3]
                            ],
                            'price_change': s.price_change,
                            'price_change_percent': s.price_change_percent,
                            'total_analyses': s.total_analyses,
                            'accuracy_rate': s.accuracy_rate,
                            'dimensions': s.dimensions,
                        }
                        for s in summaries
                    ],
                    'total': len(summaries),
                }
            })
        except Exception as e:
            logger.error("获取每日总结失败: %s", e)
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/stats')
    def api_stats():
        """准确率统计接口"""
        try:
            days = request.args.get('days', 7, type=int)
            stats = db.get_accuracy_stats(days=days)

            return jsonify({
                'success': True,
                'data': stats
            })
        except Exception as e:
            logger.error("获取统计数据失败: %s", e)
            return jsonify({'success': False, 'error': str(e)}), 500

    logger.info("Flask 应用创建完成，已注册所有路由和 API")
    return app
