"""一次性诊断脚本:stream 模式跑单脑图,实时记录工具调用序列。
不改产品代码;用 InMemorySaver 避死锁;CLISink 把每步 tool_call 写 stdout。
目的:看 agent 在 ist_compile 流程里到底怎么调度(fanout? 逐条? run/grade/merged?)。
"""
import os, sys
os.environ["IST_NON_INTERACTIVE"] = "1"

# 加载 environment 文件(infotest 入口靠 _ensure_env 做,直接 python -m 要自己来)
from main.ist_core.runner import _ensure_env
_ensure_env()

from langgraph.checkpoint.memory import InMemorySaver
from main.ist_core.runner import run_single

query = (
    "请将 /Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/"
    "Project/InfoTest_Engine/workspace/inputs/automatic_case/yzg.txt "
    "这个脑图编译成 10.5 的自动化 excel 文件"
)

result = run_single(
    query,
    task_type="QA",
    thread_id="diag-yzg-compile",
    stream=True,          # 走 CLISink,实时打 tool_call
    verbose=True,
    checkpointer=InMemorySaver(),
)
print("\n=== FINAL ===")
print((result or {}).get("final_answer") or "（无回答）")
