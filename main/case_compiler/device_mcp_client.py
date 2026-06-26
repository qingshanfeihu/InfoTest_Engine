"""IST-Core 侧框架 MCP client 驱动（经 SSH 启动跳转机 stdio server）。

首发用直接 paramiko + stdio JSON-RPC 驱动（与 langchain-mcp-adapters stdio transport
等价的最小实现）；后续可平滑换成 MultiServerMCPClient 适配成 LangChain tool。

凭据：跳转机 SSH 口令从 env IST_JUMPHOST_PASS / JUMPHOST_PASS 取，不落盘不回显。
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from main.case_compiler.config import get_config

_cfg = get_config()
JUMPHOST = os.environ.get("IST_JUMPHOST_HOST", _cfg.jumphost.host)
JUMPHOST_USER = os.environ.get("IST_JUMPHOST_USER", _cfg.jumphost.user)
SERVER_CMD = _cfg.jumphost.server_cmd


def _password(env: Any = None) -> str:
    keys: list[str] = []
    if env is not None and getattr(env, "pass_env", ""):
        keys.append(env.pass_env)
    keys += ["IST_JUMPHOST_PASS", "JUMPHOST_PASS"]
    for k in keys:
        v = os.environ.get(k)
        if v:
            return v
    raise RuntimeError("跳转机口令未提供：设置 IST_JUMPHOST_PASS 环境变量")


def _connect(env: Any = None):
    """连跳转机。``env``（config.Environment）给定则用其 host/port/user；否则用模块级现役单环境。"""
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    host = env.jumphost if env is not None else JUMPHOST
    user = env.ssh_user if env is not None else JUMPHOST_USER
    port = int(env.ssh_port) if env is not None else 22
    c.connect(host, port=port, username=user, password=_password(env),
              timeout=15, look_for_keys=False, allow_agent=False)
    return c


def framework_ready(env: Any, timeout: int = 8) -> bool:
    """只读探活：env 跳板机 SSH 可达 **且** 框架 stdio ``server.py`` 存在 **且** 被测设备可达。

    环境池 health-check 用——Path A 克隆部署到新机前，新机没有这个 server.py，探活返回
    False、池自动跳过它；ops 部署后自动加入可用池。任何异常一律 False（保守）。

    **device-aware（治"跳板机活但设备 down 被误判 ready"）**：跳板机 + server.py 通过后，再经
    跳板机查被测设备 SSH 口(:22)可达——设备 down（如 79 床 ping 不通）则 False、池剔除它，避免
    verify 被路由到死设备上全 fail。``IST_HEALTH_CHECK_DEVICE=0`` 关掉设备探活（退回只验跳板机+
    server.py 的旧行为）。设备段解析不出 IP / 设备探活本身异常 → 保守**放行**（不因探活逻辑波动
    误杀环境，维持"宁可多放不可错杀"——错杀会让池整体回退单环境）。
    """
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(env.jumphost, port=int(env.ssh_port), username=env.ssh_user,
                  password=_password(env), timeout=timeout, banner_timeout=timeout,
                  auth_timeout=timeout, look_for_keys=False, allow_agent=False)
    except Exception:  # noqa: BLE001
        return False
    try:
        _i, o, _e = c.exec_command(f"test -f {env.server_path} && echo OK", timeout=timeout)
        if o.read().decode("utf-8", "replace").strip() != "OK":
            return False
        if os.environ.get("IST_HEALTH_CHECK_DEVICE", "1") == "0":
            return True
        return _device_reachable_via(c, env, timeout=timeout)
    except Exception:  # noqa: BLE001
        return False
    finally:
        try:
            c.close()
        except Exception:  # noqa: BLE001
            pass


def _device_reachable_via(c: Any, env: Any, timeout: int = 8) -> bool:
    """经已连的跳板机 SSH 通道，查被测设备 SSH 口(:22)是否可达。

    用部署 server 的 ``tools._parse_device_conn`` 解析设备 IP（单一事实源），再从跳板机侧
    ``/dev/tcp`` 探设备 :22。**保守放行**：解析不出 IP / 探活异常 → True（不误杀环境）；仅当
    明确探到设备不可达才 False。
    """
    try:
        srv_dir = os.path.dirname(env.server_path) or "~/mcp_server"
        script = ("import tools,sys; c=tools._parse_device_conn(sys.argv[1] if len(sys.argv)>1 else '');"
                  " print(c[0] if c else '')")
        ip_cmd = "cd %s && python3 -c %s %s" % (_shquote(srv_dir), _shquote(script), _shquote(""))
        _i, o, _e = c.exec_command(ip_cmd, timeout=timeout)
        ip = ""
        for line in o.read().decode("utf-8", "replace").splitlines():
            line = line.strip()
            if re.match(r"^\d+\.\d+\.\d+\.\d+$", line):
                ip = line
        if not ip:
            return True   # 解析不出设备段 → 保守放行
        chk = "timeout 3 bash -c 'echo > /dev/tcp/%s/22' >/dev/null 2>&1 && echo OPEN || echo CLOSED" % ip
        _i2, o2, _e2 = c.exec_command(chk, timeout=timeout)
        return "OPEN" in o2.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return True   # 探活逻辑异常 → 保守放行，不误杀


# 设备/task 日志原样回灌 agent 上下文前过一道**凭据脱敏**：mask 掉口令/密钥/token 的值，
# 守红线「禁止在日志中打印 Token/口令」。**故意不脱敏 IP**——dig 真实输出里解析出的 IP 是
# agent 填 <RUNTIME> 断言的必需信息，脱了就废了核心功能；内网 IP 与设备数据同信任边界。
_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|api[\s_-]?key|apikey|access[\s_-]?token|auth[\s_-]?token|credential|community)\b"
    r"(\s*[:=]\s*|\s+)"
    r"(\"[^\"\n]*\"|'[^'\n]*'|\S+)"
)


def _redact(text: str | None) -> str:
    """对设备/task 日志做凭据脱敏（值替成 ****）；保留 IP 等诊断必需信息。"""
    if not text:
        return text or ""
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}****", text)


# ── 新版 FastMCP HTTP 探针（apv_ssh_execute）：自带 status + 完整回显 + 对齐 ^ ──
# 老 stdio probe_show 剥命令回显行 → 无效命令只剩孤立 ^，LLM 无从识别哪个 token 错（churn 根因）。
# 新版 FastMCP 的 apv_ssh_execute 不剥回显、回 status:error/success + 对齐 ^，故探针切到它。
FASTMCP_PORT = int(os.environ.get("IST_FASTMCP_PORT", "8000") or 8000)
_DEVICE_IP_CACHE: dict[tuple, str] = {}


def _shquote(s: str) -> str:
    import shlex
    return shlex.quote(s)


def resolve_device_ip(build: str = "", env: Any = None) -> str | None:
    """SSH 跳转机读 conf 解析被测设备 IP（build 段 ssh_ips 首个）。结果按 (host,build) 缓存。

    复用部署 server 的 ``tools._parse_device_conn``（单一事实源），不在 client 端重造 conf 解析。
    解析失败返回 None（上层据此回退老 probe_show）。
    """
    host = (env.jumphost if env is not None else JUMPHOST)
    key = (host, build)
    if key in _DEVICE_IP_CACHE:
        return _DEVICE_IP_CACHE[key]
    c = None
    try:
        c = _connect(env)
        script = ("import tools,sys; c=tools._parse_device_conn(sys.argv[1] if len(sys.argv)>1 else '');"
                  " print(c[0] if c else '')")
        cmd = "cd ~/mcp_server && python3 -c %s %s" % (_shquote(script), _shquote(build))
        _, so, _ = c.exec_command(cmd, timeout=30)
        out = so.read().decode("utf-8", "replace")
        ip = ""
        for line in out.splitlines():
            line = line.strip()
            if re.match(r"^\d+\.\d+\.\d+\.\d+$", line):
                ip = line
        if ip:
            _DEVICE_IP_CACHE[key] = ip
            return ip
        return None
    except Exception:
        return None
    finally:
        if c is not None:
            try:
                c.close()
            except Exception:
                pass


def fastmcp_call(tool: str, arguments: dict, env: Any = None,
                 timeout: int = 30) -> str | None:
    """通用：经跳转机新版 FastMCP(:8000) 调一个工具，返回其结果文本(content[0].text)。

    streamable-http JSON-RPC over HTTP，解析 SSE ``data:`` 行取 result/error。FastMCP 不可达 /
    响应异常 / 无 result → 返回 None。**迁移基座**：dev_probe 走它(apv_ssh_execute)，后续把
    init_device/deliver/run 等编排工具迁到 FastMCP 也复用它(不再各写一遍 HTTP+SSE)。
    """
    host = (env.jumphost if env is not None else JUMPHOST)
    url = "http://%s:%d/mcp" % (host, FASTMCP_PORT)
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": tool, "arguments": arguments}}
    import urllib.request
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except Exception:
        return None
    obj = None
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        if isinstance(o, dict) and ("result" in o or "error" in o):
            obj = o
            break
    if obj is None:
        return None
    try:
        return obj["result"]["content"][0]["text"]
    except Exception:
        return None


def probe_via_fastmcp(command: str, build: str = "", env: Any = None,
                      timeout: int = 30) -> dict | None:
    """经跳转机新版 FastMCP(:8000) 的 ``apv_ssh_execute`` 在被测设备上跑只读 show，取回显。

    返回 ``{"text": <服务端格式化文本，含 status + 回显 + 对齐 ^>, "device_ip": ip}``；
    设备 IP 解析不出 / FastMCP 不可达 / 响应异常 → 返回 None（上层回退老 stdio probe_show）。
    """
    device_ip = resolve_device_ip(build, env)
    if not device_ip:
        return None
    text = fastmcp_call("apv_ssh_execute", {"host": device_ip, "command": command},
                        env=env, timeout=timeout)
    if text is None:
        return None
    return {"text": text, "device_ip": device_ip}


class FrameworkMCPClient:
    """经 SSH 驱动跳转机 stdio MCP server。每次调用开一个 server 会话（无状态命令）。"""

    def __init__(self, env: Any = None):
        self._env = env
        self._c = _connect(env)
        self._server_cmd = env.server_cmd if env is not None else SERVER_CMD

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
        si, so, se = self._c.exec_command(self._server_cmd, timeout=120)
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
        不走直连 dev_ssh。硬白名单首 token show/get(server 侧强制)。
        build 决定 conf 设备段(infosec_hgk 等),空则 server 端遍历设备段兜底。
        """
        return self.call([("probe_show", {"command": command, "build": build})]).get("probe_show", {})

    def init_device(self, device_count: int = 0, device_index: int = -1) -> dict:
        """编译前固化设备初始化：经部署 server 串口 ``clear config all`` + 配接口 IP。

        让 draft 的 dev_probe 探到**干净已知态**，不再撞别人残留配置。整机级清，编译入口
        调一次即可（非 per-case）。返回 ``{"initialized","failed","total","details"}`` 或 ``{"error"}``。
        device_count=0 自动从 conf ssh_ips 推断；device_index 指定单台（优先于 count）。
        server 侧加单跑锁后，与正在 verify 的 run_cases 互斥（撞锁返回 ``error: another run in progress``）。
        """
        return (self.call([("init_device",
                            {"device_count": device_count, "device_index": device_index})])
                .get("init_device") or {})

    def deliver(self, module: str, autoid: str, xlsx_path: str) -> dict:
        b64 = base64.b64encode(Path(xlsx_path).read_bytes()).decode()
        return self.call([("write_case", {"module": module, "autoid": autoid, "xlsx_b64": b64})]).get("write_case", {})

    def run(self, module: str, autoid: str, build: str) -> dict:
        """提交上机。返回 server 原始结果：成功含 task_id，撞锁含 busy 结构。"""
        return (self.call([("run_cases_submit",
                            {"module": module, "autoid": autoid, "build": build})])
                .get("run_cases_submit") or {})

    def status(self, task_id: str, build: str, case_ids: list[str]) -> dict:
        return self.call([("run_cases_status",
                           {"task_id": task_id, "build": build, "case_ids": case_ids})]).get("run_cases_status", {})

    def run_and_wait(self, module: str, autoid: str, build: str, case_ids: list[str],
                     poll_s: int = 10, max_s: int = 600) -> dict:
        """提交一个 staging 用例并轮询到 done，返回最终 status。

        撞锁（设备正在验证上一个用例）时**不静默放弃**，把 server 的结构化 busy
        信号原样上抛（含 running_autoid / elapsed_s / message），由上层 agent 决定
        等待、跳过还是上报——而不是把"环境忙"误当成"提交失败"。
        """
        sub = self.run(module, autoid, build)
        if sub.get("busy") or sub.get("error") == "device_busy":
            return {"error": "device_busy", "busy": True,
                    "running_autoid": sub.get("running_autoid", ""),
                    "elapsed_s": sub.get("elapsed_s"),
                    "message": sub.get("message", "环境忙：正在验证上一个用例，请稍后重试。")}
        tid = sub.get("task_id")
        if not tid:
            return {"error": "submit failed: %s" % (sub.get("error") or "unknown")}
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
                    return _redact(text[-max_chars:])  # 与 fetch_batch_details 一致:回灌前脱敏
            return ""
        except Exception:
            return ""

    def fetch_batch_details(self, submit_autoid: str, max_chars_each: int = 3500) -> dict[str, str]:
        """整份 xlsx 一次上机后,从 **submit_autoid 的 staging** 读回**所有内层 case** 的逐
        check_point 明细。返回 {inner_autoid: detail_text}。

        关键(实证):框架把交付的整份 xlsx 当套件整跑,所有内层 case 的日志都落在**提交时那个
        autoid** 的 staging 下:``ist_staging_*/{submit_autoid}/test_xlsx/case.xlsx/<inner>/<inner>.txt``
        ——不是各自 autoid 的独立 staging。故一次提交后用本方法一把捞齐,**不必逐 autoid 重复整跑**
        (旧 dev_run_batch O(N²) 的根因)。一条 SSH 命令带分隔符 cat 全部,减少往返。
        """
        base_glob = (f"/home/test/apv_src/report/*/*/ist_staging_*/{submit_autoid}"
                     f"/test_xlsx/case.xlsx")
        cmd = (f"base=$(ls -dt {base_glob} 2>/dev/null | head -1); "
               f"[ -z \"$base\" ] && exit 0; "
               f"for d in \"$base\"/*/; do a=$(basename \"$d\"); "
               f"if [ -f \"$d/$a.txt\" ]; then echo \"<<<CASE:$a>>>\"; cat \"$d/$a.txt\"; fi; done")
        out: dict[str, str] = {}
        try:
            _i, o, _e = self._c.exec_command(cmd, timeout=120)
            raw = o.read().decode("utf-8", "replace")
        except Exception:
            return out
        for chunk in raw.split("<<<CASE:")[1:]:
            mark = chunk.find(">>>")
            if mark < 0:
                continue
            aid = chunk[:mark].strip()
            body = chunk[mark + 3:]
            if aid:
                out[aid] = _redact(body[-max_chars_each:])
        return out

    def fetch_device_context_under(self, submit_autoid: str, inner_autoid: str,
                                   max_chars: int = 14000) -> str:
        """取**某内层 case** 的完整设备上下文(配置会话 + 触发端 dig),路径在 submit_autoid 的
        staging 下(整份单跑语义)。与 fetch_device_context 同义,只是 base 指向 submit staging。
        """
        base = (f"/home/test/apv_src/report/*/*/ist_staging_*/{submit_autoid}"
                f"/test_xlsx/case.xlsx/{inner_autoid}")
        sources = [
            # 框架逐步执行 + 每个 check_point 明细 + **case 内异常/traceback**（最富信息，放最前）。
            ("框架逐步执行+断言明细+异常", f"{base}/{inner_autoid}.txt"),
            ("设备配置会话(每条命令+设备响应)", f"{base}/apv_*.txt"),
            ("触发端会话 RouterA(dig 真实输出)", f"{base}/RouterA.txt"),
            ("触发端会话 RouterB(dig 真实输出)", f"{base}/RouterB.txt"),
            ("触发端会话 clientc", f"{base}/clientc.txt"),
        ]
        per = max(1500, max_chars // max(1, len(sources)))
        parts: list[str] = []
        try:
            for label, g in sources:
                _i, o, _e = self._c.exec_command(f"ls -t {g} 2>/dev/null | head -1", timeout=20)
                path = o.read().decode("utf-8", "replace").strip()
                if not path:
                    continue
                _i, o, _e = self._c.exec_command(f"cat '{path}'", timeout=20)
                text = o.read().decode("utf-8", "replace")
                if text.strip():
                    parts.append(f"=== {label} ({path.split('/')[-1]}) ===\n{text[-per:]}")
        except Exception:
            return ""
        return _redact("\n\n".join(parts))

    def fetch_device_context(self, autoid: str, max_chars: int = 9000) -> str:
        """拉**完整设备上下文**（上机失败诊断用，喂给 agent 让它知道怎么改/怎么填）。

        fetch_case_detail 只给 check_point 裁决（找没找到）；失败时 agent 还需要看到：
        ① **设备配置会话原文**（每条 config 命令 + 设备的真实响应，含 "Failed to execute X
           because Y"）→ 知道**哪条命令、为什么被拒** → 怎么改；
        ② **触发端会话**（RouterA/clientc 的 dig 等真实输出，含 ANSWER SECTION / 解析出的 IP）
           → 知道设备**实际返回了什么** → 怎么填 <RUNTIME>。
        这些是自动化框架已经写在跳转机报告目录里的原始 log，原样取来不解析。
        """
        base = (f"/home/test/apv_src/report/*/*/ist_staging_*/{autoid}/test_xlsx")
        sources = [
            ("设备配置会话(每条命令+设备响应)", f"{base}/case.xlsx/apv_*.txt"),
            ("触发端会话 RouterA(dig 真实输出)", f"{base}/RouterA.txt"),
            ("触发端会话 clientc", f"{base}/clientc.txt"),
        ]
        per = max(1500, max_chars // max(1, len(sources)))
        parts: list[str] = []
        try:
            for label, g in sources:
                _i, o, _e = self._c.exec_command(f"ls -t {g} 2>/dev/null | head -1", timeout=20)
                path = o.read().decode("utf-8", "replace").strip()
                if not path:
                    continue
                _i, o, _e = self._c.exec_command(f"cat '{path}'", timeout=20)
                text = o.read().decode("utf-8", "replace")
                if text.strip():
                    parts.append(f"=== {label} ({path.split('/')[-1]}) ===\n{text[-per:]}")
        except Exception:
            return ""
        return _redact("\n\n".join(parts))

    def fetch_task_log_errors(self, task_id: str, max_chars: int = 2800) -> str:
        """取框架 task 日志里的 pytest 异常/traceback——**文件级崩溃**真因。

        某个 case 的断言让整份 pytest 崩（如 found_times 缺 times 的 TypeError、found(None)
        的 TypeError）时，崩溃点之后的 case 全 ``unknown``，而**逐 case 日志看不到这个崩因**
        （它崩在框架层、写在 ``tasks/<task_id>.log`` 里）。这里把它取出来，让 agent 知道
        “不是这些 case 本身错，是前面某个 case 把整份 pytest 搞崩了，traceback 指向哪一行”。
        """
        if not task_id:
            return ""
        log = f"/home/test/mcp_server/tasks/{task_id}.log"
        try:
            cmd = (f"grep -nE 'Traceback|Error|Exception|FAILED|test_xlsx\\.py:|missing .* argument' "
                   f"'{log}' 2>/dev/null | tail -40; echo '--- log tail ---'; tail -20 '{log}' 2>/dev/null")
            _i, o, _e = self._c.exec_command(cmd, timeout=20)
            text = o.read().decode("utf-8", "replace")
            return _redact(text[-max_chars:]) if text.strip() else ""
        except Exception:  # noqa: BLE001
            return ""

