"""单独调一个 draft fork,dump 它内部的完整往返序列(每轮 reasoning + tool_call + tool 返回)。
目的:看清"draft 慢的十几次 LLM 往返"具体每次在干什么,反推哪些可靠喂数据省掉。
不走主 agent,直接 execute_fork_skill 但改造成能拿到完整 messages。
"""
import json, sys, time
from main.ist_core.runner import _ensure_env
_ensure_env()

from pathlib import Path
from main.ist_core.skills.loader import (
    _SKILLS_DIR, _parse_skill_md, _render_skill_body, get_subagent_runnable,
)
from langchain_core.messages import HumanMessage

# 选一个慢 case:676654 (zone forward 递归,8条命令,之前 11:10 才落盘)
AID = sys.argv[1] if len(sys.argv) > 1 else "203601753067676654"
mani = json.load(open("workspace/outputs/yzg/manifest.json"))
case = next((c for c in mani["cases"] if str(c["autoid"]) == AID), None)
if not case:
    # 从归档找
    for m in Path(".").glob("workspace/.outputs_archive*/yzg/manifest.json"):
        d = json.load(open(m)); case = next((c for c in d["cases"] if str(c["autoid"])==AID), None)
        if case: break
ROOT = "/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine"
title = (case.get("title") or "").replace("\n"," ")
intents = case.get("step_intents") or []
need = "; ".join((s.get("desc","")+" 期望:"+str(s.get("expected","") or "无")).replace("\n"," ") for s in intents)
brief = (f"待编译用例 autoid={AID}，标题「{title}」\n"
         f"模块=sdns；目标产品+版本=APV 10.5，手册 glob=10.5_cli__part*.md\n"
         f"步骤意图：{need}\n"
         f"这是新编译(非重做)。生成 case.xlsx 草稿。")

print(f"=== 跑 draft fork: {AID} ===", flush=True)
print(f"brief:\n{brief}\n{'='*60}", flush=True)

# 直接构造 draft fork 的 runnable 并 invoke,拿完整 messages
parsed = _parse_skill_md(_SKILLS_DIR / "ist_compile_draft" / "SKILL.md")
agent_name = parsed["frontmatter"]["agent"]
runnable = get_subagent_runnable(agent_name)
rendered = _render_skill_body(parsed["body"], brief)

t0 = time.time()
result = runnable.invoke({"messages": [HumanMessage(content=rendered)]})
elapsed = time.time() - t0
msgs = result.get("messages", [])

# 逐轮 dump:每个 AIMessage 的 reasoning + tool_calls,每个 ToolMessage 的返回摘要
print(f"\n=== 完整往返({len(msgs)} 消息, 耗时 {elapsed:.0f}s)===", flush=True)
round_n = 0
for m in msgs:
    t = type(m).__name__
    if t == "AIMessage":
        round_n += 1
        ak = getattr(m, "additional_kwargs", {}) or {}
        rc = (ak.get("reasoning_content") or "").strip()
        ct = m.content if isinstance(m.content, str) else " ".join(b.get("text","") for b in m.content if isinstance(b,dict))
        tcs = [(tc.get("name"), tc.get("args")) for tc in (getattr(m,"tool_calls",None) or [])]
        print(f"\n--- 往返#{round_n} ---", flush=True)
        if rc: print(f"  [reasoning {len(rc)}字]: {rc[:300]}", flush=True)
        if ct.strip(): print(f"  [text]: {ct[:200]}", flush=True)
        for name, args in tcs:
            print(f"  [调用] {name}({json.dumps(args, ensure_ascii=False)[:160]})", flush=True)
    elif t == "ToolMessage":
        out = m.content if isinstance(m.content,str) else str(m.content)
        print(f"  [返回] {out[:200]}", flush=True)

json.dump([{"type":type(m).__name__,
            "reasoning":(getattr(m,"additional_kwargs",{}) or {}).get("reasoning_content",""),
            "content": m.content if isinstance(m.content,str) else str(m.content),
            "tool_calls":[(tc.get("name"),tc.get("args")) for tc in (getattr(m,"tool_calls",None) or [])]}
           for m in msgs], open(f"/tmp/draft_trace_{AID}.json","w"), ensure_ascii=False, indent=2)
print(f"\n=== 完整记录存 /tmp/draft_trace_{AID}.json,往返{round_n}次,耗时{elapsed:.0f}s ===", flush=True)
