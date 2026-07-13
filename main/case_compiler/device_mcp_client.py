"""IST-Core 侧框架 MCP client 驱动（经 SSH 启动跳转机 stdio server）。

首发用直接 paramiko + stdio JSON-RPC 驱动（与 langchain-mcp-adapters stdio transport
等价的最小实现）；后续可平滑换成 MultiServerMCPClient 适配成 LangChain tool。

凭据：跳转机 SSH 口令从 env IST_JUMPHOST_PASS / JUMPHOST_PASS 取，不落盘不回显。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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
        logger.debug("跳板机 SSH 连接失败: host=%s", env.jumphost, exc_info=True)
        return False
    try:
        _i, o, _e = c.exec_command(f"test -f {env.server_path} && echo OK", timeout=timeout)
        if o.read().decode("utf-8", "replace").strip() != "OK":
            return False
        if os.environ.get("IST_HEALTH_CHECK_DEVICE", "1") == "0":
            return True
        return _device_reachable_via(c, env, timeout=timeout)
    except Exception:  # noqa: BLE001
        logger.debug("探活检查失败: host=%s", env.jumphost, exc_info=True)
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
        logger.debug("设备可达性探活异常(保守放行)", exc_info=True)
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

# ── Option Y（废弃老 stdio server）：verify 编排上移客户端，经 SSH/sftp 直驱跳板机 ──
# 跳板机路径镜像老 device_mcp_server/tools.py 默认值（单一事实源同步）。IST_VERIFY_CLIENTSIDE=1
# 时 deliver/run/status/init_device 走客户端 SSH 实现、不经老 stdio server。
# **默认已翻 1**（Option Y：deliver/run/status/init_device 四函数单 case+batch 真机 E2E 全过）；
# IST_VERIFY_CLIENTSIDE=0 可临时回退老 self.call 路径（老 server 删除前的安全网）。
_JH_APV_SRC = os.environ.get("IST_APV_SRC", "/home/test/apv_src")
_JH_STAGING_MODULE = os.environ.get("IST_STAGING_MODULE", "sdns")
_JH_STAGING_PARENT = os.environ.get("IST_STAGING_PARENT", _JH_APV_SRC + "/smoke_test/" + _JH_STAGING_MODULE)
_JH_PY38 = os.environ.get("IST_JUMPHOST_PY38", _JH_APV_SRC + "/.python3.8/bin/python")
_JH_TASK_DIR = os.environ.get("IST_MCP_TASK_DIR", "/home/test/mcp_server/tasks")
_JH_LOCK_FILE = os.environ.get("IST_MCP_LOCK_FILE", "/home/test/mcp_server/run.lock")
_JH_RESULT_DB_DIR = os.environ.get("IST_RESULT_DB_DIR", "/home/test/mcp_server")  # result_db.py(MySQL 读)所在
_VERIFY_CLIENTSIDE = os.environ.get("IST_VERIFY_CLIENTSIDE", "1") == "1"

# Option Y：run 提交脚本（经 python3 - 走 stdin 在跳板机跑；锁/setsid 脱离必须在跳板机执行）。
# 忠实 port 老 tools.py _submit_pytest：O_EXCL 锁 → 写 runner.sh(setsid pytest+写 done 状态+rm 锁)
# → setsid Popen 脱离 → 写真实 pid 入锁。撞锁回结构化 busy。argv: APV_SRC PY38 TASK_DIR LOCK_FILE
# STAGING_PARENT module autoid build。stdout 打 JSON。
_SUBMIT_SCRIPT = r'''
import os, sys, json, time, subprocess
APV_SRC, PY38, TASK_DIR, LOCK_FILE, STAGING_PARENT, module, autoid, build = sys.argv[1:9]
os.makedirs(TASK_DIR, exist_ok=True)
stg = os.path.join(STAGING_PARENT, "ist_staging_%s" % module, str(autoid))
xnode = os.path.join(stg, "test_xlsx.py")
node = xnode if os.path.exists(xnode) else (stg if os.path.isdir(stg) else None)
if not node:
    print(json.dumps({"error": "staging not found: %s" % stg})); sys.exit(0)
def read_lock():
    try:
        s = open(LOCK_FILE).read().strip()
        if not s: return None
        p = s.split(":"); return (":".join(p[:-1]), int(p[-1]))
    except Exception: return None
def pid_alive(pid):
    try: os.kill(pid, 0); return True
    except Exception: return False
def acquire():
    for _ in (0, 1):
        try: return os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            h = read_lock()
            if h and pid_alive(h[1]): return None
            try: os.unlink(LOCK_FILE)
            except FileNotFoundError: pass
    return None
fd = acquire()
if fd is None:
    h = read_lock(); tid = h[0] if h else ""; aid = ""; started = None
    if tid:
        parts = tid.split("_")
        if len(parts) >= 4 and parts[-1].isdigit(): aid = parts[-2]; started = int(parts[-1])
        try:
            st = json.load(open(os.path.join(TASK_DIR, tid + ".status.json")))
            started = st.get("ts", started); aid = st.get("autoid", aid)
        except Exception: pass
    el = int(time.time() - started) if started else None
    msg = "环境忙：正在验证用例 %s" % (aid or "?")
    if el is not None: msg += "，已运行 %ds" % el
    print(json.dumps({"error": "device_busy", "busy": True, "running_autoid": aid,
                      "running_task_id": tid, "elapsed_s": el, "message": msg}))
    sys.exit(0)
task_id = "ist_%s_%s_%d" % (module, autoid, int(time.time()))
log = os.path.join(TASK_DIR, task_id + ".log"); status = os.path.join(TASK_DIR, task_id + ".status.json")
junit = os.path.join(TASK_DIR, task_id + ".xml"); runner = os.path.join(TASK_DIR, task_id + ".sh")
script = ("#!/bin/bash\ncd '%s'\n'%s' -m pytest -s '%s' --build '%s' --junitxml '%s' > '%s' 2>&1\nRC=$?\n"
          % (APV_SRC, PY38, node, build, junit, log) +
          "python3 -c \"import json,time;json.dump({'task_id':'%s','state':'done','rc':$RC,'build':'%s','module':'%s','autoid':'%s','ts':time.time()},open('%s','w'))\"\n"
          % (task_id, build, module, autoid, status) + "rm -f '%s'\n" % LOCK_FILE)
open(runner, "w").write(script); os.chmod(runner, 0o755)
json.dump({"task_id": task_id, "state": "running", "ts": time.time(), "build": build,
           "module": module, "autoid": autoid}, open(status, "w"))
proc = subprocess.Popen(["setsid", "bash", runner], cwd=APV_SRC, stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
os.write(fd, ("%s:%d" % (task_id, proc.pid)).encode()); os.close(fd)
print(json.dumps({"task_id": task_id}))
'''

# Option Y：init_device 脚本。忠实 port 老 tools.py init_device + _init_one_device 串口逻辑：
# 读 conf → O_EXCL 锁 → 逐设备 ssh localhost → cu -s 9600 ttyS{n} → 登录 → clear config all →
# 配 port IPv4/IPv6。argv: APV_SRC TASK_DIR LOCK_FILE device_count device_index。stdout 打 JSON。
# 在跳板机 PY38(含 paramiko)跑，故串口逻辑/锁都在跳板机执行、逻辑由客户端 owns(免改 FastMCP daemon)。
_INIT_SCRIPT = r'''
import os, sys, json, time, re, subprocess, configparser
APV_SRC, TASK_DIR, LOCK_FILE = sys.argv[1:4]
device_count = int(sys.argv[4]) if len(sys.argv) > 4 else 0
device_index = int(sys.argv[5]) if len(sys.argv) > 5 else -1
_LOCALHOST_SSH_PASS = sys.argv[6] if len(sys.argv) > 6 else os.environ.get("IST_LOCALHOST_SSH_PASS", "")
if not _LOCALHOST_SSH_PASS:
    print(json.dumps({"error": "localhost SSH password not provided (set IST_LOCALHOST_SSH_PASS or pass as arg)"})); sys.exit(0)
def conf_name():
    out = subprocess.run(["ip", "add"], capture_output=True, text=True).stdout
    m = re.search(r"10\.4\.\d+\.(\d+)/\d+", out)
    return (m.group(1) + ".conf") if m else "103.conf"
try:
    text = open(os.path.join(APV_SRC, "conf", conf_name()), "r", errors="replace").read()
except Exception as e:
    print(json.dumps({"error": "cannot read conf: %s" % e})); sys.exit(0)
cp = configparser.ConfigParser(strict=False); cp.read_string(text)
ssh_ips = [ip.strip() for ip in cp.get("comm", "ssh_ips").split(",")
           if ip.strip()] if cp.has_option("comm", "ssh_ips") else []
if not ssh_ips:
    print(json.dumps({"error": "conf [comm] ssh_ips empty"})); sys.exit(0)
hostname, user, passwd = "APV", "admin", "admin"
for sec in cp.sections():
    if sec == "comm": continue
    if cp.has_option(sec, "hostname"): hostname = cp.get(sec, "hostname")
    if cp.has_option(sec, "user"): user = cp.get(sec, "user")
    if cp.has_option(sec, "passwd"): passwd = cp.get(sec, "passwd")
    elif cp.has_option(sec, "password"): passwd = cp.get(sec, "password")
    break
port1, port2, port3 = "port1", "port2", "port3"
if cp.has_option("comm", "ports"):
    ports = [p.strip() for p in cp.get("comm", "ports").split(",")]
    if len(ports) >= 3: port1, port2, port3 = ports[0], ports[1], ports[2]
if 0 <= device_index <= 2:
    if device_index >= len(ssh_ips):
        print(json.dumps({"error": "device_index OOB"})); sys.exit(0)
    indices = [device_index]
else:
    n = device_count if device_count > 0 else len(ssh_ips)
    if n > len(ssh_ips) or n > 3:
        print(json.dumps({"error": "device_count invalid"})); sys.exit(0)
    indices = list(range(n))
os.makedirs(TASK_DIR, exist_ok=True)
def read_lock():
    try:
        s = open(LOCK_FILE).read().strip()
        if not s: return None
        p = s.split(":"); return (":".join(p[:-1]), int(p[-1]))
    except Exception: return None
def pid_alive(pid):
    try: os.kill(pid, 0); return True
    except Exception: return False
def acquire():
    for _ in (0, 1):
        try: return os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            h = read_lock()
            if h and pid_alive(h[1]): return None
            try: os.unlink(LOCK_FILE)
            except FileNotFoundError: pass
    return None
fd = acquire()
if fd is None:
    h = read_lock()
    print(json.dumps({"error": "another run in progress (lock held by %s)" % (h[0] if h else "?")})); sys.exit(0)
try: os.write(fd, ("init_%d:%d" % (int(time.time()), os.getpid())).encode())
finally: os.close(fd)
import paramiko
def ru(chan, expected, timeout=5):
    output = ""; rx = re.compile(expected); deadline = time.time() + timeout
    while time.time() < deadline:
        try: tmp = chan.recv(1024).decode("utf-8", "ignore")
        except Exception: tmp = ""
        output += tmp
        if rx.search(output): return output
    return output
def login(chan):
    chan.send("\n")
    o = ru(chan, r"(ogin)|(ew assword:)|(%s#)|Mode\]#|Init\]#|Standby\]#|Active\]#|\]>|(\]#)|(TMA#)|(TMB#)|(\]\$)|(assword:)|(config\)#)|(test#)|(\$ )|(\# )|(%s>)" % (hostname, hostname), 10)
    if re.search(r"%s>" % hostname, o) or re.search(r"\]>", o):
        chan.send("quit\n"); o = ru(chan, r"(ogin)|(\]#)|(\]\$)|(# )", 10)
        if re.search("ogin", o):
            chan.send("%s\n" % user); ru(chan, "sword:", 5); chan.send("%s\n" % passwd); o = ru(chan, r"(>)|(ew password:)", 5)
        if re.search("%s>" % hostname, o):
            chan.send("enable\n"); o = ru(chan, r"(#)|(sword:)", 5)
            if "sword:" in o: chan.send("%s\n" % passwd); ru(chan, "#", 5)
        chan.send("terminal length 0\n"); ru(chan, "#", 5)
    elif re.search("ogin", o):
        chan.send("%s\n" % user); ru(chan, "sword:", 5); chan.send("%s\n" % passwd); o = ru(chan, r"(#)|(>)", 5)
        if ">" in o:
            chan.send("enable\n"); o = ru(chan, r"(#)|(sword:)", 5)
            if "sword:" in o: chan.send("%s\n" % passwd); ru(chan, "#", 5)
        chan.send("terminal length 0\n"); ru(chan, "#", 5)
def init_one(idx, ssh_ip):
    tty = "ttyS%d" % idx; logs = []
    ssh = paramiko.SSHClient(); ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try: ssh.connect(hostname="127.0.0.1", port=22, username="test", password=_LOCALHOST_SSH_PASS, timeout=10)
    except Exception as e:
        return {"device": idx, "ssh_ip": ssh_ip, "status": "error", "error": "cannot SSH localhost: %s" % e}
    try:
        chan = ssh.invoke_shell(); chan.settimeout(5); time.sleep(1)
        try: chan.recv(2048)
        except Exception: pass
        chan.send("cu -s 9600 -l %s\n" % tty); out = ru(chan, r"(Connected.)|(\$ )", 10)
        if "Line in use" in out:
            chan.send("ps aux|%s|%s\n" % (tty, "grep -v grep")); out = ru(chan, r"\$ ", 5)
            for pid in re.findall(r"test\s+(\d+)", out):
                chan.send("kill %s\n" % pid); ru(chan, r"\$ ", 3)
            time.sleep(2); chan.send("cu -s 9600 -l %s\n" % tty); ru(chan, "Connected.", 10)
        login(chan); logs.append("login done")
        chan.send("config ter\n"); ru(chan, "#", 5)
        chan.send("no page\n"); ru(chan, r"\(config\)#", 5)
        chan.send("clear config all\n"); ru(chan, r"\(config\)#", 60)
        chan.send("support 0.0.0.0 0\n"); ru(chan, r"\(config\)#", 5); logs.append("clear done")
        for p, sub in ((port1, "35"), (port2, "34"), (port3, "32")):
            chan.send("ip add %s 172.16.%s.7%d 24\n" % (p, sub, idx)); ru(chan, r"\(config\)#", 5)
        for p, sub in ((port1, "3ffd"), (port2, "3ffc"), (port3, "3ffb")):
            chan.send("ip add %s %s::7%d 64\n" % (p, sub, idx)); ru(chan, r"\(config\)#", 5)
        chan.send("support 0.0.0.0 0\n"); ru(chan, r"\(config\)#", 5); logs.append("ip done")
        return {"device": idx, "ssh_ip": ssh_ip, "tty": tty, "status": "ok", "log": logs}
    except Exception as e:
        return {"device": idx, "ssh_ip": ssh_ip, "tty": tty, "status": "error", "error": str(e), "log": logs}
    finally:
        try: ssh.close()
        except Exception: pass
try:
    results = [init_one(idx, ssh_ips[idx]) for idx in indices]
    ok = [r for r in results if r.get("status") == "ok"]
    print(json.dumps({"initialized": len(ok), "failed": len(results) - len(ok),
                      "total": len(results), "details": results}))
finally:
    try: os.unlink(LOCK_FILE)
    except Exception: pass
'''

# Option Y：status 脚本。读 status.json + result_db(MySQL 主源,跳板机 lib) + tail log。
# argv: TASK_DIR RESULT_DB_DIR APV_SRC task_id build case_ids_json。stdout 打 JSON。
_STATUS_SCRIPT = r'''
import os, sys, json, re, subprocess
TASK_DIR, RDB_DIR, APV_SRC, task_id = sys.argv[1:5]
build = sys.argv[5] if len(sys.argv) > 5 else ""
case_ids = json.loads(sys.argv[6]) if len(sys.argv) > 6 and sys.argv[6] else []
status = {}
sp = os.path.join(TASK_DIR, task_id + ".status.json")
if os.path.exists(sp):
    try: status = json.load(open(sp))
    except Exception: pass
build = build or status.get("build")
results = {}; mysql_err = None
if build and case_ids:
    try:
        sys.path.insert(0, RDB_DIR)
        from result_db import query_results, read_mysql_ip
        out = subprocess.run(["ip", "add"], capture_output=True, text=True).stdout
        m = re.search(r"10\.4\.\d+\.(\d+)/\d+", out)
        conf = os.path.join(APV_SRC, "conf", (m.group(1) + ".conf") if m else "103.conf")
        conf_text = open(conf, "r", errors="replace").read()
        results = query_results(read_mysql_ip(conf_text), build, case_ids)
    except Exception as e:
        mysql_err = str(e)
tail = ""
lp = os.path.join(TASK_DIR, task_id + ".log")
if os.path.exists(lp):
    try: tail = "".join(open(lp, "r", errors="replace").readlines()[-25:])
    except Exception: pass
print(json.dumps({"status": status, "results": results, "mysql_error": mysql_err, "log_tail": tail}))
'''


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
    except Exception:  # noqa: BLE001
        logger.debug("解析设备 IP 失败: build=%s", build, exc_info=True)
        return None
    finally:
        if c is not None:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass


def _extract_rpc_obj(raw: str) -> dict | None:
    """SSE/JSON 文本 → 首个含 result/error 的 JSON-RPC 对象(解析不出=None)。"""
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(o, dict) and ("result" in o or "error" in o):
            return o
    return None


def fastmcp_call(tool: str, arguments: dict, env: Any = None,
                 timeout: int = 30) -> str | None:
    """通用：经跳转机新版 FastMCP(:8000) 调一个工具，返回其结果文本(content[0].text)。

    streamable-http JSON-RPC over HTTP，解析 SSE ``data:`` 行取 result/error。FastMCP 不可达 /
    响应异常 / 无 result / 墙钟死线 → 返回 None。**迁移基座**：dev_probe 走它(apv_ssh_execute)，
    后续把 init_device/deliver/run 等编排工具迁到 FastMCP 也复用它(不再各写一遍 HTTP+SSE)。
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
    buf = bytearray()
    obj: dict | None = None
    try:
        import time as _time
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # 墙钟死线逐块读:urlopen 的 timeout 只是 socket idle 超时,SSE keep-alive
            # 会不断续租它——2026-07-13 实证:服务端工具调用卡死时,单发 resp.read()
            # 挂 20min+(回归套件在 bed 探针上级联挂死)。拿到 result/error 事件即停,
            # 不等流关闭;死线触发按不可达处理(调用方回退 stdio/如实报错)。
            deadline = _time.monotonic() + max(1, int(timeout))
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                buf += chunk
                if b'"result"' in buf or b'"error"' in buf:
                    obj = _extract_rpc_obj(buf.decode("utf-8", "replace"))
                    if obj is not None:
                        break
                if _time.monotonic() >= deadline:
                    logger.warning("FastMCP 墙钟死线触发(%ds): tool=%s host=%s"
                                   "——服务端工具调用疑似卡死", timeout, tool, host)
                    break
    except Exception:  # noqa: BLE001
        logger.debug("FastMCP HTTP 请求失败: url=%s tool=%s", url, tool, exc_info=True)
        return None
    if obj is None:
        obj = _extract_rpc_obj(buf.decode("utf-8", "replace"))
    if obj is None:
        return None
    try:
        return obj["result"]["content"][0]["text"]
    except Exception:  # noqa: BLE001
        logger.debug("FastMCP 响应解析失败: tool=%s obj=%s", tool, obj, exc_info=True)
        return None


def probe_via_fastmcp(command: str, build: str = "", env: Any = None,
                      timeout: int = 30, mode: str = "show") -> dict | None:
    """经跳转机新版 FastMCP(:8000) 的 ``apv_ssh_execute`` 在被测设备上执行命令，取回显。

    mode="show"(默认,只读探针) / "config"(配置模式——床态初始化清理用:clear 族命令在
    show 通道被设备拒,2026-07-10 实证 status:error,须走 config 通道)。
    返回 ``{"text": <服务端格式化文本，含 status + 回显 + 对齐 ^>, "device_ip": ip}``；
    设备 IP 解析不出 / FastMCP 不可达 / 响应异常 → 返回 None（上层回退老 stdio probe_show）。
    """
    device_ip = resolve_device_ip(build, env)
    if not device_ip:
        return None
    text = fastmcp_call("apv_ssh_execute",
                        {"host": device_ip, "command": command, "mode": mode},
                        env=env, timeout=timeout)
    if text is None:
        return None
    return {"text": text, "device_ip": device_ip}


# ── CLI context-help（`?`）探针：设备回 `^`/Failed 后，追问设备"这个位置到底期望什么" ──
# 为什么不复用 apv_ssh_execute：服务端 send_command 强制补 `\n`，`?` 打完帮助后那个 `\n` 会把
# **截断到 `?` 前的前缀命令真的执行一次**（实测 `sdns host pool "h" "p" ?` → 触发一次 host-pool
# 绑定尝试）。前缀若是完整的会改配置的命令（真实对象上就是 mutate），这就是**真实副作用**——
# 引擎里自动跑不能留。故走跳板机 direct-tcpip 代理开设备交互 shell，自己控制字节：
# 发 `<prefix> ?`（不回车）→ 读帮助 → 发 Ctrl-U(\x15) 杀整行（绝不回车执行）→ 零副作用（已实证
# `show sdns host name` 无残留）。enable 密码为空（直接回车），config 模式进 `?` 才是配置命令语义。

def _split_cli_tokens(command: str) -> list[str]:
    """按空白切 CLI token，但**保留引号整体**（含引号本身），供逐前缀重建带引号命令。

    `sdns host pool "a.b.com" "p1" 5` → ['sdns','host','pool','"a.b.com"','"p1"','5']。
    引号内空白不切；未闭合引号吞到行尾（设备侧也会这么解析）。
    """
    toks: list[str] = []
    buf = ""
    quote = ""
    for chch in command.strip():
        if quote:
            buf += chch
            if chch == quote:
                quote = ""
        elif chch in ('"', "'"):
            quote = chch
            buf += chch
        elif chch.isspace():
            if buf:
                toks.append(buf); buf = ""
        else:
            buf += chch
    if buf:
        toks.append(buf)
    return toks


def _qhelp_extract(raw: str, prefix: str) -> tuple[bool, str]:
    """从 `<prefix> ?` 的原始回显里剥出帮助文本。返回 (是否真帮助, 帮助文本)。

    无效位置设备回 `^`（无文字）；有效位置回一段说明/子命令表。剥掉命令回显行、裸提示符、
    孤立 `^`、空行后若还有实质内容 = 真帮助。
    """
    help_lines: list[str] = []
    only_caret = False
    for ln in raw.replace("\r", "\n").split("\n"):
        s = ln.strip()
        if not s:
            continue
        if s == "^":
            only_caret = True
            continue
        # 命令回显行（含发出的 prefix 或以 ? 结尾）
        if prefix and prefix in ln:
            continue
        if s.endswith("?") and len(s) <= len(prefix) + 4:
            continue
        # 裸提示符
        if re.match(r"^[\w\-]+(\([^)]*\))?[#>]\s*$", s):
            continue
        # 提示符粘着回显（APV(config)#sdns host pool）
        if re.match(r"^[\w\-]+(\([^)]*\))?[#>]", s):
            continue
        help_lines.append(s)
    text = "\n".join(help_lines).strip()
    return (bool(text), text if text else ("(仅 ^，无文字：该位置语法非法)" if only_caret else ""))


def cli_qhelp(command: str, build: str = "", env: Any = None,
              timeout: int = 25) -> dict:
    """对一条（通常刚报 `^`/Failed 的）命令做 CLI context-help 追问，解释设备为何拒绝。

    机制：跳板机 direct-tcpip 代理 → 设备交互 shell → enable(空密码)+config → 对命令的各前缀
    发 `<prefix> ?`（不回车）+ Ctrl-U 清行（零执行/零副作用）。从最长前缀往回退，找到**最长可
    解析前缀**及其后设备期望的 token 说明 = 第一个"越位" token 的解释。

    返回 dict：
      device_ip / mode / ok(bool 连通)
      full_valid(bool)：整条命令语法可解析（`^` 非语法问题，多为语义/引用类）
      offending(str|None)：第一个越位 token
      valid_prefix(str)：最长可解析前缀
      expect(str)：该位置设备期望的说明（`?` 帮助文本）
      map(list[{prefix,expect}])：探到的各位置期望（供 LLM 自查）
      error(str)：连不通/异常时的说明
    """
    import paramiko
    toks = _split_cli_tokens(command)
    if not toks:
        return {"ok": False, "error": "空命令"}
    first = toks[0].lower()
    # show/get 类在 enable 模式问 ?；配置命令进 config 模式
    use_config = first not in ("show", "get", "ping", "ping6", "traceroute",
                               "traceroute6", "nslookup")
    device_ip = resolve_device_ip(build, env)
    if not device_ip:
        return {"ok": False, "error": "解析不出被测设备 IP（build 段）"}
    duser = os.environ.get("APV_USERNAME", "admin")
    dpass = os.environ.get("APV_PASSWORD", "admin")

    j = d = ch = None
    try:
        j = _connect(env)
        sock = j.get_transport().open_channel(
            "direct-tcpip", (device_ip, 22), ("127.0.0.1", 0), timeout=10)
        d = paramiko.SSHClient()
        d.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        d.connect(device_ip, 22, username=duser, password=dpass, sock=sock,
                  timeout=15, look_for_keys=False, allow_agent=False)
        ch = d.invoke_shell(term="vt100", width=200, height=50)
        ch.settimeout(8)
        time.sleep(1.2)
        try:
            ch.recv(65535)
        except Exception:  # noqa: BLE001
            pass

        def _ru(expect: str, t: float = 6.0) -> str:
            out = ""
            rx = re.compile(expect)
            dl = time.time() + t
            while time.time() < dl:
                try:
                    out += ch.recv(65535).decode("utf-8", "ignore")
                except Exception:  # noqa: BLE001
                    pass
                if rx.search(out):
                    break
                time.sleep(0.2)
            return out

        # enable（空密码）→ 需要则 config
        ch.send("enable\n")
        o = _ru(r"(#)|(sword:)", 5)
        if "sword" in o.lower():
            ch.send("\n")
            _ru(r"#", 5)
        mode = "enable"
        if use_config:
            ch.send("config terminal\n")
            cf = _ru(r"\(config\)#", 5)
            if "(config)#" not in cf:
                return {"ok": False, "error": "未能进入 config 模式", "device_ip": device_ip}
            mode = "config"

        def _probe(prefix: str) -> tuple[bool, str]:
            while ch.recv_ready():
                try:
                    ch.recv(65535)
                except Exception:  # noqa: BLE001
                    break
            ch.send(prefix + " ?")
            raw = ""
            dl = time.time() + 2.6
            while time.time() < dl:
                try:
                    b = ch.recv(65535)
                    if b:
                        raw += b.decode("utf-8", "ignore")
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(0.2)
            ch.send("\x15")   # Ctrl-U 杀整行，绝不回车执行
            time.sleep(0.3)
            try:
                ch.recv(65535)
            except Exception:  # noqa: BLE001
                pass
            return _qhelp_extract(raw, prefix)

        probe_map: list[dict] = []
        full_valid = False
        offending = None
        valid_prefix = ""
        expect = ""
        # 从最长前缀往回退，找最长可解析前缀
        for k in range(len(toks), 0, -1):
            prefix = " ".join(toks[:k])
            is_help, text = _probe(prefix)
            probe_map.insert(0, {"prefix": prefix, "expect": text})
            if is_help:
                valid_prefix = prefix
                expect = text
                if k == len(toks):
                    full_valid = True
                else:
                    offending = toks[k]
                break

        try:
            ch.send("\x15")
            ch.send("end\n")
            _ru(r"#", 3)
        except Exception:  # noqa: BLE001
            pass

        return {
            "ok": True, "device_ip": device_ip, "mode": mode,
            "full_valid": full_valid, "offending": offending,
            "valid_prefix": valid_prefix, "expect": _redact(expect),
            "map": [{"prefix": m["prefix"], "expect": _redact(m["expect"])} for m in probe_map],
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("cli_qhelp 异常: cmd=%s", command, exc_info=True)
        return {"ok": False, "error": f"设备交互异常: {exc}", "device_ip": device_ip}
    finally:
        for closable in (ch, d, j):
            try:
                if closable is not None:
                    closable.close()
            except Exception:  # noqa: BLE001
                pass


class FrameworkMCPClient:
    """经 SSH 驱动跳转机 stdio MCP server。每次调用开一个 server 会话（无状态命令）。"""

    def __init__(self, env: Any = None):
        self._env = env
        self._c = _connect(env)
        self._server_cmd = env.server_cmd if env is not None else SERVER_CMD

    @property
    def host(self) -> str:
        """当前上机占用的跳板机 host(env 池取 env.jumphost,否则全局 IST_JUMPHOST_HOST)。"""
        return self._env.jumphost if self._env is not None else JUMPHOST

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
    # 注：list_capabilities/promote_case/read_case_xlsx 老 server 工具 IST-Core 从不调用，
    # 客户端不再封装（Option Y 废弃老版顺手收口，不留死接口）。

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
        device_count=0 自动从 conf ssh_ips 推断；device_index 指定单台（优先于 count）。单跑锁与
        verify 的 run_cases 互斥（撞锁返回 ``error: another run in progress``）。
        ``IST_VERIFY_CLIENTSIDE=1`` 走客户端 SSH 实现（不经老 stdio server）。
        """
        if _VERIFY_CLIENTSIDE:
            return self._init_device_clientside(device_count, device_index)
        return (self.call([("init_device",
                            {"device_count": device_count, "device_index": device_index})])
                .get("init_device") or {})

    def _init_device_clientside(self, device_count: int = 0, device_index: int = -1) -> dict:
        """Option Y：经 SSH 在跳板机(PY38+paramiko)跑串口 init 脚本（clear config all + 配 IP），

        不经老 stdio server。串口/锁逻辑必须在跳板机执行，但脚本是客户端常量（逻辑客户端 owns）。
        串口 ``clear config all`` 较慢（单台 ~30s；**多台序列化时第二台起串口读易撞满超时，实测
        两台 ~174s**），故 timeout 给到 300s 留足余量——超时会让远端脚本续跑持锁、拖垮后续 verify。
        编译入口只 init device_index=0（单台 ~30s）避开序列慢路径，见 compile_pipeline。
        """
        return self._ssh_python_json(
            _INIT_SCRIPT,
            [_JH_APV_SRC, _JH_TASK_DIR, _JH_LOCK_FILE, str(device_count), str(device_index),
             os.environ.get("IST_LOCALHOST_SSH_PASS", "")],
            timeout=300)

    def deliver(self, module: str, autoid: str, xlsx_path: str) -> dict:
        if _VERIFY_CLIENTSIDE:
            return self._deliver_clientside(module, autoid, xlsx_path)
        b64 = base64.b64encode(Path(xlsx_path).read_bytes()).decode()
        return self.call([("write_case", {"module": module, "autoid": autoid, "xlsx_b64": b64})]).get("write_case", {})

    def _deliver_clientside(self, module: str, autoid: str, xlsx_path: str) -> dict:
        """Option Y：经 SSH/sftp 把 xlsx 落到 staging，不经老 stdio server 的 write_case。

        镜像老 write_case 语义：staging=``ist_staging_<module>/<autoid>/``，原子写
        ``case.xlsx``（sftp 写 .tmp → mv）+ 软链 ``test_xlsx.py`` → ../../../../lib/test_xlsx.py。
        返回 ``{staging_dir, xlsx, bytes}`` 或 ``{error}``（永不抛）。
        """
        import posixpath
        import shlex as _sh
        try:
            data = Path(xlsx_path).read_bytes()
        except Exception as exc:  # noqa: BLE001
            return {"error": "read xlsx failed: %s" % exc}
        stg = posixpath.join(_JH_STAGING_PARENT, "ist_staging_%s" % module, str(autoid))
        final = posixpath.join(stg, "case.xlsx")
        tmp = final + ".tmp"
        link = posixpath.join(stg, "test_xlsx.py")
        try:
            _i, _o, e = self._c.exec_command("mkdir -p %s" % _sh.quote(stg), timeout=30)
            err = e.read().decode("utf-8", "replace")
            if err.strip():
                return {"error": "mkdir failed: %s" % err.strip()[:200]}
            sftp = self._c.open_sftp()
            try:
                with sftp.open(tmp, "wb") as f:
                    f.write(data)
            finally:
                sftp.close()
            # 原子 rename + 强制软链（-n 防把已存在的目录软链当目录进去）
            cmd = ("mv -f %s %s && ln -sfn ../../../../lib/test_xlsx.py %s && echo OK"
                   % (_sh.quote(tmp), _sh.quote(final), _sh.quote(link)))
            _i, o, e = self._c.exec_command(cmd, timeout=30)
            out = o.read().decode("utf-8", "replace")
            if "OK" not in out:
                return {"error": "finalize failed: %s"
                        % (e.read().decode("utf-8", "replace").strip()[:200] or out.strip()[:200])}
            return {"staging_dir": stg, "xlsx": final, "bytes": len(data)}
        except Exception as exc:  # noqa: BLE001
            return {"error": "deliver(clientside) failed: %s" % exc}

    def _ssh_python_json(self, script: str, args: list[str], timeout: int = 60) -> dict:
        """经 SSH 在跳板机跑 ``python3 - <args>``（脚本走 stdin，不留临时文件），解析 stdout JSON。

        Option Y verify run/status 用：锁/setsid 脱离/MySQL 读必须在跳板机执行，但逻辑由客户端
        owns（脚本是客户端常量）。失败/非 JSON → {"error": ...}。"""
        import shlex as _sh
        # 用框架 venv PY38（含 pymysql，result_db MySQL 查询需要）跑 wrapper；系统 python3 缺 pymysql。
        cmd = "%s - %s" % (_sh.quote(_JH_PY38), " ".join(_sh.quote(a) for a in args))
        try:
            si, so, se = self._c.exec_command(cmd, timeout=timeout)
            si.write(script)
            si.flush()
            si.channel.shutdown_write()
            out = so.read().decode("utf-8", "replace")
            err = se.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            return {"error": "ssh python failed: %s" % exc}
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except Exception:  # noqa: BLE001
                    break
        return {"error": "no JSON from jumphost: %s" % (err.strip()[:200] or out.strip()[:200])}

    def _run_clientside(self, module: str, autoid: str, build: str) -> dict:
        """Option Y：客户端经 SSH 提交上机（O_EXCL 锁 + setsid 脱离 pytest），不经老 server。"""
        return self._ssh_python_json(
            _SUBMIT_SCRIPT,
            [_JH_APV_SRC, _JH_PY38, _JH_TASK_DIR, _JH_LOCK_FILE, _JH_STAGING_PARENT,
             module, str(autoid), build],
            timeout=60)

    def _status_clientside(self, task_id: str, build: str, case_ids: list[str]) -> dict:
        """Option Y：客户端经 SSH 查 task 状态 + MySQL 结果(result_db) + tail log，不经老 server。"""
        return self._ssh_python_json(
            _STATUS_SCRIPT,
            [_JH_TASK_DIR, _JH_RESULT_DB_DIR, _JH_APV_SRC, str(task_id),
             build or "", json.dumps(case_ids or [])],
            timeout=60)

    def run(self, module: str, autoid: str, build: str) -> dict:
        """提交上机。返回 server 原始结果：成功含 task_id，撞锁含 busy 结构。"""
        if _VERIFY_CLIENTSIDE:
            return self._run_clientside(module, autoid, build)
        return (self.call([("run_cases_submit",
                            {"module": module, "autoid": autoid, "build": build})])
                .get("run_cases_submit") or {})

    def status(self, task_id: str, build: str, case_ids: list[str]) -> dict:
        if _VERIFY_CLIENTSIDE:
            return self._status_clientside(task_id, build, case_ids)
        return self.call([("run_cases_status",
                           {"task_id": task_id, "build": build, "case_ids": case_ids})]).get("run_cases_status", {})

    def run_and_wait(self, module: str, autoid: str, build: str, case_ids: list[str],
                     poll_s: int = 10, max_s: int = 600, progress_cb=None) -> dict:
        """提交一个 staging 用例并轮询到 done，返回最终 status。

        撞锁（设备正在验证上一个用例）时**不静默放弃**，把 server 的结构化 busy
        信号原样上抛（含 running_autoid / elapsed_s / message），由上层 agent 决定
        等待、跳过还是上报——而不是把"环境忙"误当成"提交失败"。

        progress_cb: 每次轮询后以当次 status dict 回调（含 ``results``/``log_tail``），
        供上层输出跑批进度；回调异常吞掉——可观测性不拖垮跑批。
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
            if progress_cb is not None:
                try:
                    progress_cb(last)
                except Exception:  # noqa: BLE001
                    pass
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

    STALE_LOG_MARK = "<<STALE_LOG>>"

    def jumphost_epoch(self) -> float:
        """跳板机当前 epoch 秒。run-identity 基线用它——staging 日志与它在**同一台机器**
        的时钟下,天然无设备/本地时差问题(设备与本地实测偏差 +5h40m,墙钟比较不可用)。"""
        try:
            _i, o, _e = self._c.exec_command("date +%s", timeout=15)
            return float(o.read().decode("utf-8", "replace").strip())
        except Exception:  # noqa: BLE001
            return 0.0

    def fetch_batch_details(self, submit_autoid: str, max_chars_each: int = 3500,
                            min_epoch: float = 0.0) -> dict[str, str]:
        """整份 xlsx 一次上机后,从 **submit_autoid 的 staging** 读回**所有内层 case** 的逐
        check_point 明细。返回 {inner_autoid: detail_text}。

        关键(实证):框架把交付的整份 xlsx 当套件整跑,所有内层 case 的日志都落在**提交时那个
        autoid** 的 staging 下:``ist_staging_*/{submit_autoid}/test_xlsx/case.xlsx/<inner>/<inner>.txt``
        ——不是各自 autoid 的独立 staging。故一次提交后用本方法一把捞齐,**不必逐 autoid 重复整跑**
        (旧 dev_run_batch O(N²) 的根因)。一条 SSH 命令带分隔符 cat 全部,减少往返。

        min_epoch(run-identity 绑定):staging 目录跨 run 复用——上一次执行被打断时旧
        ``<inner>.txt`` 原样留存,新收割会把**旧执行**的结果当本次的(2026-07-04 实证:两轮
        digest 收割到被打断执行的日志,0/34、1/34 假结果各一轮,归因据此全部误导)。传本次
        deliver 时刻的跳板机 epoch:mtime 早于它的日志条目值置为 ``STALE_LOG_MARK``,调用方
        据此判 unknown 而非采信。
        """
        base_glob = (f"/home/test/apv_src/report/*/*/ist_staging_*/{submit_autoid}"
                     f"/test_xlsx/case.xlsx")
        cmd = (f"base=$(ls -dt {base_glob} 2>/dev/null | head -1); "
               f"[ -z \"$base\" ] && exit 0; "
               f"for d in \"$base\"/*/; do a=$(basename \"$d\"); "
               f"if [ -f \"$d/$a.txt\" ]; then m=$(stat -c %Y \"$d/$a.txt\" 2>/dev/null || echo 0); "
               f"echo \"<<<CASE:$a|$m>>>\"; cat \"$d/$a.txt\"; fi; done")
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
            head = chunk[:mark].strip()
            aid, _, mtime_s = head.partition("|")
            aid = aid.strip()
            body = chunk[mark + 3:]
            if not aid:
                continue
            try:
                mtime = float(mtime_s or 0)
            except ValueError:
                mtime = 0.0
            if min_epoch > 0 and 0 < mtime < min_epoch:
                out[aid] = self.STALE_LOG_MARK
            else:
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
        # 失败机理/交互提示行优先保留(2026-07-13 echo-grounding):纯尾截会把会话**中段**的
        # 'Failed to execute'/'Type YES'/'Error:' 丢掉(668030 主设备会话实证),使归因扫不到
        # 自身执行失败。此为**采集面宽扫**(多留无害)——判定仍在消费侧文法 exec_failure_markers。
        _KEEP = re.compile(
            r'Failed to (execute|get)|RTNETLINK|aborted|Error:|Type\s+"?YES|'
            r'occupied|already (exist|used|in use)', re.IGNORECASE)
        parts: list[str] = []
        try:
            for label, g in sources:
                _i, o, _e = self._c.exec_command(f"ls -t {g} 2>/dev/null | head -1", timeout=20)
                path = o.read().decode("utf-8", "replace").strip()
                if not path:
                    continue
                _i, o, _e = self._c.exec_command(f"cat '{path}'", timeout=20)
                text = o.read().decode("utf-8", "replace")
                if not text.strip():
                    continue
                tail = text[-per:]
                keep = [ln for ln in text.splitlines()
                        if _KEEP.search(ln) and ln not in tail][:12]
                body = ("[执行失败/交互标记行(防中段截断保留)]\n" + "\n".join(keep)
                        + "\n[会话尾]\n" + tail) if keep else tail
                parts.append(f"=== {label} ({path.split('/')[-1]}) ===\n{body}")
        except Exception:
            return ""
        return _redact("\n\n".join(parts))

    def fetch_case_raw(self, submit_autoid: str, inner_autoid: str,
                       max_inner: int = 120000, max_apv_each: int = 150000) -> dict:
        """oracle 残差门取证(§18.10 窗口出处对账):某内层 case 的原始步骤日志 + 各主机
        设备会话**全文**。与 fetch_device_context_under 的本质区别:不混流、不尾截优选、
        不做标记行提取——对账审计必须走旁路拿未经预处理的文本(衍生视图与被审窗口共享
        失真,用失真通道审失真只会自洽;2026-07-14 写保存族 3 run 假 FAIL/假 PASS 实证)。
        返回 {"inner": str, "apv": {文件名: 全文}};取不到=空骨架(调用方记审计不可用)。"""
        out: dict = {"inner": "", "apv": {}}
        base = (f"/home/test/apv_src/report/*/*/ist_staging_*/{submit_autoid}"
                f"/test_xlsx/case.xlsx/{inner_autoid}")
        try:
            _i, o, _e = self._c.exec_command(
                f"ls -t {base}/{inner_autoid}.txt 2>/dev/null | head -1", timeout=20)
            ipath = o.read().decode("utf-8", "replace").strip()
            if not ipath:
                return out
            _i, o, _e = self._c.exec_command(f"tail -c {int(max_inner)} '{ipath}'", timeout=25)
            out["inner"] = _redact(o.read().decode("utf-8", "replace"))
            d = ipath.rsplit("/", 1)[0]
            _i, o, _e = self._c.exec_command(
                f"ls '{d}' 2>/dev/null | grep '^apv_.*\\.txt$'", timeout=20)
            for name in o.read().decode("utf-8", "replace").split():
                _i, o2, _e = self._c.exec_command(
                    f"tail -c {int(max_apv_each)} '{d}/{name}'", timeout=25)
                out["apv"][name] = _redact(o2.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            return out
        return out

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
        # 失败机理/交互提示行优先保留(2026-07-13 echo-grounding):纯尾截会把会话**中段**的
        # 'Failed to execute'/'Type YES'/'Error:' 丢掉(668030 主设备会话实证),使归因扫不到
        # 自身执行失败。此为**采集面宽扫**(多留无害)——判定仍在消费侧文法 exec_failure_markers。
        _KEEP = re.compile(
            r'Failed to (execute|get)|RTNETLINK|aborted|Error:|Type\s+"?YES|'
            r'occupied|already (exist|used|in use)', re.IGNORECASE)
        parts: list[str] = []
        try:
            for label, g in sources:
                _i, o, _e = self._c.exec_command(f"ls -t {g} 2>/dev/null | head -1", timeout=20)
                path = o.read().decode("utf-8", "replace").strip()
                if not path:
                    continue
                _i, o, _e = self._c.exec_command(f"cat '{path}'", timeout=20)
                text = o.read().decode("utf-8", "replace")
                if not text.strip():
                    continue
                tail = text[-per:]
                keep = [ln for ln in text.splitlines()
                        if _KEEP.search(ln) and ln not in tail][:12]
                body = ("[执行失败/交互标记行(防中段截断保留)]\n" + "\n".join(keep)
                        + "\n[会话尾]\n" + tail) if keep else tail
                parts.append(f"=== {label} ({path.split('/')[-1]}) ===\n{body}")
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

