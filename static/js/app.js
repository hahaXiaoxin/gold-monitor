/**
 * Gold Monitor - 前端交互逻辑
 *
 * 功能：轮询刷新数据、用户反馈提交、事件卡片渲染、日期筛选、表格排序
 */

// ============================
// 全局状态
// ============================
const APP_STATE = {
    currentAnalysisId: null,
    refreshInterval: 30000, // 30秒刷新
    currentDays: 1,         // 当前筛选天数（历史页面）
    sortField: 'time',
    sortAsc: false,
    // 图表状态
    chartHours: 24,
    chartSource: '',
    priceChart: null,
};

// 方向/操作的中文映射
const DIRECTION_MAP = {
    bullish: '🟢 利好',
    bearish: '🔴 利空',
    neutral: '⚪ 中性',
};

const ACTION_MAP = {
    buy: '💰 买入',
    sell: '📉 卖出',
    hold: '⏸️ 持有',
};

const IMPACT_MAP = {
    high: '🔥 高影响',
    medium: '⚡ 中影响',
    low: '💤 低影响',
};

const CATEGORY_MAP = {
    geopolitical: '🌍 地缘政治',
    economic_data: '📊 经济数据',
    central_bank: '🏦 央行政策',
    usd_trend: '💵 美元走势',
    market_sentiment: '📈 市场情绪',
    technical: '📐 技术面',
    general: '📰 综合',
};

const SOURCE_MAP = {
    sina_hq: '新浪行情',
    tencent_hq: '腾讯行情',
};

const SOURCE_COLORS = {
    sina_hq: { line: '#D4A843', bg: 'rgba(212, 168, 67, 0.1)' },
    tencent_hq: { line: '#58A6FF', bg: 'rgba(88, 166, 255, 0.1)' },
};

// ============================
// 页面初始化
// ============================
document.addEventListener('DOMContentLoaded', () => {
    // 注入 SVG 渐变定义
    injectSVGDefs();
    // 检查系统状态
    checkStatus();
    // 根据页面类型加载数据
    if (document.getElementById('currentPrice')) {
        // 仪表盘页面
        loadPrices();
        loadEvents();
        loadAnalysis();
        loadNotifications();
        initPriceChart();
        // 定时刷新
        setInterval(() => {
            loadPrices();
            loadPriceChart();
            loadEvents();
            loadAnalysis();
            loadNotifications();
            checkStatus();
        }, APP_STATE.refreshInterval);
    }
});

// ============================
// SVG 渐变注入
// ============================
function injectSVGDefs() {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.style.position = 'absolute';
    svg.style.width = '0';
    svg.style.height = '0';
    svg.innerHTML = `
        <defs>
            <linearGradient id="goldGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" style="stop-color:#D4A843"/>
                <stop offset="50%" style="stop-color:#F5C842"/>
                <stop offset="100%" style="stop-color:#B8860B"/>
            </linearGradient>
        </defs>
    `;
    document.body.prepend(svg);
}

// ============================
// 系统状态
// ============================
async function checkStatus() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        const dot = document.getElementById('statusDot');
        const text = document.getElementById('statusText');
        const time = document.getElementById('updateTime');

        if (data.success && data.data.status === 'running') {
            dot.className = 'status-dot online';
            text.textContent = '运行中';
        } else {
            dot.className = 'status-dot';
            text.textContent = '异常';
        }
        time.textContent = formatTime(new Date());
    } catch (e) {
        const dot = document.getElementById('statusDot');
        const text = document.getElementById('statusText');
        if (dot) dot.className = 'status-dot';
        if (text) text.textContent = '离线';
    }
}

// ============================
// 金价数据
// ============================
async function loadPrices() {
    try {
        const resp = await fetch('/api/prices?hours=24');
        const data = await resp.json();
        if (!data.success || !data.data.current) return;

        const current = data.data.current;
        const priceEl = document.getElementById('currentPrice');
        const timestampEl = document.getElementById('priceTimestamp');
        const sourceEl = document.getElementById('priceSource');
        const changeEl = document.getElementById('priceChange');
        const percentEl = document.getElementById('priceChangePercent');
        const volatilityEl = document.getElementById('volatility');

        if (priceEl) priceEl.textContent = `$${current.price.toFixed(2)}`;
        if (timestampEl) timestampEl.textContent = current.timestamp ? formatTime(new Date(current.timestamp)) : '--';
        if (sourceEl && current.source) {
            sourceEl.textContent = SOURCE_MAP[current.source] || current.source;
        }

        if (changeEl) {
            const change = current.change_24h;
            changeEl.textContent = `${change >= 0 ? '+' : ''}$${change.toFixed(2)}`;
            changeEl.className = `change-value ${change >= 0 ? 'positive' : 'negative'}`;
        }

        if (percentEl) {
            const pct = current.change_percent_24h;
            percentEl.textContent = `${pct >= 0 ? '▲' : '▼'} ${Math.abs(pct).toFixed(2)}%`;
            percentEl.className = `change-percent ${pct >= 0 ? 'positive' : 'negative'}`;
        }

        if (volatilityEl) {
            volatilityEl.textContent = `${current.volatility.toFixed(4)}%`;
        }

        // 更新数据源按钮组
        updateSourceButtons(data.data.sources || []);
    } catch (e) {
        console.error('加载金价失败:', e);
    }
}

function updateSourceButtons(sources) {
    const group = document.getElementById('sourceGroup');
    if (!group || sources.length === 0) return;

    // 检查是否已经存在所有按钮
    const existing = group.querySelectorAll('button[data-source]');
    const existingSources = new Set(Array.from(existing).map(b => b.dataset.source));
    const allPresent = sources.every(s => existingSources.has(s));
    if (allPresent && existingSources.size === sources.length + 1) return; // +1 for "全部"

    // 重建按钮组
    group.innerHTML = `<button class="chart-btn ${APP_STATE.chartSource === '' ? 'active' : ''}" data-source="" onclick="switchSource('', this)">全部</button>`;
    sources.forEach(s => {
        const btn = document.createElement('button');
        btn.className = `chart-btn ${APP_STATE.chartSource === s ? 'active' : ''}`;
        btn.dataset.source = s;
        btn.textContent = SOURCE_MAP[s] || s;
        btn.onclick = () => switchSource(s, btn);
        group.appendChild(btn);
    });
}

// ============================
// 金价走势图表
// ============================
function initPriceChart() {
    const canvas = document.getElementById('priceChart');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    APP_STATE.priceChart = new Chart(ctx, {
        type: 'line',
        data: { datasets: [] },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        usePointStyle: true,
                        pointStyle: 'circle',
                        padding: 16,
                        font: { family: "'Inter', sans-serif", size: 12 },
                        color: '#4A4A6A',
                    },
                },
                tooltip: {
                    backgroundColor: 'rgba(26, 26, 46, 0.9)',
                    titleFont: { family: "'Inter', sans-serif" },
                    bodyFont: { family: "'Inter', sans-serif" },
                    padding: 12,
                    cornerRadius: 8,
                    callbacks: {
                        label: function(ctx) {
                            const src = SOURCE_MAP[ctx.dataset.sourceKey] || ctx.dataset.label;
                            return `${src}: $${ctx.parsed.y.toFixed(2)}`;
                        },
                    },
                },
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        tooltipFormat: 'yyyy-MM-dd HH:mm',
                        displayFormats: {
                            minute: 'HH:mm',
                            hour: 'HH:mm',
                            day: 'MM-dd',
                        },
                    },
                    grid: { color: 'rgba(0,0,0,0.04)' },
                    ticks: {
                        maxTicksLimit: 10,
                        font: { size: 11 },
                        color: '#8B8BA8',
                    },
                },
                y: {
                    grid: { color: 'rgba(0,0,0,0.04)' },
                    ticks: {
                        font: { size: 11 },
                        color: '#8B8BA8',
                        callback: v => `$${v.toFixed(0)}`,
                    },
                },
            },
        },
    });

    loadPriceChart();
}

async function loadPriceChart() {
    if (!APP_STATE.priceChart) return;

    const hours = APP_STATE.chartHours;
    const source = APP_STATE.chartSource;

    try {
        const url = `/api/prices?hours=${hours}${source ? `&source=${source}` : ''}`;
        const resp = await fetch(url);
        const data = await resp.json();
        if (!data.success) return;

        const history = data.data.history || [];
        if (history.length === 0) {
            APP_STATE.priceChart.data.datasets = [];
            APP_STATE.priceChart.update();
            return;
        }

        // 按 source 分组
        const grouped = {};
        history.forEach(p => {
            const src = p.source || 'unknown';
            if (!grouped[src]) grouped[src] = [];
            grouped[src].push({ x: new Date(p.timestamp), y: p.price });
        });

        const datasets = Object.entries(grouped).map(([src, points]) => {
            const colors = SOURCE_COLORS[src] || { line: '#D4A843', bg: 'rgba(212, 168, 67, 0.1)' };
            return {
                label: SOURCE_MAP[src] || src,
                sourceKey: src,
                data: points,
                borderColor: colors.line,
                backgroundColor: colors.bg,
                borderWidth: 2,
                pointRadius: points.length > 100 ? 0 : 2,
                pointHoverRadius: 4,
                fill: true,
                tension: 0.3,
            };
        });

        APP_STATE.priceChart.data.datasets = datasets;
        APP_STATE.priceChart.update();
    } catch (e) {
        console.error('加载图表数据失败:', e);
    }
}

function switchTimeRange(hours, btn) {
    APP_STATE.chartHours = hours;
    document.querySelectorAll('#timeRangeGroup .chart-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    loadPriceChart();
}

function switchSource(source, btn) {
    APP_STATE.chartSource = source;
    document.querySelectorAll('#sourceGroup .chart-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    loadPriceChart();
}

// ============================
// 关键事件
// ============================
async function loadEvents() {
    try {
        const resp = await fetch('/api/events?hours=48&limit=20');
        const data = await resp.json();
        const container = document.getElementById('eventsContainer');
        const countEl = document.getElementById('eventsCount');

        if (!data.success || !data.data.events.length) {
            container.innerHTML = '<div class="events-placeholder">暂无关键事件数据</div>';
            if (countEl) countEl.textContent = '0';
            return;
        }

        const events = data.data.events;
        if (countEl) countEl.textContent = events.length;

        container.innerHTML = events.map(e => `
            <div class="event-card ${e.direction}">
                <div class="event-title">
                    <a href="${escapeHtml(e.url)}" target="_blank" rel="noopener">${escapeHtml(e.title)}</a>
                </div>
                <div class="event-tags">
                    <span class="event-tag impact-${e.impact_level}">${IMPACT_MAP[e.impact_level] || e.impact_level}</span>
                    <span class="event-tag category">${CATEGORY_MAP[e.event_category] || e.event_category}</span>
                </div>
                <div class="event-summary">${escapeHtml(e.summary)}</div>
                <div class="event-meta">
                    <span>${e.source}</span>
                    <span>${e.published_at ? formatTime(new Date(e.published_at)) : '--'}</span>
                </div>
            </div>
        `).join('');
    } catch (e) {
        console.error('加载事件失败:', e);
    }
}

// ============================
// AI 分析结果
// ============================
async function loadAnalysis() {
    try {
        const resp = await fetch('/api/analysis?hours=24&limit=1');
        const data = await resp.json();

        if (!data.success || !data.data.latest) return;

        const a = data.data.latest;
        APP_STATE.currentAnalysisId = a.id;

        // 方向徽章
        const badge = document.getElementById('analysisBadge');
        if (badge) {
            badge.textContent = DIRECTION_MAP[a.direction] || a.direction;
            badge.className = `badge direction-badge ${a.direction}`;
        }

        // 操作建议
        const actionBadge = document.getElementById('actionBadge');
        if (actionBadge) {
            actionBadge.textContent = ACTION_MAP[a.suggested_action] || a.suggested_action;
            actionBadge.className = `badge action-badge ${a.suggested_action}`;
        }

        // 影响等级
        const impactBadge = document.getElementById('impactBadge');
        if (impactBadge) {
            impactBadge.textContent = IMPACT_MAP[a.impact_level] || a.impact_level;
            impactBadge.className = `badge impact-badge ${a.impact_level}`;
        }

        // 事件类别
        const categoryBadge = document.getElementById('categoryBadge');
        if (categoryBadge) {
            categoryBadge.textContent = CATEGORY_MAP[a.event_category] || a.event_category;
            categoryBadge.className = 'badge category-badge';
        }

        // 时间
        const timeEl = document.getElementById('analysisTime');
        if (timeEl) timeEl.textContent = a.created_at ? formatTime(new Date(a.created_at)) : '--';

        // 置信率环
        updateConfidenceRing(a.confidence);

        // 关键因素
        const factorsEl = document.getElementById('keyFactors');
        if (factorsEl && a.key_factors) {
            factorsEl.innerHTML = a.key_factors.map(f =>
                `<span class="factor-tag">${escapeHtml(f)}</span>`
            ).join('');
        }

        // 分析理由
        const reasoningEl = document.getElementById('reasoningText');
        if (reasoningEl) reasoningEl.textContent = a.reasoning || '--';

        // 反馈区域
        const feedbackArea = document.getElementById('feedbackArea');
        if (feedbackArea) {
            feedbackArea.style.display = 'flex';
            if (a.feedback) {
                showFeedbackSubmitted(a.feedback.is_accurate);
            }
        }
    } catch (e) {
        console.error('加载分析失败:', e);
    }
}

function updateConfidenceRing(confidence) {
    const ring = document.getElementById('confidenceRing');
    const valueEl = document.getElementById('confidenceValue');

    if (valueEl) valueEl.textContent = `${Math.round(confidence)}%`;

    if (ring) {
        const circumference = 2 * Math.PI * 52; // r=52
        const offset = circumference - (confidence / 100) * circumference;
        ring.style.strokeDasharray = circumference;
        ring.style.strokeDashoffset = offset;
        ring.setAttribute('stroke', 'url(#goldGradient)');
    }
}

function toggleReasoning() {
    const content = document.getElementById('reasoningContent');
    const arrow = document.getElementById('toggleArrow');
    if (content.style.display === 'none') {
        content.style.display = 'block';
        arrow.classList.add('open');
    } else {
        content.style.display = 'none';
        arrow.classList.remove('open');
    }
}

// ============================
// 用户反馈
// ============================
async function submitFeedback(isAccurate) {
    if (!APP_STATE.currentAnalysisId) return;

    try {
        const resp = await fetch('/api/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                analysis_id: APP_STATE.currentAnalysisId,
                is_accurate: isAccurate,
            }),
        });
        const data = await resp.json();
        if (data.success) {
            showFeedbackSubmitted(isAccurate);
        }
    } catch (e) {
        console.error('提交反馈失败:', e);
        const status = document.getElementById('feedbackStatus');
        if (status) status.textContent = '提交失败，请重试';
    }
}

function showFeedbackSubmitted(isAccurate) {
    const area = document.getElementById('feedbackArea');
    if (!area) return;

    const btns = area.querySelectorAll('.btn-feedback');
    btns.forEach(btn => {
        btn.disabled = true;
        btn.style.opacity = '0.5';
    });

    if (isAccurate) {
        area.querySelector('.btn-accurate').classList.add('active');
        area.querySelector('.btn-accurate').style.opacity = '1';
    } else {
        area.querySelector('.btn-inaccurate').classList.add('active');
        area.querySelector('.btn-inaccurate').style.opacity = '1';
    }

    const status = document.getElementById('feedbackStatus');
    if (status) status.textContent = '✓ 反馈已提交，感谢！';
}

// ============================
// 近期通知列表
// ============================
async function loadNotifications() {
    try {
        const resp = await fetch('/api/analysis?hours=24&limit=10');
        const data = await resp.json();
        const tbody = document.getElementById('notificationsBody');
        if (!tbody) return;

        if (!data.success || !data.data.list.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-text">暂无分析记录</td></tr>';
            return;
        }

        tbody.innerHTML = data.data.list.map(a => `
            <tr>
                <td>${a.created_at ? formatTime(new Date(a.created_at)) : '--'}</td>
                <td><span class="tag tag-${a.direction}">${DIRECTION_MAP[a.direction] || a.direction}</span></td>
                <td>
                    <span class="confidence-bar">
                        <span class="confidence-bar-fill ${a.confidence >= 70 ? 'high' : (a.confidence >= 40 ? 'medium' : 'low')}"
                              style="width:${a.confidence}%"></span>
                    </span>
                    ${Math.round(a.confidence)}%
                </td>
                <td><span class="tag category">${CATEGORY_MAP[a.event_category] || a.event_category}</span></td>
                <td><span class="tag tag-${a.suggested_action}">${ACTION_MAP[a.suggested_action] || a.suggested_action}</span></td>
                <td>${a.feedback ? (a.feedback.is_accurate ? '<span style="color:var(--color-success)">✓ 准确</span>' : '<span style="color:var(--color-danger)">✗ 不准确</span>') : '<span style="color:var(--text-muted)">待反馈</span>'}</td>
            </tr>
        `).join('');
    } catch (e) {
        console.error('加载通知失败:', e);
    }
}

// ============================
// 历史页面功能
// ============================
async function loadHistoryData() {
    try {
        const resp = await fetch(`/api/analysis?hours=${APP_STATE.currentDays * 24}&limit=100`);
        const data = await resp.json();
        const tbody = document.getElementById('historyBody');
        if (!tbody) return;

        if (!data.success || !data.data.list.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-text">暂无分析记录</td></tr>';
            return;
        }

        tbody.innerHTML = data.data.list.map(a => `
            <tr>
                <td>${a.created_at ? formatTime(new Date(a.created_at)) : '--'}</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml((a.key_factors || []).join(', '))}</td>
                <td><span class="tag tag-${a.direction}">${DIRECTION_MAP[a.direction] || a.direction}</span></td>
                <td>
                    <span class="confidence-bar">
                        <span class="confidence-bar-fill ${a.confidence >= 70 ? 'high' : (a.confidence >= 40 ? 'medium' : 'low')}"
                              style="width:${a.confidence}%"></span>
                    </span>
                    ${Math.round(a.confidence)}%
                </td>
                <td><span class="tag tag-${a.suggested_action}">${ACTION_MAP[a.suggested_action] || a.suggested_action}</span></td>
                <td>${a.feedback ? (a.feedback.is_accurate ? '<span style="color:var(--color-success)">✓ 准确</span>' : '<span style="color:var(--color-danger)">✗ 不准确</span>') : '<span style="color:var(--text-muted)">--</span>'}</td>
            </tr>
        `).join('');
    } catch (e) {
        console.error('加载历史数据失败:', e);
    }
}

async function loadStats() {
    try {
        // 总体统计
        const resp30 = await fetch('/api/stats?days=30');
        const data30 = await resp30.json();
        if (data30.success) {
            const s = data30.data;
            const overallEl = document.getElementById('overallAccuracy');
            const overallCount = document.getElementById('overallCount');
            if (overallEl) overallEl.textContent = s.total > 0 ? `${s.accuracy_rate}%` : '--';
            if (overallCount) overallCount.textContent = `${s.accurate}/${s.total} 条反馈`;

            // 按方向
            const bullishEl = document.getElementById('bullishAccuracy');
            const bearishEl = document.getElementById('bearishAccuracy');
            if (bullishEl && s.by_direction.bullish) {
                bullishEl.textContent = `${s.by_direction.bullish.accuracy_rate}%`;
            }
            if (bearishEl && s.by_direction.bearish) {
                bearishEl.textContent = `${s.by_direction.bearish.accuracy_rate}%`;
            }
        }

        // 近7天统计
        const resp7 = await fetch('/api/stats?days=7');
        const data7 = await resp7.json();
        if (data7.success) {
            const s7 = data7.data;
            const weekEl = document.getElementById('weekAccuracy');
            const weekCount = document.getElementById('weekCount');
            if (weekEl) weekEl.textContent = s7.total > 0 ? `${s7.accuracy_rate}%` : '--';
            if (weekCount) weekCount.textContent = `${s7.accurate}/${s7.total} 条反馈`;
        }
    } catch (e) {
        console.error('加载统计失败:', e);
    }
}

async function loadSummaries() {
    try {
        const resp = await fetch(`/api/summaries?days=${APP_STATE.currentDays}`);
        const data = await resp.json();
        const container = document.getElementById('summariesContainer');
        if (!container) return;

        if (!data.success || !data.data.summaries.length) {
            container.innerHTML = '<div class="empty-text">暂无每日总结数据</div>';
            return;
        }

        container.innerHTML = data.data.summaries.map((s, idx) => `
            <div class="summary-card">
                <div class="summary-header">
                    <div class="summary-date">📅 ${s.date}</div>
                    <div class="summary-stats">
                        <span class="summary-stat" style="color:${s.price_change_percent >= 0 ? 'var(--color-success)' : 'var(--color-danger)'}">
                            ${s.price_change_percent >= 0 ? '▲' : '▼'} ${Math.abs(s.price_change_percent).toFixed(2)}%
                        </span>
                        <span class="summary-stat">📊 ${s.total_analyses} 次分析</span>
                        ${s.accuracy_rate > 0 ? `<span class="summary-stat" style="color:var(--gold-dark)">🎯 ${s.accuracy_rate.toFixed(1)}%</span>` : ''}
                    </div>
                </div>
                <div class="summary-events">
                    ${(s.key_events || []).slice(0, 3).map(e => `
                        <div class="summary-event-item">
                            <span class="event-dot ${e.direction}"></span>
                            <span>${escapeHtml(e.title)}</span>
                        </div>
                    `).join('')}
                </div>
                <button class="summary-toggle" onclick="toggleSummaryDetail(${idx})">
                    查看详情 ▼
                </button>
                <div class="summary-detail" id="summaryDetail${idx}">
                    <p>${escapeHtml(s.summary)}</p>
                    ${s.dimensions ? Object.entries(s.dimensions).map(([k, v]) => `
                        <p><strong>${CATEGORY_MAP[k] || k}:</strong> ${escapeHtml(v)}</p>
                    `).join('') : ''}
                </div>
            </div>
        `).join('');
    } catch (e) {
        console.error('加载总结失败:', e);
    }
}

function toggleSummaryDetail(idx) {
    const detail = document.getElementById(`summaryDetail${idx}`);
    if (detail) {
        detail.classList.toggle('open');
    }
}

function filterByDays(days, btn) {
    APP_STATE.currentDays = days;

    // 更新按钮状态
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');

    // 刷新数据
    loadHistoryData();
    loadSummaries();
}

function applyDateFilter() {
    // 自定义日期范围筛选（简化实现）
    const from = document.getElementById('dateFrom')?.value;
    const to = document.getElementById('dateTo')?.value;
    if (from && to) {
        const diff = Math.ceil((new Date(to) - new Date(from)) / (1000 * 60 * 60 * 24)) + 1;
        APP_STATE.currentDays = Math.max(1, diff);
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        loadHistoryData();
        loadSummaries();
    }
}

function sortTable(field) {
    if (APP_STATE.sortField === field) {
        APP_STATE.sortAsc = !APP_STATE.sortAsc;
    } else {
        APP_STATE.sortField = field;
        APP_STATE.sortAsc = true;
    }
    loadHistoryData(); // 简化：重新加载并在前端排序
}

// ============================
// 工具函数
// ============================
function formatTime(date) {
    if (!date || isNaN(date.getTime())) return '--';
    const pad = n => n.toString().padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
