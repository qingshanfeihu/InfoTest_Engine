"""闸3:复核SELF_ECHO判定。把判为self-echo的机器断言点,
连同它命中的自配token + 同autoid真人gold真值,并排打出肉眼核。
证明:机器断言的是"自己配下去的值",真人gold是另一个(测试床真值)。"""
import json, sys
from pathlib import Path
ROOT = Path("/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine")
sys.path.insert(0, str(ROOT))
import scripts.debug.common_disease_31 as CD

def main():
    idx = json.load(open(ROOT/"runtime/logs/human_autoid_index.json"))
    import glob
    prods = sorted(set(x.split("/")[-2] for x in glob.glob(str(ROOT/"workspace/outputs/2030*/case.xlsx"))))
    shown = 0
    for aid in prods:
        hf = idx.get(aid)
        if not hf: continue
        mcps, mcfg = CD._machine_block(aid)
        gcps, gcfg = CD._human_block(aid, hf)
        if not mcps or not gcps: continue
        gkeys = CD._gold_keys(gcps)
        cfgtoks = CD._toks(mcfg)
        gold_vals = [g for _, g in gcps]
        se = [(f,g) for f,g in mcps if CD.classify(g, gkeys, cfgtoks)=="SELF_ECHO"]
        if not se: continue
        print(f"\n=== {aid} ({hf.split('/')[-2]}) self-echo {len(se)}点 ===")
        print(f"  真人gold真值: {gold_vals}")
        for f,g in se[:4]:
            # 它命中的自配片段
            import re
            ips=CD.IP.findall(g); key=max(ips,key=len) if ips else ([t for t in CD.TOK.findall(g) if len(t)>=2] or [g])[-1]
            srcs=[c for c in mcfg.splitlines() if key in c]
            print(f"    机器断言 found '{g[:30]}' ← 自己配过: {srcs[0][:55] if srcs else '?'}")
            shown += 1
        if shown >= 24: break

if __name__ == "__main__":
    main()
