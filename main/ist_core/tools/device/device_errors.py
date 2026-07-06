"""设备 CLI 错误识别 —— 全仓唯一权威。

历史上 `apv_ssh_client._has_cli_error` / `restapi` 内联检测 / `fail_attribution._G_MARKERS`
各自维护一套关键字表与 caret 检测，措辞漂移、行为容易回退。本模块把"设备回显是否
含 CLI 报错"的判定收口到一处，所有调用方共享同一组 marker 与孤立 `^` 行检测。

在历史 marker 之外只新增一条 "failed to execute"——设备的**统一失败裁决**：
这台设备对任何执行失败的命令都回一行 "Failed to execute the command"。实测各类
具体报错（"Query type not support."、"Domain name or network or query type not found."
…）**均伴随此句**，故认这条通用裁决即可，不去穷举各业务命令的具体措辞——
穷举既脆（换固件/特性即失效），又是把领域知识写死进判错函数（项目红线反对）。
另：43dcabe5 把孤立 `^` 包装出的 "% Invalid input" 已被历史 marker "% invalid" 子串覆盖；
孤立 `^` 由 has_caret_error 覆盖。均无需单列。

只依赖标准库（re），不得引入 langchain 等重依赖。
"""

from __future__ import annotations

import re

# 全小写子串 marker。命中任一即判为 CLI 错误。
DEVICE_CLI_ERROR_MARKERS: tuple[str, ...] = (
    # —— 历史 marker（保留，行为不回退）——
    "% invalid",
    "% error",
    "% unknown",
    "% unrecognized",
    "syntax error",
    "invalid input",
    "command not found",
    # —— 新增：只认设备「统一失败裁决」这一条通用信号 ——
    # 任何命令执行失败设备都回 "Failed to execute the command"；实测 "Query type not
    # support."、"Domain name or network or query type not found." 等具体原因均伴随此句。
    # 故认这条通用裁决，不穷举各业务命令的具体措辞（穷举既脆，又把领域知识写死进判错函数）。
    "failed to execute",
)

# 孤立 caret 行：长度 <=3 且含 `^`（含恰好等于 "^" 的行）。
_CARET_RE = re.compile(r"\^")


def has_caret_error(text: str) -> bool:
    """检测输出里是否存在孤立 `^` 报错行。

    设备 CLI 在命令语法出错时会在下一行用 `^` 指向出错位置（有时带少量空格/字符）。
    收口"孤立 ^ 行 / 长度<=3 且含 ^ 的短行"检测。
    """
    if not text:
        return False
    for line in text.splitlines():
        s = line.strip()
        if s == "^" or (len(s) <= 3 and _CARET_RE.search(s)):
            return True
    return False


def has_cli_error(text: str) -> bool:
    """text.lower() 命中任一 marker（子串）或存在孤立 ^ 行 → True。"""
    if not text:
        return False
    lower = text.lower()
    if any(marker in lower for marker in DEVICE_CLI_ERROR_MARKERS):
        return True
    return has_caret_error(text)
