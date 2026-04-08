"""
Gold Monitor - 黄金涨幅盯盘软件

应用入口文件。负责初始化所有模块，启动调度器和 Web 服务。
支持命令行参数切换运行模式：完整模式 / 仅 Web / 仅调度。
"""

import argparse
import logging
import signal
import sys
from pathlib import Path

from config import get_config, setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='Gold Monitor - 黄金涨幅盯盘软件'
    )
    parser.add_argument(
        '--mode',
        choices=['full', 'web', 'scheduler'],
        default='full',
        help='运行模式: full=完整模式, web=仅Web服务, scheduler=仅调度器 (默认: full)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=None,
        help='Web 服务端口 (覆盖配置文件)'
    )
    return parser.parse_args()


def main() -> None:
    """主入口函数"""
    # 解析命令行参数
    args = parse_args()

    # 初始化日志
    setup_logging()
    logger.info("=" * 50)
    logger.info("Gold Monitor 启动中...")
    logger.info("运行模式: %s", args.mode)

    # 加载配置
    config = get_config()

    # 确保数据目录存在
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(config.chroma_persist_dir).mkdir(parents=True, exist_ok=True)
    Path(config.log_dir).mkdir(parents=True, exist_ok=True)

    # 初始化数据库
    from db.sqlite_db import SQLiteDB
    db = SQLiteDB(config.db_path)
    db.init_tables()
    logger.info("SQLite 数据库初始化完成")

    # 初始化 ChromaDB
    from db.chroma_db import ChromaDB
    chroma = ChromaDB(config.chroma_persist_dir)
    logger.info("ChromaDB 向量数据库初始化完成")

    # 注册优雅关闭
    scheduler_instance = None

    def graceful_shutdown(signum, frame):
        logger.info("收到关闭信号，正在优雅关闭...")
        if scheduler_instance:
            scheduler_instance.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    # 根据模式启动服务
    if args.mode in ('full', 'scheduler'):
        from core.scheduler import GoldScheduler
        scheduler_instance = GoldScheduler(db=db, chroma=chroma, config=config)
        scheduler_instance.start()
        logger.info("调度器已启动")

    if args.mode in ('full', 'web'):
        from web.app import create_app
        app = create_app(db=db, chroma=chroma, config=config)
        port = args.port or config.web_port
        logger.info("Web 服务启动于 http://%s:%d", config.web_host, port)
        app.run(
            host=config.web_host,
            port=port,
            debug=config.web_debug,
            use_reloader=False  # 避免调度器被重复启动
        )
    elif args.mode == 'scheduler':
        # 仅调度模式，保持进程运行
        logger.info("调度器运行中，按 Ctrl+C 退出")
        signal.pause()


if __name__ == '__main__':
    main()
