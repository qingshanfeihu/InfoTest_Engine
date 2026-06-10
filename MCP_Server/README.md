# APV MCP Server

远程设备管理 MCP (Model Context Protocol) 服务器，提供以下工具：

| 工具 | 说明 | 协议 |
|------|------|------|
| `apv_ssh_execute` | SSH 到 APV 设备执行 CLI 命令 | SSH |
| `apv_telnet_execute` | Telnet 到 APV 设备执行 CLI 命令 | Telnet |
| `apv_restapi_execute` | 通过 REST API 向 APV 设备下发命令 | HTTPS |
| `linux_ssh_execute` | SSH 到 Linux 服务器执行 shell 命令 | SSH |
| `device_session_open` | 打开一个持久连接到设备 | 任意 |
| `device_session_exec` | 在已打开的会话上执行命令 | 任意 |
| `device_session_close` | 关闭一个持久会话 | — |
| `device_session_list` | 列出所有活跃会话 | — |

## 环境要求

- **Python 3.11+**
- `mcp>=1.0.0` — MCP 官方 Python SDK (FastMCP)
- `paramiko>=5.0.0` — SSH 客户端
- `httpx>=0.28.0` — HTTP 客户端（REST API）

## 安装

```bash
# 从本地目录安装
pip install -e .

# 或直接安装
pip install .
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
      "args": ["D:/MCP_Server/server.py"],
      "env": {
        "APV_USERNAME": "admin",
        "APV_PASSWORD": "admin",
        "APV_ENABLE_PASSWORD": "",
        "APV_RESTAPI_USERNAME": "admin",
        "APV_RESTAPI_PASSWORD": "admin",
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

### Linux 服务器部署

```bash
pip install mcp paramiko httpx
python server.py
```

## 使用示例

### APV SSH

```
apv_ssh_execute(host="172.16.34.70", command="show slb virtual all", mode="show")
apv_ssh_execute(host="172.16.34.70", command="slb virtual http v1 172.16.34.100 80 arp 0", mode="config")
```

### APV Telnet

```
apv_telnet_execute(host="172.16.34.70", port=23, command="show interface", mode="show")
apv_telnet_execute(host="172.16.34.70", port=23, command="hostname APV-01", mode="config")
```

### APV REST API（最快方式，推荐优先使用）

```
apv_restapi_execute(host="172.16.34.70", port=9997, command="show slb virtual all")
apv_restapi_execute(host="172.16.34.70", port=9997, command="show running")
```

### Linux SSH

```
linux_ssh_execute(host="10.0.0.100", command="df -h")
linux_ssh_execute(host="10.0.0.100", command="systemctl status nginx")
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

```
D:\MCP_Server\
├── server.py                      # 入口（加载 .env，启动 MCP 服务）
├── pyproject.toml                 # 项目配置与依赖（Python 3.11+）
├── .env.example                   # 环境变量模板
├── README.md
└── src/
    └── apv_mcp_server/
        ├── __init__.py
        ├── server.py              # FastMCP 应用 + 8 个工具注册
        ├── ssh_apv.py             # APVSSHClient — paramiko 交互式 shell（含密码提示自动识别）
        ├── telnet_apv.py          # APVTelnetClient — raw socket telnet（含 IAC 协商 + 密码提示自动识别）
        ├── restapi_apv.py         # execute_restapi() — httpx REST API 客户端
        └── ssh_linux.py           # LinuxSSHClient — paramiko exec_command（默认密码 click1）
```

## 设计说明

- **所有阻塞 I/O 在线程池中运行** — paramiko/socket 操作通过 `loop.run_in_executor()` 包装，避免阻塞异步事件循环。
- **每次工具调用为原子操作** — 创建连接 → 执行命令 → 断开连接。会话工具提供可选的持久连接。
- **APV CLI 特性** — 处理 InfosecOS（非 Cisco IOS）的提示符模式、`--More--` 分页、enable/config 模式切换。
- **Telnet 采用原生 socket** — Python 3.13 移除了 `telnetlib`，改用原生 socket + Telnet IAC 协商实现。
- **REST API 优先** — `apv_restapi_execute` 比 SSH/Telnet 快得多（单次 HTTP POST vs 交互式 shell），SSH/Telnet 作为备选方案。

## License

MIT
