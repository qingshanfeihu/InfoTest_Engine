# -*- coding: utf-8 -*-
"""人工修床登记(C1 维护日志通道;理论锚=(38) 写者全集的「运维写」)。

纪律:对测试床做过任何手工配置(拆 vlan/bond、恢复接口 IP、清残留……)后,
**修完必登记**——否则下批引擎会把维护写误判为「非己方残留」(弹问询)或
「案残留」(误告警/误清理)。run12 实证:五次人工修床未入账,批后收敛全部误报。

用法:
    python scripts/maintenance/log_bed_maintenance.py \\
        --host 10.4.127.93 --who jiangyongze \\
        --why "run12 拆床:恢复 port2 基线" \\
        --cmd "no vlan vlan100" --cmd "no bond interface bond1" \\
        --cmd "ip address port2 172.16.34.70 255.255.255.0"

host 缺省读 IST_JUMPHOST_HOST(environment 文件);who 缺省取系统用户名。
落账:runtime/bed_ledger/<host>.jsonl 追加 ev=maintenance 事实(append-only)。
消费:bed_check 残留判定与 closing 批后收敛按命令面身份 token 解释 diff。
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description="登记一次人工床维护(修完必登记)")
    ap.add_argument("--host", default="", help="跳板机/床标识(缺省 IST_JUMPHOST_HOST)")
    ap.add_argument("--who", default="", help="操作人(缺省系统用户名)")
    ap.add_argument("--why", required=True, help="为何维护(一句话)")
    ap.add_argument("--cmd", action="append", required=True, dest="cmds",
                    help="执行过的设备命令(可多次)")
    args = ap.parse_args()

    try:
        from main.langchain_env import langchain_load_dotenv_if_present
        langchain_load_dotenv_if_present()
    except Exception:  # noqa: BLE001
        pass
    host = args.host or os.environ.get("IST_JUMPHOST_HOST", "") or "10.4.127.103"
    who = args.who or getpass.getuser()

    from main.ist_core.compile_engine_v8.bed import bed_record, maintenance_tokens
    ident = f"maint:{time.strftime('%Y%m%d-%H%M%S')}"
    bed_record(ROOT, host, "maintenance", "manual", ident,
               payload={"who": who, "why": args.why, "commands": list(args.cmds)})
    toks = maintenance_tokens(ROOT, host)
    print(f"已登记 {ident} → runtime/bed_ledger/{host}.jsonl")
    print(f"操作人 {who} · 原因:{args.why}")
    print(f"命令 {len(args.cmds)} 条;当前维护命令面身份 token 共 {len(toks)} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
