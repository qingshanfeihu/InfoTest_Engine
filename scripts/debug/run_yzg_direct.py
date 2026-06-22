"""直连跳转机框架跑合并后的 yzg excel——不走 ist-core agent,自己调 FrameworkMCPClient。
照搬 qa_run_batch 的串行 deliver+run_and_wait 逻辑,采集每个 case 的框架真实裁决。
"""
import json
import re
import time
from pathlib import Path

from main.ist_core.runner import _ensure_env
_ensure_env()

from main.case_compiler.config import get_config
from main.case_compiler.device_mcp_client import FrameworkMCPClient

XLSX = "workspace/outputs/yzg/case.xlsx"
AUTOIDS = [
    "203601753067655154","203601753067655173","203601753067655188","203601753067655203",
    "203601753067655218","203601753067655233","203601753067655248","203601753067655262",
    "203601753067655276","203601753067655290","203601753067667986","203601753067668000",
    "203601753067668015","203601753067668030","203601753067668044","203601753067668059",
    "203601753067676594","203601753067676612","203601753067676626","203601753067676640",
    "203601753067676654","203601753067676668","203601753067681539","203601753067681556",
    "203601753067681571","203601753067681588",
]

cfg = get_config()
module = cfg.staging_module.strip()
build = cfg.build.strip()
print(f"module={module} build={build} xlsx={XLSX} cases={len(AUTOIDS)}", flush=True)

results = []
t_start = time.time()
with FrameworkMCPClient() as client:
    for i, autoid in enumerate(AUTOIDS, 1):
        rec = {"autoid": autoid, "verdict": "error", "task_id": "", "causality": "", "detail_tail": ""}
        t0 = time.time()
        try:
            dres = client.deliver(module, autoid, XLSX)
            if dres.get("error"):
                rec["detail_tail"] = f"deliver失败: {dres.get('error')}"
                print(f"[{i}/{len(AUTOIDS)}] {autoid} deliver失败: {dres.get('error')}", flush=True)
                results.append(rec); continue
            run = client.run_and_wait(module, autoid, build, [autoid], max_s=600)
            if run.get("busy") or run.get("error") == "device_busy":
                rec["verdict"] = "busy"; rec["detail_tail"] = run.get("message", "")
            elif run.get("error"):
                rec["detail_tail"] = f"运行失败: {run.get('error')}"
            else:
                rec["verdict"] = (run.get("results") or {}).get(autoid) or run.get("result") or "unknown"
                rec["task_id"] = run.get("task_id", "")
                detail = client.fetch_case_detail(autoid)
                causality = [ln.rstrip() for ln in (detail or "").splitlines()
                             if re.search(r"(Success|Fail)\s*Num|fail to find|successed to find", ln, re.I)]
                rec["causality"] = "\n".join(causality[-12:]) if causality else ""
                rec["detail_tail"] = (detail or "")[-1500:]
        except Exception as exc:
            rec["detail_tail"] = f"上机异常: {exc}"
        dt = time.time() - t0
        print(f"[{i}/{len(AUTOIDS)}] {autoid} verdict={rec['verdict']} ({dt:.0f}s) task={rec['task_id']}", flush=True)
        if rec["causality"]:
            print(f"    裁决: {rec['causality'][:200]}", flush=True)
        results.append(rec)

# 汇总
json.dump(results, open("/tmp/yzg_run_results.json", "w"), ensure_ascii=False, indent=2)
from collections import Counter
vc = Counter(r["verdict"] for r in results)
print(f"\n=== 汇总(总耗时 {(time.time()-t_start)/60:.1f}min) ===", flush=True)
print(f"verdict 分布: {dict(vc)}", flush=True)
print(f"结果存 /tmp/yzg_run_results.json", flush=True)
