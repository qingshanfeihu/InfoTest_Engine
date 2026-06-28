"""footprint 预检索 A/B：同一脑图跑两轮（prefetch OFF→ON），一键产出「LLM 调用/查找是否
明显减少 + 质量(done 数)不降」的 realized 对比。

这是计划「检查 LLM 调用次数和查找是否有明显减少但质量不降」的最后一步——把手动两跑+对眼
收敛成一条命令。**会跑真编译（真实 LLM 往返）**，云盘环境会卡，请在正常 infotest 环境跑。

用法：
    python -m scripts.debug.measure_prefetch_ab <mindmap_path> <product_version> [out_name]
例：
    python -m scripts.debug.measure_prefetch_ab workspace/inputs/dongkl.txt 10.5

输出：draft/总 LLM 往返、kb_footprint/dev_probe 次数的 before→after+降幅，以及 done 数对比。
原始 per-fork 明细见 runtime/logs/fork_status.jsonl。建议同时关流式防网关空 chunk：
    IST_LLM_STREAMING=0 python -m scripts.debug.measure_prefetch_ab ...
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


def _run(mindmap: str, version: str, out_name: str, *, enabled: bool):
    """跑一轮 _run_pipeline，返回 (observability_total dict, done_count)。"""
    os.environ["IST_FOOTPRINT_PREFETCH"] = "1" if enabled else "0"
    # flag 运行时读 env（_footprint_prefetch_enabled），故同进程翻转即生效。
    cp = importlib.import_module("main.ist_core.tools.device.compile_pipeline")
    res = cp._run_pipeline(mindmap, version, out_name,
                           draft_skill="ist_compile_draft", grade_skill="ist_compile_grade")
    obs = (res.get("observability") or {}).get("total", {})
    return obs, len(res.get("done", []))


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    mindmap, version = argv[1], argv[2]
    base = argv[3] if len(argv) > 3 else Path(mindmap).stem

    print(">>> [1/2] baseline：IST_FOOTPRINT_PREFETCH=0（关预检索）…", flush=True)
    ob_off, done_off = _run(mindmap, version, f"{base}_ab_off", enabled=False)
    print(">>> [2/2] optimized：IST_FOOTPRINT_PREFETCH=1（开预检索，默认）…", flush=True)
    ob_on, done_on = _run(mindmap, version, f"{base}_ab_on", enabled=True)

    cp = importlib.import_module("main.ist_core.tools.device.compile_pipeline")
    print("\n" + cp._format_observability_delta(ob_off, ob_on))
    verdict = "不降 ✅" if done_on >= done_off else "下降 ⚠（需查质量回归）"
    print(f"  done(质量,PASS 进 merge 的 case 数): {done_off} → {done_on}  ({verdict})")
    print("\n判读：kb_footprint / draft LLM 往返应明显下降，done 数应不降。"
          "\n（per-fork 明细见 runtime/logs/fork_status.jsonl 的 ai_rounds/tool_calls）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
