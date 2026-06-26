"""框架 MCP server：手写纯标准库 stdio JSON-RPC（MCP 协议子集）。

跳转机 Py3.8 + 离线，官方 mcp SDK 装不了 → 手写。传输=stdio（IST-Core 经 SSH 启动本进程
并接管 stdin/stdout，langchain-mcp-adapters stdio transport 原生支持）。

实现 MCP 必需方法：initialize / notifications/initialized / tools/list / tools/call。
逐行读 JSON-RPC（Content-Length 帧 或 行分隔 JSON，两者都支持）。

CWD 必须 = apv_src（由部署/启动脚本保证；这里也 chdir 兜底）。
"""

import json
import os
import sys
import traceback

APV_SRC = os.environ.get("IST_APV_SRC", "/home/test/apv_src")
SERVER_DIR = os.environ.get("IST_MCP_SERVER_DIR", "/home/test/mcp_server")

# 保证 import result_db / framework lib 都在正确路径
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)
if APV_SRC not in sys.path:
    sys.path.insert(0, APV_SRC)
try:
    os.chdir(APV_SRC)
except Exception:
    pass

import tools  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"

TOOL_DEFS = [
    {
        "name": "list_capabilities",
        "description": "读取框架能力源（command_function_mapping 中文意图→func + synonyms + 通用反射方法 + 断言类型 + test_env 主机）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_case_xlsx",
        "description": "用框架原生 read_excel_with_openpyxl 读 xlsx 为 cell-grid（结构往返对账用）。",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "write_case",
        "description": "把 base64 编码的 xlsx 落到 staging 子目录 ist_staging_<module>/<autoid>/case.xlsx（原子写 + 软链 test_xlsx.py）。",
        "inputSchema": {"type": "object", "properties": {
            "module": {"type": "string"}, "autoid": {"type": "string"}, "xlsx_b64": {"type": "string"},
        }, "required": ["module", "autoid", "xlsx_b64"]},
    },
    {
        "name": "run_cases_submit",
        "description": "后台跑 staging 单用例（.python3.8 -m pytest，cwd=apv_src，全局单跑锁），返回 task_id。",
        "inputSchema": {"type": "object", "properties": {
            "module": {"type": "string"}, "autoid": {"type": "string"}, "build": {"type": "string"},
        }, "required": ["module", "autoid", "build"]},
    },
    {
        "name": "run_cases_status",
        "description": "查 task 状态 + 框架 MySQL 结果（per case_id pass/fail，主源）+ 日志尾部。",
        "inputSchema": {"type": "object", "properties": {
            "task_id": {"type": "string"}, "build": {"type": "string"},
            "case_ids": {"type": "array", "items": {"type": "string"}},
        }, "required": ["task_id"]},
    },
    {
        "name": "promote_case",
        "description": "staging 通过后整 feature 晋升到正式 smoke_test/<module>/<feature>/（按文件晋升，保留同 xlsx 内全部 case），并把 case_autoids 写入 lists/<module> run 清单 + autoid 命名空间防撞登记。",
        "inputSchema": {"type": "object", "properties": {
            "module": {"type": "string"},
            "autoid": {"type": "string"},
            "feature": {"type": "string"},
            "xlsx_path": {"type": "string"},
            "case_autoids": {"type": "array", "items": {"type": "string"}},
            "source": {"type": "string"},
            "overwrite": {"type": "boolean"},
            "list_name": {"type": "string"},
        }, "required": ["module"]},
    },
    {
        "name": "probe_show",
        "description": "只读设备探针：在被测设备跑 show/get 命令取实证输出（KP1 设备 overlay 源）。硬白名单首 token show/get，单跑锁与 run_cases 互斥。",
        "inputSchema": {"type": "object", "properties": {
            "command": {"type": "string"},
        }, "required": ["command"]},
    },
    {
        "name": "init_device",
        "description": "设备初始化：通过串口连接设备，清除全部配置（clear config all），重新配置接口 IP（port1 管理口 + port2/port3 固定地址）。编译入口固化用，让 draft 探针见干净已知态。单跑锁与 probe_show/run_cases 互斥。读 conf 自动获取设备 IP/账号/端口。",
        "inputSchema": {"type": "object", "properties": {
            "device_count": {"type": "integer", "description": "初始化设备数（1/2/3），0=自动从 conf 推断", "default": 0},
            "device_index": {"type": "integer", "description": "指定初始化哪台（0/1/2），优先级高于 device_count", "default": -1},
        }},
    },
]

DISPATCH = {
    "list_capabilities": lambda a: tools.list_capabilities(),
    "read_case_xlsx": lambda a: tools.read_case_xlsx(a["path"]),
    "write_case": lambda a: tools.write_case(a["module"], a["autoid"], a["xlsx_b64"]),
    "run_cases_submit": lambda a: tools.run_cases_submit(a["module"], a["autoid"], a["build"]),
    "run_cases_status": lambda a: tools.run_cases_status(a["task_id"], a.get("build"), a.get("case_ids")),
    "promote_case": lambda a: tools.promote_case(
        a["module"], autoid=a.get("autoid"), feature=a.get("feature"),
        xlsx_path=a.get("xlsx_path"), case_autoids=a.get("case_autoids"),
        source=a.get("source"), overwrite=a.get("overwrite", False),
        list_name=a.get("list_name")),
    "probe_show": lambda a: tools.probe_show(a["command"], a.get("build", "")),
    "init_device": lambda a: tools.init_device(a.get("device_count", 0), a.get("device_index", -1)),
}


def _send(obj):
    data = json.dumps(obj)
    sys.stdout.write(data + "\n")
    sys.stdout.flush()


def _handle(req):
    mid = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ist-framework-mcp", "version": "1.0.0"},
        }}
    if method in ("notifications/initialized", "initialized"):
        return None  # notification, no response
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOL_DEFS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = DISPATCH.get(name)
        if not fn:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "unknown tool %s" % name}}
        try:
            result = fn(args)
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "isError": bool(isinstance(result, dict) and result.get("error")),
            }}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid, "error": {
                "code": -32000, "message": str(e), "data": traceback.format_exc()}}
    if mid is not None:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % method}}
    return None


def _read_messages(stream):
    """支持两种帧：Content-Length 头 或 一行一个 JSON。"""
    buf = stream.readline()
    while buf:
        line = buf.strip()
        if not line:
            buf = stream.readline()
            continue
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip())
            stream.readline()  # blank line
            body = stream.read(length)
            yield json.loads(body)
        else:
            try:
                yield json.loads(line)
            except Exception:
                pass
        buf = stream.readline()


def main():
    for req in _read_messages(sys.stdin):
        resp = _handle(req)
        if resp is not None:
            _send(resp)


if __name__ == "__main__":
    main()
