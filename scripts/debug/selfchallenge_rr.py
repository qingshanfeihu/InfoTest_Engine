"""自我挑战实验:还原"当年发现 rr 计数器断言问题"的真实情景,看 agent 能否自主走通
   调查→改写→上机验证 闭环。MiMo vs DeepSeek 对比。

不走 case_compiler 管线。直接给主 agent 一个真实脆弱用例 + 任务,给它全套工具
(dev_ssh 探命令 / run_python 写分析脚本 / grep 手册 / dev_run_case 上机验证),
看它能否复现人当年的根因分析路径——且全程无人告诉它"答案是 show statistics sdns pool 分布断言"。

用法:
  IST_JUMPHOST_PASS=xxx .venv/bin/python -m scripts.debug.selfchallenge_rr --model mimo
  IST_JUMPHOST_PASS=xxx .venv/bin/python -m scripts.debug.selfchallenge_rr --model deepseek
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

# ── 还原的"犯罪现场":当年那个脆弱用例的真实信息(不含答案)─────────────────
# 真实出处:knowledge/framework/mirror/smoke_test/sdns/host_persistence/205271757988589359.py
# 脆弱断言:dig 15 次,每次断言回的 IP 等于第一次的 IP(逐次裸 IP 字面比对)。
# 我们不告诉 agent "三宗罪""分布定律""show statistics sdns pool"——让它自己查出来。

_FRAGILE_CASE = """\
被测用例(autoid 205271757988589359,SDNS rr 轮询/会话保持类),核心断言逻辑是:

    APV0.cmd_config('sdns host method "www.zyq.com" "rr"')   # rr 轮询算法
    ... 配置 pool1(成员 r1/r2/r3/r61/r62/r63)+ pool2(成员 r4/r5/r6/r64/r65/r66)
    APV0.cmd_config('sdns host pool www.zyq.com pool1')
    APV0.cmd_config('sdns host pool www.zyq.com pool2')
    APV0.cmd_config('sdns listener 172.16.34.70')

    # 第一次 dig,记下回的 IP
    init_ip = dig @172.16.34.70 www.zyq.com A
    # 然后连续 dig 15 次,每次都断言:这次回的 IP == 第一次回的 IP
    for i in range(15):
        a = dig @172.16.34.70 www.zyq.com A
        check_point.found(a, init_ip)    # 要求 15 次都命中同一个 IP
"""

_TASK_PROMPT = """\
你是测试自动化工程师。下面这个已自动化的 SDNS 测试用例,在目标设备(build 10.5.0.568)上
**上机不稳定(flaky)**——有时过有时不过,同样的用例反复跑结果会变。

{fragile}

# 你的任务
搞清楚这个断言为什么 flaky,把它改成**稳定**的断言(每次跑都给出确定裁决),并上机验证你改对了。

# 纪律(必须遵守)
1. **看到才能断言**:断言的期望值必须有依据——来自用例作者意图、产品手册规范、或框架先例,
   绝不能"跑一次看设备输出什么就照着写"(那会把偶然结果固化成期望)。
2. **查证据,别猜**:CLI 命令语法以产品手册为准。设备命令手册在
   knowledge/data/markdown/product/*cli__part*.md,先 grep 核对再用。
   设备可直连排查:用 dev_ssh(show 命令只读探查 / config 安全子集)。
3. **上机是唯一裁判**:改完用 dev_run_case 真机跑,pass/fail 设备说了算,不是你自评。
   fail 了就看日志诊断、改、再跑,直到稳定 pass 或你能确证这是产品缺陷。

# 可用手段
- grep/read 手册和先例语料(knowledge/ 下)
- dev_ssh 直连设备 172.16.34.70 发单条命令探查回显/语法
- run_python 写一次性分析脚本
- compile_emit 产出 case.xlsx;dev_run_case 把它上机跑
- 设备 build/topology 已配好,APV_0=172.16.34.70

# 推进纪律(重要)
- 调查是手段不是目的——**交付物是一个上机验证过的稳定 case.xlsx**,不是一份分析报告。
- 一旦你诊断出根因(通常几次 grep/读手册就够),**立刻**动手:产出修好的 xlsx → dev_run_case 上机。
- 别反复探查同一批文件。想清楚了就动手;上机 fail 比继续空想更有价值——失败日志会告诉你下一步。
- 你必须至少调用一次 dev_run_case 上机验证你的修复;没上机过就不算完成。

先简述根因(1-2 段),然后直接产出 xlsx 并上机。开始。
"""


def _build_model(which: str):
    """按 which 构造模型:mimo(默认端点) 或 deepseek(切 base_url+key+model)。"""
    if which == "deepseek":
        os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com"
        os.environ["OPENAI_API_KEY"] = os.environ.get("DEEPSEEK_API_KEY", "")
        os.environ["IST_MODEL"] = "deepseek-v4-pro"
        os.environ["IST_OPUS_MODEL"] = "deepseek-v4-pro"
        os.environ["IST_HAIKU_MODEL"] = "deepseek-v4-flash"
    # mimo: 用 environment 默认(token-plan MiMo)
    from main.ist_core.agents._llm import build_agent_chat_model
    return build_agent_chat_model()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["mimo", "deepseek"], default="mimo")
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--recursion-limit", type=int, default=400,
                    help="graph node 预算。deepagents 每次工具调用≈3-4 node,"
                         "调查+改+多次上机要 ~100+ 工具调用,给足预算别中途掐断。")
    args = ap.parse_args()

    from main.langchain_env import langchain_load_dotenv_if_present
    langchain_load_dotenv_if_present()

    model = _build_model(args.model)
    from main.ist_core.agents.main_agent import build_main_agent
    agent = build_main_agent(model=model)

    prompt = _TASK_PROMPT.format(fragile=_FRAGILE_CASE)
    from langchain_core.messages import HumanMessage

    t0 = time.time()
    tool_calls = []
    final_text = ""
    state = {"messages": [HumanMessage(content=prompt)]}
    cfg = {"recursion_limit": args.recursion_limit, "configurable": {"thread_id": f"selfchallenge_{args.model}_{int(time.time())}"}}

    print(f"=== self-challenge rr | model={args.model} | start ===", flush=True)
    try:
        for chunk in agent.stream(state, cfg, stream_mode="values"):
            msgs = chunk.get("messages", [])
            if msgs:
                last = msgs[-1]
                # 记录工具调用
                tcs = getattr(last, "tool_calls", None) or []
                for tc in tcs:
                    name = tc.get("name", "")
                    tool_calls.append(name)
                    print(f"  [tool] {name}({str(tc.get('args',{}))[:120]})", flush=True)
                if getattr(last, "type", "") == "ai" and isinstance(last.content, str) and last.content.strip():
                    final_text = last.content
    except Exception as e:
        print(f"  [error] {type(e).__name__}: {str(e)[:300]}", flush=True)

    elapsed = time.time() - t0
    print(f"\n=== DONE model={args.model} ===", flush=True)
    print(f"elapsed={elapsed:.0f}s  total_tool_calls={len(tool_calls)}", flush=True)
    from collections import Counter
    print(f"tool histogram: {dict(Counter(tool_calls))}", flush=True)
    print(f"dev_run_case calls (上机次数): {tool_calls.count('dev_run_case')}", flush=True)
    print(f"\n--- agent final message (tail) ---\n{final_text[-1500:]}", flush=True)


if __name__ == "__main__":
    main()
