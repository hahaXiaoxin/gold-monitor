---
name: gold-price-history-and-source-separation
overview: 重构金价数据模块：1) 金价不再实时请求展示，改为每5分钟入库，前端以图表形式展示不同时间维度的涨跌曲线；2) 区分不同数据源（新浪/腾讯），避免互相覆盖，前端显示数据来源和上次更新时间。
todos:
  - id: model-and-db
    content: 扩展 PriceData 模型增加 source 字段，修改 SQLiteDB 的 price_history 表结构（新增 source 列 + 索引）和 schema 迁移逻辑（v1->v2），适配 save_price / _row_to_price / 新增 get_price_history_v2(hours, source)
    status: completed
  - id: price-monitor
    content: 改造 PriceMonitor：新增 fetch_all_sources() 遍历所有 API 源并返回带 source 标记的 List[PriceData]；修复 get_current_price 中 24h 涨跌被缓存覆盖的问题；修改 Scheduler._job_check_price 改用多源采集保存
    status: completed
    dependencies:
      - model-and-db
  - id: api-extend
    content: /api/prices 接口扩展支持 hours 和 source 查询参数，返回带 source 的完整 history 数据和可用 sources 列表
    status: completed
    dependencies:
      - model-and-db
  - id: frontend-chart
    content: 前端实现金价走势图表：base.html 引入 Chart.js CDN，dashboard.html 新增图表区域（时间维度按钮组 + 数据源切换 + canvas），app.js 实现 Chart.js 折线图初始化和数据加载，style.css 新增图表相关样式
    status: completed
    dependencies:
      - api-extend
  - id: commit-and-verify
    content: 提交 git commit，使用 [subagent:code-explorer] 验证所有修改文件的接口一致性
    status: completed
    dependencies:
      - frontend-chart
---

## 用户需求

金价数据展示的改进，核心包含两点：

1. **金价数据存储与多维度图表**：金价不需要实时请求展示，而是每隔5分钟采集一次存入数据库（已有此机制），前端以图表曲线形式展示金价走势，支持按不同时间维度（1小时、6小时、24小时、7天、30天）切换查看涨跌曲线
2. **多数据源区分**：不同来源（新浪行情、腾讯行情）的金价数据应区分存储，避免互相覆盖，前端需支持按数据源筛选显示，同时展示上次更新时间

## 核心功能

- 金价数据增加 source 字段，区分不同采集来源
- 每次采集时所有可用数据源都保存各自的数据（而非只取第一个成功的）
- 仪表盘金价区域改为图表形式展示，使用折线图呈现金价走势曲线
- 支持时间维度切换（1h / 6h / 24h / 7d / 30d）
- 支持按数据源切换（全部 / 新浪 / 腾讯）
- 金价卡片区保留当前金价、24h涨跌、波动率数值摘要，新增"上次更新时间"和"数据来源"标识
- API 接口扩展支持 hours 和 source 查询参数

## 技术栈

- 后端: Python Flask + SQLite（现有）
- 前端: 原生 JS + Chart.js（新增轻量图表库，通过 CDN 引入）
- 图表库选择: Chart.js -- 轻量（~70KB gzip）、无依赖、原生支持折线图和时间轴，CDN 引入无需构建工具

## 实现方案

### 核心思路

将 PriceMonitor 从"取第一个成功源就返回"改为"遍历所有源，各自独立保存"。数据库 price_history 表新增 source 字段区分来源。前端引入 Chart.js 绘制金价走势折线图，支持按时间维度和数据源切换。

### 数据层改动

1. **PriceData 模型**：新增 `source: str = ''` 字段
2. **price_history 表**：ALTER TABLE 新增 `source TEXT DEFAULT ''` 列 + 索引，schema 版本升至 2
3. **PriceMonitor**：新增 `fetch_all_sources()` 方法，遍历所有 API 源，返回 `List[PriceData]`（各带 source 标记）；原 `get_current_price()` 保持不变（兼容调度器其他调用处）
4. **Scheduler**：`_job_check_price` 改用 `fetch_all_sources()`，循环保存每个源的数据
5. **SQLiteDB**：`save_price` 增加 source 字段写入；新增 `get_price_history_v2(hours, source)` 支持按来源和时间范围查询；`_row_to_price` 适配 source 字段

### API 层改动

`/api/prices` 接口扩展：

- 新增查询参数 `hours`（默认 24）和 `source`（默认空=全部）
- 响应增加 `sources` 列表（可用数据源名称）
- history 条目增加 source 和完整字段

### 前端改动

1. **base.html**：在 head 中引入 Chart.js CDN
2. **dashboard.html**：金价卡片区保留 3 张摘要卡片（增加来源和更新时间），下方新增图表区域（含时间维度按钮组 + 数据源切换按钮组 + canvas 画布）
3. **app.js**：新增 `initPriceChart()` / `loadPriceChart(hours, source)` / `updateChartData()` 函数；改造 `loadPrices()` 补充来源和更新时间显示
4. **style.css**：新增图表容器、维度按钮组样式

## 实现细节

- **数据库迁移**：在 `init_tables()` 中检测 schema_version，若为 1 则执行 `ALTER TABLE price_history ADD COLUMN source TEXT DEFAULT ''`，更新版本为 2。SQLite 的 ALTER TABLE ADD COLUMN 是安全操作，不影响已有数据
- **24h 涨跌计算修复**：解析器已经从 API 返回的昨收价正确计算了 change_24h，但 `get_current_price()` 中又用缓存覆盖。改为：仅当解析器返回的 change_24h 为 0 时才用缓存补算
- **Chart.js 时间轴**：使用 `type: 'line'`，x 轴为 `type: 'time'`（需引入 chartjs-adapter-date-fns 适配器），y 轴自动缩放。多数据源时用不同颜色的折线区分
- **性能**：30 天数据量约 8640 条/源（每5分钟一条），Chart.js 可轻松处理。前端切换维度时重新请求对应时间范围数据，避免一次性加载全量

## 目录结构

```
project-root/
├── models/
│   └── schemas.py              # [MODIFY] PriceData 新增 source 字段
├── core/
│   ├── price_monitor.py        # [MODIFY] 新增 fetch_all_sources() 方法，修复涨跌覆盖问题
│   └── scheduler.py            # [MODIFY] _job_check_price 改用 fetch_all_sources 多源保存
├── db/
│   └── sqlite_db.py            # [MODIFY] price_history 表新增 source 列，新增 get_price_history_v2，schema 迁移至 v2
├── web/
│   ├── app.py                  # [MODIFY] /api/prices 支持 hours/source 参数，返回 sources 列表
│   └── templates/
│       ├── base.html           # [MODIFY] head 引入 Chart.js + adapter CDN
│       └── dashboard.html      # [MODIFY] 金价区域改为摘要卡片 + 图表区域（维度切换+数据源切换+canvas）
├── static/
│   ├── css/style.css           # [MODIFY] 新增图表容器、维度按钮组、数据源切换样式
│   └── js/app.js               # [MODIFY] 新增 Chart.js 图表初始化/更新/维度切换/数据源切换逻辑
```