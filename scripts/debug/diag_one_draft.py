"""诊断单个 draft fork 的完整轨迹：每个工具调用的 name+args+结果片段 + 最终输出。

回答"draft 实际在干嘛、为啥不用 footprint、grep 了啥"。用当前 agent 配置跑一个真 case。

用法：python -m scripts.debug.diag_one_draft <manifest.json> [autoid]
"""
import json
import sys
from pathlib import Path

from main.langchain_env import langchain_load_dotenv_if_present


def main():
    langchain_load_dotenv_if_present()
    mp = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("workspace/outputs/yzg/manifest.json")
    manifest = json.loads(mp.read_text(encoding="utf-8"))
    cases = manifest.get("cases", [])
    want = sys.argv[2] if len(sys.argv) > 2 else None
    case = next((c for c in cases if str(c.get("autoid")) == want), None) if want else cases[0]
    print(f"诊断 case autoid={case.get('autoid')} 标题={case.get('title')}", flush=True)

    from main.ist_core.tools.device.compile_pipeline import _preretrieve_precedent, _build_case_brief
    from main.ist_core.skills.loader import (
        get_subagent_runnable, _parse_skill_md, _render_skill_body, _SKILLS_DIR)
    from langchain_core.messages import HumanMessage

    pt = _preretrieve_precedent(case)
    print(f"预检索先例长度={len(pt)} 含sdns_on={'sdns on' in pt.lower()}", flush=True)
    brief = _build_case_brief(case, product_version="10.5",
                              manual_glob="10.5_cli__part*.md", groups={}, precedent_text=pt)

    # 渲染 draft skill body（与 execute_fork_skill 同路径）
    parsed = _parse_skill_md(_SKILLS_DIR / "ist_draft_v3" / "SKILL.md")
    body = _render_skill_body(parsed["body"], brief)

    import time
    runnable = get_subagent_runnable("ist-draft-v3")
    t0 = time.time()
    result = runnable.invoke({"messages": [HumanMessage(content=body)]})
    elapsed = time.time() - t0

    msgs = result.get("messages", [])
    print(f"\n=== 完整轨迹（{len(msgs)} 条消息，耗时 {elapsed:.0f}s）===", flush=True)
    for i, m in enumerate(msgs):
        mtype = getattr(m, "type", "?")
        tcs = getattr(m, "tool_calls", None) or []
        if tcs:
            for tc in tcs:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "?")
                args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                arg_s = json.dumps(args, ensure_ascii=False)[:160]
                print(f"  [{i}] TOOL_CALL {name}({arg_s})", flush=True)
        elif mtype == "tool":
            content = str(getattr(m, "content", ""))[:180].replace("\n", " ")
            print(f"  [{i}] tool_result: {content}", flush=True)
        elif mtype == "ai":
            content = str(getattr(m, "content", ""))[:200].replace("\n", " ")
            if content.strip():
                print(f"  [{i}] AI说: {content}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
