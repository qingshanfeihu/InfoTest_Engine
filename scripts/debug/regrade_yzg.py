"""直接调 ist_compile_grade fork 对 26 个 yzg case 重新判分,拿完整判分理由。
不走主 agent(避免 ask_user 空转)、不经 CLISink(直接拿 fork 返回字符串)。
并发跑(grade 是纯本地判分,无设备交互,可并发)。
"""
import json, concurrent.futures as cf, time
from main.ist_core.runner import _ensure_env
_ensure_env()
from main.ist_core.skills.loader import execute_fork_skill

mani = json.load(open("workspace/outputs/yzg/manifest.json"))
ROOT = "/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine"

def build_brief(c):
    aid = c["autoid"]
    title = (c.get("title") or "").replace("\n", " ")
    intents = c.get("step_intents") or []
    need = "; ".join((s.get("desc","")+" 期望:"+str(s.get("expected","") or "无")).replace("\n"," ") for s in intents)
    xlsx = f"{ROOT}/workspace/outputs/{aid}/case.xlsx"
    return (f"xlsx_path={xlsx}\n"
            f"原始需求=case autoid={aid}，标题「{title}」，步骤意图：{need}")

def run_one(c):
    aid = c["autoid"]
    t0 = time.time()
    try:
        out = execute_fork_skill("ist_compile_grade", build_brief(c))
    except Exception as e:
        out = f"ERROR: {e}"
    return {"autoid": aid, "elapsed": round(time.time()-t0,1), "output": out}

cases = mani["cases"]
print(f"对 {len(cases)} 个 case 并发 grade(并发度6)...", flush=True)
results = []
with cf.ThreadPoolExecutor(max_workers=6) as ex:
    futs = {ex.submit(run_one, c): c["autoid"] for c in cases}
    done = 0
    for fut in cf.as_completed(futs):
        r = fut.result(); results.append(r); done += 1
        # 抽 PASS/CUT
        o = r["output"]
        verdict = "PASS" if ("PASS" in o[:150] and "CUT" not in o[:150]) else ("CUT" if "CUT" in o[:150] else "?")
        print(f"[{done}/{len(cases)}] {r['autoid'][-9:]} {verdict} ({r['elapsed']}s)", flush=True)

# 按 autoid 排序存
results.sort(key=lambda x: x["autoid"])
json.dump(results, open("/tmp/yzg_grade2.json","w"), ensure_ascii=False, indent=2)
from collections import Counter
vc = Counter("PASS" if ("PASS" in r["output"][:150] and "CUT" not in r["output"][:150])
             else ("CUT" if "CUT" in r["output"][:150] else "?") for r in results)
print(f"\n=== 汇总: {dict(vc)} ===", flush=True)
print("完整判分理由存 /tmp/yzg_grade2.json", flush=True)
