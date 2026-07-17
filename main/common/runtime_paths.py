# -*- coding: utf-8 -*-
"""runtime/ 台账路径的单一取径点(pytest 隔离,团队审计 4-3-② 补做批)。

实证三处测试污染生产台账:ask_user_answers.jsonl 混入 2426 条 ts=0 fixture 记录、
emit_stats.jsonl 单轮 +103 行、k_signals.jsonl +19 行——并行真编译取证时被干扰。
本模块提供 `runtime_path()`:生产=repo/runtime/<parts>;pytest 运行期
(PYTEST_CURRENT_TEST,pytest 自动注入)=系统 tmp 的 ist_pytest_runtime.<pid>/<parts>。

纪律:**台账的读写两侧必须同经本函数取径**——「先问后落」类凭证门(如
compile_user_decision 读 ask_user_answers.jsonl)与写入者在 pytest 下指向同一
tmp,门语义在测试内保持;只改写侧会让门读空台账假拒。显式断言日志内容的测试
经同函数取径即可(tmp 按 pid 分目录,跨 run 基本隔离)。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def runtime_path(*parts: str) -> Path:
    """runtime/ 下的台账/流水路径;pytest 运行期改写 tmp 同名结构(不建目录,
    建目录责任在写入者——读者对不存在路径的语义保持各自既有行为)。"""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return Path(tempfile.gettempdir()).joinpath(
            f"ist_pytest_runtime.{os.getpid()}", *parts)
    return _REPO_ROOT.joinpath("runtime", *parts)
