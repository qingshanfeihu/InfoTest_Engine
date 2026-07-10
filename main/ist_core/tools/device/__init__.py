"""Device interaction tools: dev_ssh / dev_rest（单命令）+ dev_run_case（整 case 上机验证）。"""

from main.ist_core.tools.device.ssh import dev_ssh
from main.ist_core.tools.device.restapi import dev_rest
from main.ist_core.tools.device.run_case import dev_run_case, dev_probe, dev_help, dev_init_device
from main.ist_core.tools.device.emit_xlsx_tool import compile_emit, compile_emit_merged
from main.ist_core.tools.device.verifiability_tool import compile_check_verifiability, compile_user_decision
# V8 验收切换(2026-07-10):出口指向 V8;V6 engine_tool 保留在盘待验收后删除
from main.ist_core.compile_engine_v8.engine_tool import compile_engine_run
from main.ist_core.tools.device.batch_tools import compile_fanout, dev_run_batch, dev_run_batch_digest
from main.ist_core.tools.device.compile_prep import compile_prep
from main.ist_core.tools.device.fail_attribution import compile_attribute, submit_attribution
from main.ist_core.tools.device.ask_panel import submit_ask_panel
from main.ist_core.tools.device.precedent_tools import compile_writeback
from main.ist_core.tools.device.checker_tool import compile_expected_hits
from main.ist_core.tools.device.runtime_fill_tools import compile_runtime_slots, compile_runtime_fill
# 注:origin/main 引用了 qa_smoke_test 但其客户端模块 smoke_test.py 从未提交(只有 MCP 服务端
# smoke_test_run 在 scripts/MCP/),是远程一个残提交。此处不引入死 import;待该文件补齐再接。

__all__ = ["dev_ssh", "dev_rest", "dev_run_case", "dev_probe", "dev_help", "dev_init_device",
           "compile_emit", "compile_emit_merged", "compile_check_verifiability", "compile_user_decision",
           "compile_engine_run",
           "compile_fanout", "dev_run_batch", "dev_run_batch_digest",
           "compile_prep", "compile_writeback", "compile_expected_hits", "compile_attribute", "submit_attribution",
           "submit_ask_panel",
           "compile_runtime_slots", "compile_runtime_fill"]
