"""正确跑法:deliver 合并 xlsx 一次 + run 一次,框架跑全部 26 case,
然后从该 run 的 staging 目录逐个读 case 子日志判 verdict。不走 ist-core agent。
"""
import json, re, time
from pathlib import Path
from main.ist_core.runner import _ensure_env
_ensure_env()
from main.case_compiler.config import get_config
from main.case_compiler.device_mcp_client import FrameworkMCPClient

XLSX = "workspace/outputs/yzg/case.xlsx"
cases = json.load(open("/tmp/yzg_cases.json"))
aids = [c["autoid"] for c in cases]
RUN_AID = aids[0]  # 用第一个 autoid 作为 deliver/run 的代表

cfg = get_config()
module = cfg.staging_module.strip()
build = cfg.build.strip()
print(f"module={module} build={build} 代表autoid={RUN_AID} 共{len(aids)}case", flush=True)

with FrameworkMCPClient() as c:
    print(f"[{time.strftime('%H:%M:%S')}] deliver 合并 xlsx...", flush=True)
    dres = c.deliver(module, RUN_AID, XLSX)
    if dres.get("error"):
        print(f"deliver 失败: {dres.get('error')}", flush=True); raise SystemExit(1)
    print(f"[{time.strftime('%H:%M:%S')}] deliver ok, run 一次(跑全部26 case,等≤40min)...", flush=True)
    # case_ids 传全部 aids,max_s 给足
    run = c.run_and_wait(module, RUN_AID, build, aids, poll_s=15, max_s=2400)
    print(f"[{time.strftime('%H:%M:%S')}] run 返回: task_id={run.get('task_id')} state={(run.get('status') or {}).get('state')} err={run.get('error')}", flush=True)
    tid = run.get("task_id", "")

    # 定位本次 run 的 staging 目录(用 task_id 或最新)
    i,o,e = c._c.exec_command(
        f"ls -dt /home/test/apv_src/report/*/*/ist_staging_sdns/{RUN_AID} 2>/dev/null | head -1", timeout=30)
    base = o.read().decode("utf-8","replace").strip()
    print(f"staging: {base}", flush=True)
    casedir = f"{base}/test_xlsx/case.xlsx"
    # 列出实际跑出的 case 子目录
    i,o,e = c._c.exec_command(f"ls {casedir}/ 2>/dev/null | grep '^20360'", timeout=30)
    ran = [x for x in o.read().decode("utf-8","replace").split() if x]
    print(f"实际跑出 {len(ran)}/{len(aids)} 个 case 子目录", flush=True)

    # 逐个读 case 子日志判 verdict(Success/Fail Num)
    results = []
    for aid in aids:
        rec = {"autoid": aid, "verdict": "no_log", "passed": 0, "failed": 0, "tail": ""}
        if aid in ran:
            i,o,e = c._c.exec_command(f"cat {casedir}/{aid}/{aid}.txt 2>/dev/null", timeout=30)
            txt = o.read().decode("utf-8","replace")
            # 框架真实裁决:统计 Success Num / Fail Num
            sn = len(re.findall(r"#### Success Num", txt))
            fn = len(re.findall(r"#### Fail Num", txt))
            rec["passed"]=sn; rec["failed"]=fn
            if "######      FAIL" in txt or fn>0: rec["verdict"]="fail"
            elif "######      PASS" in txt or (sn>0 and fn==0): rec["verdict"]="pass"
            else: rec["verdict"]="unknown"
            # 关键裁决行
            keylines=[l.strip() for l in txt.splitlines() if re.search(r"(Success|Fail) Num|fail to find|TypeError|Error",l)]
            rec["tail"]="\n".join(keylines[-6:])
        results.append(rec)
        print(f"  {aid[-9:]} verdict={rec['verdict']} (S={rec['passed']} F={rec['failed']})", flush=True)

json.dump(results, open("/tmp/yzg_run2_results.json","w"), ensure_ascii=False, indent=2)
from collections import Counter
print(f"\n=== 汇总 ===\nverdict: {dict(Counter(r['verdict'] for r in results))}", flush=True)
print("存 /tmp/yzg_run2_results.json", flush=True)
