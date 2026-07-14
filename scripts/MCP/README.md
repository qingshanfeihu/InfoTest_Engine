# APV MCP Server

远程设备管理 MCP (Model Context Protocol) 服务器，提供以下工具：

| 工具 | 说明 | 协议 |
|------|------|------|
| `apv_restapi_execute` ⭐ | 通过 REST API 向 APV 设备下发命令（**推荐首选**） | HTTPS |
| `apv_ssh_execute` | SSH 到 APV 设备执行 CLI 命令 | SSH |
| `apv_telnet_execute` | Telnet 到 APV 设备执行 CLI 命令 | Telnet |
| `linux_ssh_execute` | SSH 到 Linux 服务器执行 shell 命令 | SSH |
| `device_session_open` | 打开一个持久连接到设备 | 任意 |
| `device_session_exec` | 在已打开的会话上执行命令 | 任意 |
| `device_session_close` | 关闭一个持久会话 | — |
| `device_session_list` | 列出所有活跃会话 | — |
| `smoke_test_run` | 在 Linux 测试服务器上运行自动化测试 | pytest |

## 性能对比

实测向 APV 设备 (InfosecOS 10.5.1.5) 下发 `show version`：

| 方式 | 耗时 | 加速比 |
|------|------|--------|
| **REST API** | **0.43s** | — |
| SSH | 9.47s | REST 快 **22×** |

> REST API 一次 HTTPS POST 直连设备 CLI 引擎，无 SSH 握手、shell 交互、`--More--` 分页开销。条件允许时始终优先使用 `apv_restapi_execute`。

## 兼容性

| Python | MCP 能力 | 说明 |
|--------|---------|------|
| **3.10+** | 完整 | 使用官方 `mcp` SDK (FastMCP) |
| **3.8 / 3.9** | 完整 | 自动切换内置兼容层 `_mcp_compat.py`（MCP JSON-RPC 协议自实现，功能等价，零额外依赖） |
| < 3.8 | 不可用 | 缺少 `asyncio` 关键 API |

客户端模块（`ssh_apv` / `telnet_apv` / `restapi_apv` / `ssh_linux`）在所有 Python 3.8+ 上均可独立 `import` 使用，不依赖 MCP 框架。

## 环境要求

- **Python 3.8+**
- 官方 SDK 模式（3.10+）：`mcp>=1.0.0`
- `paramiko>=3.4.0` — SSH 客户端
- `httpx>=0.24.0` — HTTP 客户端（REST API）
- `python-dotenv>=1.0.0` — 环境变量加载（可选）

## 安装

```bash
# Python 3.10+（完整依赖）
pip install -e .

# Python 3.8/3.9（跳过 mcp，自动使用内置兼容层）
pip install paramiko>=3.4.0 httpx>=0.24.0 python-dotenv
```

## 快速开始

### Stdio 模式（Claude Desktop、Cline 等）

```bash
python server.py
```

Claude Desktop 配置 (`claude_desktop_config.json`)：
```json
{
  "mcpServers": {
    "apv-device-manager": {
      "command": "python",
      "args": ["/path/to/InfoTest_Engine/scripts/MCP/server.py"],
      "env": {
        "APV_RESTAPI_USERNAME": "rest",
        "APV_RESTAPI_PASSWORD": "admin",
        "APV_USERNAME": "admin",
        "APV_PASSWORD": "admin",
        "APV_ENABLE_PASSWORD": "",
        "LINUX_SSH_USERNAME": "root",
        "LINUX_SSH_PASSWORD": "click1"
      }
    }
  }
}
```

### HTTP 模式（远程访问）

```bash
python server.py --http
# 默认监听 http://127.0.0.1:8000/mcp
# 可通过 MCP_HOST / MCP_PORT 环境变量自定义
```

### SSE 模式（旧版客户端）

```bash
python server.py --sse
```

## 使用示例

### APV REST API（最快方式，推荐优先使用）

```
apv_restapi_execute(host="172.16.6.86", port=9997, command="show version")
apv_restapi_execute(host="172.16.6.86", port=9997, command="show slb virtual all")
```

### APV SSH

```
apv_ssh_execute(host="172.16.34.70", command="show slb virtual all", mode="show")
apv_ssh_execute(host="172.16.34.70", command="slb virtual http v1 172.16.34.100 80 arp 0", mode="config")
```

### APV Telnet

```
apv_telnet_execute(host="172.16.34.70", port=23, command="show interface", mode="show")
```

### Linux SSH

```
linux_ssh_execute(host="10.0.0.100", command="df -h")
```

### 持久会话（多条命令复用连接）

```
# 打开会话
device_session_open(host="172.16.34.70", device_type="apv_ssh")

# 执行命令（复用同一连接）
device_session_exec(session_id="abc123", command="show slb virtual all")
device_session_exec(session_id="abc123", command="show interface")

# 关闭会话
device_session_close(session_id="abc123")
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APV_USERNAME` | `admin` | APV 设备 SSH/Telnet 用户名 |
| `APV_PASSWORD` | `admin` | APV 设备 SSH/Telnet 密码 |
| `APV_ENABLE_PASSWORD` | `""` | APV 设备 enable 模式密码 |
| `APV_RESTAPI_USERNAME` | `admin` | REST API 用户名 |
| `APV_RESTAPI_PASSWORD` | `admin` | REST API 密码 |
| `LINUX_SSH_USERNAME` | `root` | Linux 服务器 SSH 用户名 |
| `LINUX_SSH_PASSWORD` | `click1` | Linux 服务器 SSH 密码 |
| `LINUX_SSH_KEY` | `""` | Linux SSH 私钥文件路径 |
| `MCP_HOST` | `127.0.0.1` | HTTP/SSE 监听地址 |
| `MCP_PORT` | `8000` | HTTP/SSE 监听端口 |

## 项目结构

源码位于仓库 `scripts/MCP/`（2026-06-30 自根目录 `MCP_Server/` 迁入）。跳板机 HTTP 部署路径通常为 `/home/test/MCP_Server/`。

```
scripts/MCP/
├── server.py                      # 入口（加载 .env，Py 版本检查，启动 MCP 服务）
├── pyproject.toml                 # 项目配置与依赖（Python 3.8+）
├── .env.example                   # 环境变量模板
├── README.md
└── src/
    └── apv_mcp_server/
        ├── __init__.py
        ├── server.py              # FastMCP 应用 + 9 个工具注册
        ├── _mcp_compat.py         # MCP 协议兼容层（Python 3.8/3.9 自动启用）
        ├── ssh_apv.py             # APVSSHClient — paramiko 交互式 shell（密码提示 / enable / --More-- 自动处理）
        ├── telnet_apv.py          # APVTelnetClient — raw socket telnet（IAC 协商 + 密码提示自动识别）
        ├── restapi_apv.py         # execute_restapi() — httpx REST API 客户端
        └── ssh_linux.py           # LinuxSSHClient — paramiko exec_command
```

> 编译/上机验证用的 stdio 框架 server 是另一套：`main/device_mcp_server/`，部署到跳板机 `/home/test/mcp_server/`。

## 设计说明

- **REST API 优先** — `apv_restapi_execute` 比 SSH/Telnet 快 20× 以上（单次 HTTPS POST vs 交互式 shell），SSH/Telnet 作为备选方案。
- **内置 MCP 兼容层** — `_mcp_compat.py` 在 Python 3.8/3.9 上替代官方 `mcp` SDK，自行实现 JSON-RPC 2.0 协议（stdio Content-Length 帧 + HTTP POST），无需额外依赖即可启动完整的 MCP 服务。
- **所有阻塞 I/O 在线程池中运行** — paramiko/socket 操作通过 `loop.run_in_executor()` 包装，避免阻塞异步事件循环。
- **每次工具调用为原子操作** — 创建连接 → 执行命令 → 断开连接。会话工具提供可选的持久连接。
- **APV CLI 特性** — 处理 InfosecOS（非 Cisco IOS）的提示符模式、`--More--` 分页、enable/config 模式切换、密码提示自动识别。
- **Telnet 采用原生 socket** — Python 3.13 移除了 `telnetlib`，改用原生 socket + Telnet IAC 协商实现，向下兼容 3.8+。

## License

MIT
