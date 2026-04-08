"""
网关注册模块

负责将 Gold Monitor 服务注册到 hellocola-gateway 网关，
并通过定时心跳保持服务活跃，避免被网关清理。

网关接口规范（hellocola-gateway）:
- POST   /api/services                  注册/更新服务（幂等）
- PUT    /api/services/:domain/heartbeat 发送心跳
- DELETE /api/services/:domain           注销服务
- GET    /api/health                     网关健康检查
"""

import logging
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# 默认心跳间隔（秒），应小于网关默认 TTL（30s）
DEFAULT_HEARTBEAT_INTERVAL = 10
# 默认 TTL（秒），告知网关此服务的存活期限
DEFAULT_TTL = 30


class GatewayRegistry:
    """
    hellocola-gateway 网关注册器

    启动后自动向网关注册服务，并定时发送心跳。
    关闭时注销服务，确保网关及时清理。
    """

    def __init__(
        self,
        gateway_url: str,
        domain: str,
        target: str,
        name: str = 'Gold Monitor',
        description: str = '黄金涨幅盯盘软件 - AI 驱动的黄金市场分析与盯盘系统',
        icon: str = '',
        ttl: int = DEFAULT_TTL,
        heartbeat_interval: int = DEFAULT_HEARTBEAT_INTERVAL,
    ):
        """
        初始化网关注册器

        :param gateway_url: 网关地址，如 http://localhost:3000
        :param domain: 注册到网关的域名标识，如 gold-monitor.local
        :param target: 本服务的实际访问地址，如 http://localhost:5051
        :param name: 服务显示名称
        :param description: 服务描述
        :param icon: 服务图标 URL
        :param ttl: 存活时间（秒），网关在此时间内未收到心跳会清除服务
        :param heartbeat_interval: 心跳发送间隔（秒），应小于 ttl
        """
        self.gateway_url = gateway_url.rstrip('/')
        self.domain = domain
        self.target = target
        self.name = name
        self.description = description
        self.icon = icon
        self.ttl = ttl
        self.heartbeat_interval = heartbeat_interval

        # 心跳线程控制
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._registered = False

        # 请求超时（秒）
        self._request_timeout = 10

    def start(self) -> bool:
        """
        启动网关注册：注册服务 + 启动心跳线程

        :return: 注册是否成功
        """
        if self._registered:
            logger.warning("网关注册器已在运行中，跳过重复启动")
            return True

        # 先检查网关是否可达
        if not self._check_gateway_health():
            logger.error("网关 %s 不可达，跳过服务注册", self.gateway_url)
            return False

        # 注册服务
        success = self._register_service()
        if not success:
            logger.error("向网关注册服务失败")
            return False

        # 启动心跳线程
        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name='gateway-heartbeat',
            daemon=True
        )
        self._heartbeat_thread.start()
        self._registered = True
        logger.info(
            "网关注册成功 [域名: %s, 目标: %s, TTL: %ds, 心跳间隔: %ds]",
            self.domain, self.target, self.ttl, self.heartbeat_interval
        )
        return True

    def stop(self) -> None:
        """停止心跳并注销服务"""
        if not self._registered:
            return

        # 停止心跳线程
        self._stop_event.set()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=5)

        # 注销服务
        self._unregister_service()
        self._registered = False
        logger.info("已从网关注销服务 [域名: %s]", self.domain)

    def _check_gateway_health(self) -> bool:
        """检查网关是否健康可达"""
        url = f"{self.gateway_url}/api/health"
        try:
            resp = requests.get(url, timeout=self._request_timeout)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success'):
                    logger.info(
                        "网关健康检查通过 [活跃服务: %s, 运行时长: %ss]",
                        data.get('data', {}).get('activeServices', '?'),
                        data.get('data', {}).get('uptime', '?')
                    )
                    return True
            logger.warning("网关健康检查响应异常: %s", resp.text)
            return False
        except requests.RequestException as e:
            logger.warning("网关健康检查失败: %s", e)
            return False

    def _register_service(self) -> bool:
        """向网关注册服务"""
        url = f"{self.gateway_url}/api/services"
        payload = {
            'domain': self.domain,
            'target': self.target,
            'name': self.name,
            'description': self.description,
            'ttl': self.ttl,
        }
        if self.icon:
            payload['icon'] = self.icon

        try:
            resp = requests.post(
                url,
                json=payload,
                timeout=self._request_timeout
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get('success'):
                    logger.info("服务注册成功: %s", data.get('message', ''))
                    return True
            logger.error("服务注册失败 [HTTP %d]: %s", resp.status_code, resp.text)
            return False
        except requests.RequestException as e:
            logger.error("服务注册请求异常: %s", e)
            return False

    def _unregister_service(self) -> None:
        """从网关注销服务"""
        url = f"{self.gateway_url}/api/services/{self.domain}"
        try:
            resp = requests.delete(url, timeout=self._request_timeout)
            if resp.status_code == 200:
                logger.info("服务注销成功")
            else:
                logger.warning("服务注销响应异常 [HTTP %d]: %s", resp.status_code, resp.text)
        except requests.RequestException as e:
            logger.warning("服务注销请求异常（忽略）: %s", e)

    def _send_heartbeat(self) -> bool:
        """发送一次心跳"""
        url = f"{self.gateway_url}/api/services/{self.domain}/heartbeat"
        try:
            resp = requests.put(url, timeout=self._request_timeout)
            if resp.status_code == 200:
                return True
            elif resp.status_code == 404:
                # 服务已被网关清除，需要重新注册
                logger.warning("网关返回 404，服务可能已过期，尝试重新注册...")
                return self._register_service()
            else:
                logger.warning("心跳响应异常 [HTTP %d]: %s", resp.status_code, resp.text)
                return False
        except requests.RequestException as e:
            logger.warning("心跳发送失败: %s", e)
            return False

    def _heartbeat_loop(self) -> None:
        """心跳循环线程，定期向网关发送心跳"""
        consecutive_failures = 0
        max_failures = 5  # 连续失败超过此数则尝试重新注册

        logger.info("心跳线程已启动 [间隔: %ds]", self.heartbeat_interval)

        while not self._stop_event.is_set():
            # 等待指定间隔，期间可被 stop_event 中断
            if self._stop_event.wait(timeout=self.heartbeat_interval):
                break

            success = self._send_heartbeat()
            if success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                logger.warning(
                    "心跳失败 [连续失败: %d/%d]",
                    consecutive_failures, max_failures
                )

                if consecutive_failures >= max_failures:
                    logger.error("心跳连续失败 %d 次，尝试重新注册服务...", max_failures)
                    if self._register_service():
                        consecutive_failures = 0
                        logger.info("重新注册成功，心跳恢复")
                    else:
                        logger.error("重新注册也失败了，将继续重试...")
                        # 指数退避等待，避免频繁请求
                        backoff = min(self.heartbeat_interval * 2, 60)
                        self._stop_event.wait(timeout=backoff)

        logger.info("心跳线程已停止")

    @property
    def is_registered(self) -> bool:
        """当前是否已注册到网关"""
        return self._registered
