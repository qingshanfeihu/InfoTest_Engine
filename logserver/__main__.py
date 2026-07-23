"""LogServer CLI 入口。

用法：
    python -m logserver --port 8081
    python -m logserver --host 0.0.0.0 --port 8081
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# 确保项目根在 sys.path 中，以便 import main.ist_core.*
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="LogServer 审计日志查询服务")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址")
    parser.add_argument("--port", type=int, default=8081, help="端口号")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    # 加载 .env
    try:
        from dotenv import load_dotenv
        env_path = _PROJECT_ROOT / "environment"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except Exception:
        pass

    # 确保数据库 schema 存在
    try:
        from main.ist_core.auth.db import ensure_schema
        ensure_schema()
    except Exception as exc:
        logging.getLogger("logserver").warning("ensure_schema 失败: %s", exc)

    import uvicorn
    from logserver.app import app

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
