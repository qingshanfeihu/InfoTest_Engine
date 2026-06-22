"""Device interaction tools: qa_ssh / qa_restapi（单命令）+ qa_run_case（整 case 上机验证）。"""

from main.ist_core.tools.device.ssh import qa_ssh
from main.ist_core.tools.device.restapi import qa_restapi
from main.ist_core.tools.device.run_case import qa_run_case, qa_probe_show
from main.ist_core.tools.device.emit_xlsx_tool import qa_emit_xlsx, qa_emit_xlsx_merged
from main.ist_core.tools.device.batch_tools import qa_compile_fanout, qa_run_batch
from main.ist_core.tools.device.compile_prep import qa_compile_prep
from main.ist_core.tools.device.intent_cluster import qa_cluster_intents
from main.ist_core.tools.device.fail_attribution import qa_attribute_fail
from main.ist_core.tools.device.compile_pipeline import qa_compile_pipeline
from main.ist_core.tools.device.runtime_fill_tools import qa_list_runtime_slots, qa_fill_runtime
# 注:origin/main 引用了 qa_smoke_test 但其客户端模块 smoke_test.py 从未提交(只有 MCP 服务端
# smoke_test_run 在 MCP_Server/),是远程一个残提交。此处不引入死 import;待该文件补齐再接。

__all__ = ["qa_ssh", "qa_restapi", "qa_run_case", "qa_probe_show", "qa_emit_xlsx",
           "qa_emit_xlsx_merged", "qa_compile_fanout", "qa_run_batch", "qa_compile_prep",
           "qa_cluster_intents", "qa_attribute_fail", "qa_compile_pipeline",
           "qa_list_runtime_slots", "qa_fill_runtime"]
