"""
APV 设备 SSH 客户端：通过 paramiko 连接 APV/InfosecOS 负载均衡器，
执行 CLI 命令并捕获输出。支持交互式 shell、enable 模式、--More-- 分页处理。

所有方法 return 结构化数据，不 print / 不写日志——调用侧自行决定如何输出。
"""
import os
import re
import time
from typing import Dict, List, Optional

import paramiko

# CLI 错误识别收口到共享模块（main/ist_core/tools/device/device_errors.py）。
# 本脚本常被 device-verify skill 以 importlib spec 按路径独立加载（目录带连字符无法
# 作为包名），此时无法 import 项目包——故 try 绝对 import，失败则回退本地等价实现
# （marker 表须与 device_errors.DEVICE_CLI_ERROR_MARKERS 完全一致）。
try:
    from main.ist_core.tools.device.device_errors import (
        DEVICE_CLI_ERROR_MARKERS as _CLI_ERROR_MARKERS,
        has_cli_error as _has_cli_error_shared,
    )
except Exception:  # pragma: no cover - 独立 spec 加载场景
    _has_cli_error_shared = None
    _CLI_ERROR_MARKERS = (
        "% invalid",
        "% error",
        "% unknown",
        "% unrecognized",
        "syntax error",
        "invalid input",
        "command not found",
        "failed to execute",
    )


class APVSSHClient:
    """APV/InfosecOS 负载均衡器 SSH 交互客户端"""

    PROMPT_PATTERNS = [
        r'[\w\-]+>',              # 用户模式: APV>
        r'[\w\-]+#',              # enable 模式: APV#
        r'[\w\-]+\([^\)]+\)#',    # config 模式: APV(config)#
    ]
    MORE_PATTERN = r'--More--'

    def __init__(
        self,
        host: str,
        username: str = "admin",
        password: str = "admin",
        port: int = 22,
        timeout: int = 10,
        command_timeout: int = 15,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self.command_timeout = command_timeout
        self.ssh: Optional[paramiko.SSHClient] = None
        self.shell: Optional[paramiko.Channel] = None

    # ── 连接管理 ──────────────────────────────────────────────────────

    def connect(self) -> str:
        """建立 SSH 连接并打开交互式 shell，返回登录 banner"""
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(
            self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=self.timeout,
            look_for_keys=False,
            allow_agent=False,
        )
        self.shell = self.ssh.invoke_shell(term='vt100', width=200, height=50)
        self.shell.settimeout(self.command_timeout)
        banner = self._read_until_prompt(initial_wait=3.0)
        return banner

    def disconnect(self):
        """断开 SSH 连接"""
        if self.shell:
            try:
                self.shell.close()
            except Exception:
                pass
            self.shell = None
        if self.ssh:
            try:
                self.ssh.close()
            except Exception:
                pass
            self.ssh = None

    # 设备等待输入密码时的提示符
    _PASSWORD_PATTERNS = [
        r'[Pp]assword:\s*$',
        r'[Ee]nable password:\s*$',
    ]

    def _read_until_prompt(
        self,
        initial_wait: float = 1.0,
        max_wait: float = 0,
        extra_patterns: Optional[List[str]] = None,
    ) -> str:
        """读取输出直到检测到提示符或超时，自动处理 --More-- 分页

        Args:
            extra_patterns: 额外的匹配模式（如密码提示符），匹配后立即停止读取。
        """
        if max_wait <= 0:
            max_wait = self.command_timeout
        output = ""
        start = time.time()
        time.sleep(initial_wait)

        while time.time() - start < max_wait:
            if self.shell.recv_ready():
                chunk = self.shell.recv(65535).decode('utf-8', errors='replace')
                output += chunk
                if re.search(self.MORE_PATTERN, output):
                    output = re.sub(r'\s*--More--\s*', '', output)
                    self.shell.send(' ')
                    time.sleep(0.3)
                    continue
                stripped = output.rstrip()
                # 检查额外模式（密码提示等）
                if extra_patterns:
                    if any(re.search(p, stripped) for p in extra_patterns):
                        break
                if any(re.search(p + r'\s*$', stripped) for p in self.PROMPT_PATTERNS):
                    break
            else:
                time.sleep(0.3)
        return output

    def send_command(self, command: str, wait: float = 2.0) -> str:
        """发送单条命令并捕获输出"""
        if not self.shell:
            raise RuntimeError("SSH shell 未连接")
        while self.shell.recv_ready():
            self.shell.recv(65535)

        self.shell.send(command + '\n')
        raw_output = self._read_until_prompt(initial_wait=wait)

        lines = raw_output.splitlines()
        if lines and command.strip() in lines[0]:
            lines = lines[1:]
        return '\n'.join(lines)

    # ── 模式切换 ──────────────────────────────────────────────────────

    def enter_enable_mode(self, password: str = "") -> str:
        """进入 enable 模式"""
        if not self.shell:
            raise RuntimeError("SSH shell 未连接")

        # 清空待读数据
        while self.shell.recv_ready():
            self.shell.recv(65535)

        # 发送 enable，等待密码提示或 CLI 提示符
        self.shell.send("enable\n")
        output = self._read_until_prompt(
            initial_wait=1.5,
            extra_patterns=self._PASSWORD_PATTERNS,
        )

        if "assword" in output.lower():
            # 设备要求输入 enable 密码
            time.sleep(0.3)
            self.shell.send((password or "") + "\n")
            output = self._read_until_prompt(initial_wait=1.5)

        if re.search(r'[\w\-]+#\s*$', output.rstrip()):
            return output
        if "denied" in output.lower() or "failed" in output.lower():
            probe = self.send_command("show date", wait=2.0)
            if re.search(r'[\w\-]+#\s*$', probe.rstrip()):
                return probe
            raise RuntimeError(f"Enable 认证失败: {output.strip()[:200]}")
        return output

    # ── 命令执行 ──────────────────────────────────────────────────────

    def execute_show_commands(self, commands: List[str]) -> List[Dict[str, str]]:
        """在 enable 模式下批量执行 show/验证类命令"""
        results = []
        self.enter_enable_mode()
        for cmd in commands:
            cmd = cmd.strip()
            if not cmd:
                continue
            output = self.send_command(cmd, wait=3.0)
            status = "error" if self._has_cli_error(output) else "success"
            results.append({
                "command": cmd,
                "output": output.strip(),
                "status": status,
            })
        return results

    def execute_config_commands(self, commands: List[str]) -> List[Dict[str, str]]:
        """在 config 模式下批量执行配置命令"""
        results = []
        self.enter_enable_mode()
        self.send_command("config terminal", wait=2.0)
        for cmd in commands:
            cmd = cmd.strip()
            if not cmd:
                continue
            output = self.send_command(cmd, wait=3.0)
            status = "error" if self._has_cli_error(output) else "success"
            results.append({
                "command": cmd,
                "output": output.strip(),
                "status": status,
            })
        self.send_command("exit")
        return results

    @staticmethod
    def _has_cli_error(output: str) -> bool:
        """检测 CLI 输出中的错误关键字（收口到共享 device_errors，独立加载时本地回退）。"""
        if _has_cli_error_shared is not None:
            return _has_cli_error_shared(output)
        # 本地回退：与 device_errors.DEVICE_CLI_ERROR_MARKERS + has_caret_error 同义。
        text = output.strip().lower()
        if any(kw in text for kw in _CLI_ERROR_MARKERS):
            return True
        for line in output.strip().splitlines():
            s = line.strip()
            if s == "^" or (len(s) <= 3 and "^" in s):
                return True
        return False


def create_ssh_client_from_env() -> APVSSHClient:
    """从环境变量创建 SSH 客户端。

    环境变量:
        APV_DEVICE_IP: 设备 IP（默认取拓扑中的 APV0: 172.16.34.70）
        APV_USERNAME:  SSH 用户名（默认 admin）
        APV_PASSWORD:  SSH 密码（默认 admin）
        APV_SSH_PORT:  SSH 端口（默认 22）
    """
    return APVSSHClient(
        host=os.environ.get("APV_DEVICE_IP", "172.16.34.70"),
        username=os.environ.get("APV_USERNAME", "admin"),
        password=os.environ.get("APV_PASSWORD", "admin"),
        port=int(os.environ.get("APV_SSH_PORT", "22")),
    )
