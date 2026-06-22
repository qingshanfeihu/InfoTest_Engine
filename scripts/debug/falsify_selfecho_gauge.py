"""实验1:把self-echo尺子套到已验证正确的真人gold上。
self-echo谓词 = 断言值 ∈ 本case自己配置的token。
若真人gold(上机验证过=正确)也飙到高self-echo率,这把尺子把正确判成病→当场判死。
口径与common_disease_31完全一致,只是对象换成真人gold自己(断言vs自己配置)。"""
import json, sys, glob
from pathlib import Path
ROOT = Path("/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine")
sys.path.insert(0, str(ROOT))
import scripts.debug.common_disease_31 as CD

def selfecho_key(mval):
    """与CD.classify同款:抽断言值的关键标识(IP或末位token)。"""
    import re
    ips = CD.IP.findall(mval)
    if ips: return max(ips, key=len)
    toks = [t for t in CD.TOK.findall(mval) if len(t) >= 2]
    return toks[-1] if toks else mval.strip()

def main():
    idx = json.load(open(ROOT/"runtime/logs/human_autoid_index.json"))
    prods = sorted(set(x.split("/")[-2] for x in glob.glob(str(ROOT/"workspace/outputs/2030*/case.xlsx"))))
    n_cp = n_echo = 0
    rows = []
    for aid in prods:
        hf = idx.get(aid)
        if not hf: continue
        # 真人gold自己的 check_point + 自己的配置(含init前置:从行块起算)
        gcps, gcfg = CD._human_block(aid, hf)
        if not gcps: continue
        cfgtoks = CD._toks(gcfg)
        per_cp = len(gcps); per_echo = 0
        for f, g in gcps:
            key = selfecho_key(g)
            if key in cfgtoks:
                per_echo += 1
        n_cp += per_cp; n_echo += per_echo
        rows.append((aid, hf.split('/')[-2], per_cp, per_echo))
    print(f"=== 把self-echo尺子套到真人gold(已上机验证=正确)===\n")
    print(f"真人gold断言点总数: {n_cp}")
    print(f"被尺子判为self-echo(值∈自己配置): {n_echo} ({100*n_echo/n_cp:.0f}%)")
    print(f"\n对比:同尺子打机器产物时 self-echo=44%")
    print(f"判决: 若真人gold也高→尺子把正确断言判成病→旧'62%通病'结论作废\n")
    print("逐case(真人gold自echo / 总断言点):")
    for aid, fam, ncp, ne in sorted(rows, key=lambda x:-x[3]/max(1,x[2]))[:20]:
        print(f"  {aid[:18]:18} [{fam[:20]:20}] {ne:2}/{ncp:2} = {100*ne/ncp:.0f}%")

if __name__ == "__main__":
    main()
