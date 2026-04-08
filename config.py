"""
配置管理模块

加载 config.yaml 和 .env 文件，提供全局配置单例。
包含默认值定义和配置校验逻辑。
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent


class Config:
    """全局配置管理单例"""

    _instance: Optional['Config'] = None
    _config: Dict[str, Any] = {}

    def __new__(cls) -> 'Config':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self) -> None:
        """加载配置文件和环境变量"""
        # 加载 .env 文件
        env_path = BASE_DIR / '.env'
        if env_path.exists():
            load_dotenv(env_path)
            logger.info("已加载 .env 环境变量文件")
        else:
            logger.warning("未找到 .env 文件，将仅使用系统环境变量")

        # 加载 config.yaml
        config_path = BASE_DIR / 'config.yaml'
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f) or {}
            logger.info("已加载 config.yaml 配置文件")
        else:
            logger.warning("未找到 config.yaml，将使用默认配置")
            self._config = {}

        # 校验关键配置
        self._validate()

    def _validate(self) -> None:
        """校验关键配置项"""
        provider = self.get('ai.provider', 'qwen')
        if provider == 'qwen' and not self.get_env('DASHSCOPE_API_KEY'):
            logger.warning("当前 AI 提供商为 qwen，但未配置 DASHSCOPE_API_KEY")
        elif provider == 'openai' and not self.get_env('OPENAI_API_KEY'):
            logger.warning("当前 AI 提供商为 openai，但未配置 OPENAI_API_KEY")

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值，支持点号分隔的嵌套键。
        例如: config.get('ai.provider') 获取 ai -> provider
        """
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value

    @staticmethod
    def get_env(key: str, default: str = '') -> str:
        """获取环境变量值"""
        return os.getenv(key, default)

    @property
    def ai_provider(self) -> str:
        """当前 AI 提供商"""
        return self.get('ai.provider', 'qwen')

    @property
    def qwen_model(self) -> str:
        """通义千问模型名称"""
        return self.get('ai.qwen_model', 'qwen-turbo')

    @property
    def openai_model(self) -> str:
        """OpenAI 模型名称"""
        return self.get('ai.openai_model', 'gpt-4o-mini')

    @property
    def dashscope_api_key(self) -> str:
        """DashScope API Key"""
        return self.get_env('DASHSCOPE_API_KEY')

    @property
    def openai_api_key(self) -> str:
        """OpenAI API Key"""
        return self.get_env('OPENAI_API_KEY')

    @property
    def openai_base_url(self) -> str:
        """OpenAI Base URL"""
        return self.get_env('OPENAI_BASE_URL', 'https://api.openai.com/v1')

    @property
    def confidence_threshold(self) -> int:
        """触发通知的置信率阈值"""
        return self.get('analysis.confidence_threshold', 70)

    @property
    def collector_interval(self) -> int:
        """新闻采集间隔（分钟）"""
        return self.get('collector.interval_minutes', 30)

    @property
    def price_check_interval(self) -> int:
        """金价检查间隔（分钟）"""
        return self.get('price_monitor.interval_minutes', 5)

    @property
    def db_path(self) -> str:
        """SQLite 数据库路径"""
        path = self.get('database.path', './data/gold_monitor.db')
        return str(BASE_DIR / path)

    @property
    def chroma_persist_dir(self) -> str:
        """ChromaDB 持久化目录"""
        path = self.get('knowledge_base.persist_directory', './chroma_data')
        return str(BASE_DIR / path)

    @property
    def web_host(self) -> str:
        """Web 服务主机"""
        return self.get('web.host', '0.0.0.0')

    @property
    def web_port(self) -> int:
        """Web 服务端口"""
        return self.get('web.port', 5051)

    @property
    def web_debug(self) -> bool:
        """Web 调试模式"""
        return self.get('web.debug', False)

    # ---- hellocola-gateway 网关配置 ----

    @property
    def gateway_enabled(self) -> bool:
        """是否启用网关注册"""
        return self.get('gateway.enabled', False)

    @property
    def gateway_url(self) -> str:
        """网关地址（环境变量优先）"""
        return self.get_env('GATEWAY_URL') or self.get('gateway.url', 'http://localhost:3000')

    @property
    def gateway_domain(self) -> str:
        """注册到网关的域名标识"""
        return self.get('gateway.domain', 'gold-monitor.local')

    @property
    def gateway_target(self) -> str:
        """本服务的外部可访问地址（环境变量优先）"""
        env_target = self.get_env('GATEWAY_TARGET')
        if env_target:
            return env_target
        # 默认根据 web 配置生成
        return f"http://{self.web_host}:{self.web_port}"

    @property
    def gateway_name(self) -> str:
        """网关中显示的服务名称"""
        return self.get('gateway.name', 'Gold Monitor')

    @property
    def gateway_description(self) -> str:
        """网关中显示的服务描述"""
        return self.get('gateway.description', '黄金涨幅盯盘软件')

    @property
    def gateway_icon(self) -> str:
        """网关中显示的服务图标"""
        return self.get('gateway.icon', '')

    @property
    def gateway_ttl(self) -> int:
        """网关 TTL（秒）"""
        return self.get('gateway.ttl', 30)

    @property
    def gateway_heartbeat_interval(self) -> int:
        """网关心跳间隔（秒）"""
        return self.get('gateway.heartbeat_interval', 10)

    @property
    def log_level(self) -> str:
        """日志级别"""
        return self.get('logging.level', 'INFO')

    @property
    def log_dir(self) -> str:
        """日志目录"""
        path = self.get('logging.log_dir', './logs')
        return str(BASE_DIR / path)

    def reload(self) -> None:
        """重新加载配置"""
        self._load()
        logger.info("配置已重新加载")


def get_config() -> Config:
    """获取全局配置实例"""
    return Config()


def setup_logging() -> None:
    """初始化日志系统"""
    config = get_config()
    log_dir = Path(config.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, config.log_level.upper(), logging.INFO)

    # 根日志配置
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 清除已有处理器
    root_logger.handlers.clear()

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_format = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    root_logger.addHandler(console_handler)

    # 文件处理器
    file_handler = logging.FileHandler(
        log_dir / 'gold_monitor.log',
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    file_format = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_format)
    root_logger.addHandler(file_handler)

    logger.info("日志系统初始化完成，级别: %s", config.log_level)
