"""企业微信智能机器人 — WebSocket 长连接模式，主入口。

启动方式::

    python -m wecom_bot_smart.main

无 HTTP 端口，不加 Nginx / frp——直接 WebSocket 连企微网关。
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading

from .config import smart_config
from .gateway import SmartBotGateway

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("wecom_bot_smart.main")

# 强制退出看门狗秒数：shutdown 后超时未退出则 os._exit
_FORCE_EXIT_TIMEOUT = 8


def main() -> int:
    try:
        smart_config.validate()
        logger.info("配置校验通过: bot_id=%s gateway=%.60s…",
                     smart_config.bot_id, smart_config.gateway_url)
    except ValueError as e:
        logger.error("配置错误: %s", e)
        logger.error("请在 environment 文件中填写 WECOM_SMART_BOT_ID / "
                      "WECOM_SMART_SECRET / WECOM_SMART_GATEWAY_URL")
        return 1

    bot = SmartBotGateway()
    _shutting_down = False

    def _shutdown(signum, frame):
        nonlocal _shutting_down
        if _shutting_down:
            # 第二次 Ctrl+C → 立即退出
            logger.info("再次收到信号 %s，强制退出", signum)
            os._exit(1)
        _shutting_down = True
        logger.info("收到信号 %s，正在关闭…", signum)
        bot.shutdown()
        # 看门狗：超时未退出则强杀
        def _force_exit():
            logger.warning("关闭超时（%ds），强制退出", _FORCE_EXIT_TIMEOUT)
            os._exit(1)
        t = threading.Timer(_FORCE_EXIT_TIMEOUT, _force_exit)
        t.daemon = True
        t.start()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("🚀 企微智能机器人启动（WebSocket 长连接模式）")
    bot.run_forever()
    logger.info("👋 已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
