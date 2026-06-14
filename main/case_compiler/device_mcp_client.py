"""IST-Core 侧框架 MCP client 驱动（经 SSH 启动跳转机 stdio server）。

首发用直接 paramiko + stdio JSON-RPC 驱动（与 langchain-mcp-adapters stdio transport
等价的最小实现）；后续可平滑换成 MultiServerMCPClient 适配成 LangChain tool。

凭据：跳转机 SSH 口令从 env IST_JUMPHOST_PASS / JUMPHOST_PASS 取，不落盘不回显。
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from main.case_compiler.config import get_config

_cfg = get_config()
JUMPHOST = os.environ.get("IST_JUMPHOST_HOST", _cfg.jumphost.host)
JUMPHOST_USER = os.environ.get("IST_JUMPHOST_USER", _cfg.jumphost.user)
SERVER_CMD = _cfg.jumphost.server_cmd


def _password() -> str:
    for k in ("IST_JUMPHOST_PASS", "JUMPHOST_PASS"):
        v = os.environ.get(k)
        if v:
            return v
    raise RuntimeError("跳转机口令未提供：设置 IST_JUMPHOST_PASS 环境变量")


def _connect():
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(JUMPHOST, port=22, username=JUMPHOST_USER, password=_password(),
              timeout=15, look_for_keys=False, allow_agent=False)
    return c


class FrameworkMCPClient:
    """经 SSH 驱动跳转机 stdio MCP server。每次调用开一个 server 会话（无状态命令）。"""

    def __init__(self):
        self._c = _connect()

    def close(self):
        try:
            self._c.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def call(self, calls: list[tuple[str, dict]]) -> dict[str, Any]:
        """一个 server 会话内顺序调用多个 tool，按 tool 名返回结果（后者覆盖前者）。"""
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        ]
        nid = 2
        idmap = {}
        for name, args in calls:
            msgs.append({"jsonrpc": "2.0", "id": nid, "method": "tools/call",
                         "params": {"name": name, "arguments": args}})
            idmap[nid] = name
            nid += 1
        si, so, se = self._c.exec_command(SERVER_CMD, timeout=120)
        si.write("\n".join(json.dumps(m) for m in msgs) + "\n")
        si.flush()
        si.channel.shutdown_write()
        # so.read() 默认无超时阻塞——server 端某 tool 卡住(pytest hang/deliver慢)就无限 hang。
        # 给 channel 设读超时,分块读到 EOF;超时抛异常让上层处理,不无限 hang。
        # 单次会话上限按 server 最慢 tool(run_cases 上机)留足:默认 900s,可被调用方收紧。
        read_timeout_s = int(getattr(self, "_call_read_timeout_s", 900))
        chan = so.channel
        chan.settimeout(read_timeout_s)
        import socket as _sock
        chunks = []
        try:
            while True:
                b = so.read(65536)
                if not b:
                    break
                chunks.append(b)
        except (_sock.timeout, TimeoutError):
            raise RuntimeError(
                f"MCP server 响应读取超时(>{read_timeout_s}s)——server端tool可能hang"
                f"(如pytest上机卡住/deliver慢)。已中止本次调用,不无限阻塞。")
        out = b"".join(chunks).decode("utf-8", "replace")
        res: dict[str, Any] = {}
        for line in out.splitlines():
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("id") in idmap:
                try:
                    res[idmap[o["id"]]] = json.loads(o["result"]["content"][0]["text"])
                except Exception:
                    res[idmap[o["id"]]] = o.get("result") or o.get("error")
        return res

    # 便捷封装 ───────────────────────────────────────────────

    def list_capabilities(self) -> dict:
        return self.call([("list_capabilities", {})]).get("list_capabilities", {})

    def probe_show(self, command: str, build: str = "") -> dict:
        """只读设备探针:经跳转机在被测 APV 上跑单条 show/get 命令,取真实回显。

        本测试床 APV 只能经跳转机访问(本地/agent 直连不通),故探单命令走这里,
        不走直连 qa_ssh。硬白名单首 token show/get(server 侧强制)。
        build 决定 conf 设备段(infosec_hgk 等),空则 server 端遍历设备段兜底。
        """
        return self.call([("probe_show", {"command": command, "build": build})]).get("probe_show", {})

    def deliver(self, module: str, autoid: str, xlsx_path: str) -> dict:
        b64 = base64.b64encode(Path(xlsx_path).read_bytes()).decode()
        return self.call([("write_case", {"module": module, "autoid": autoid, "xlsx_b64": b64})]).get("write_case", {})

    def run(self, module: str, autoid: str, build: str) -> Optional[str]:
        r = self.call([("run_cases_submit", {"module": module, "autoid": autoid, "build": build})])
        return (r.get("run_cases_submit") or {}).get("task_id")

    def status(self, task_id: str, build: str, case_ids: list[str]) -> dict:
        return self.call([("run_cases_status",
                           {"task_id": task_id, "build": build, "case_ids": case_ids})]).get("run_cases_status", {})

    def run_and_wait(self, module: str, autoid: str, build: str, case_ids: list[str],
                     poll_s: int = 10, max_s: int = 600) -> dict:
        """提交一个 staging 用例并轮询到 done，返回最终 status。"""
        tid = self.run(module, autoid, build)
        if not tid:
            return {"error": "submit failed (lock held?)"}
        deadline = time.time() + max_s
        last = {}
        while time.time() < deadline:
            time.sleep(poll_s)
            last = self.status(tid, build, case_ids)
            st = (last.get("status") or {}).get("state")
            if st in ("done", "error"):
                break
        last["task_id"] = tid
        return last

    def fetch_case_detail(self, autoid: str, max_chars: int = 6000) -> str:
        """拉取框架**逐步骤执行明细 + check_point 真实裁决**。

        ⚠️ 路径关键(实证):check_point 的 `#### Success/Fail Num: successed/fail to find`
        写在**每个 case 的专属子日志** `test_xlsx/case.xlsx/<autoid>/<autoid>.txt`,**不是**
        框架调度总日志 `test_xlsx/test_xlsx.txt`(后者只到 `begin case` 就没了,据它会误判
        "零 check_point/空真")。故优先取 case 专属日志,缺则回退总日志。
        """
        # 优先:case 专属日志(含 Success/Fail Num 真实裁决)
        case_log = (f"/home/test/apv_src/report/*/*/ist_staging_*/{autoid}"
                    f"/test_xlsx/case.xlsx/{autoid}/{autoid}.txt")
        total_log = (f"/home/test/apv_src/report/*/*/ist_staging_*/{autoid}"
                     f"/test_xlsx/test_xlsx.txt")
        try:
            for glob in (case_log, total_log):
                _i, o, _e = self._c.exec_command(f"ls -t {glob} 2>/dev/null | head -1", timeout=30)
                path = o.read().decode("utf-8", "replace").strip()
                if not path:
                    continue
                _i, o, _e = self._c.exec_command(f"cat '{path}'", timeout=30)
                text = o.read().decode("utf-8", "replace")
                if text.strip():
                    return text[-max_chars:]
            return ""
        except Exception:
            return ""

