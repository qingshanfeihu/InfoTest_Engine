"""focus假设验证:让LLM隔离专注现推期望命中分布,对比draft夹缝里填的值。

核心:oracle的输入【只有需求文本】,不给draft/命令/xlsx结构——逼它专注算一件事。
输出结构化期望分布,再用守恒律(sum命中==请求次数)做零LLM确定性自检。

验证的是用户的核心主张:同一个LLM,从draft的"一心十用夹缝计算"
换成"隔离专注现推",会不会就把分布算对/把欠定case标出来。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import scripts.debug.audit_31_drafts as A  # need_map / cps_of / classify
from scripts.debug.v_arm_compare import _ask, _model  # 复用模型+重试封装

# oracle只干一件事:给定测试需求,现推每次请求该命中哪个pool、各pool期望命中次数。
_ORACLE_SYS = """你是负载均衡分布计算器。只做一件事:给定一条SDNS负载均衡测试需求,
按算法语义现场推导"期望命中分布"——不要判断别人对错,只算你自己的答案。

规则:
- 先识别:算法(rr轮询/wrr加权轮询/其他)、pool数量及权重、客户端发请求的总次数。
- 按算法定律推导:rr=依次轮转(第k次命中第((k-1)%pool数)+1个pool);
  wrr=按权重比例分配命中次数(权重w_i的pool命中次数≈总次数*w_i/总权重)。
- 关键:总命中次数必须严格等于总请求次数(守恒)。每个pool命中次数是非负整数。
- 若请求次数太少无法体现声称的分布(如发3次却要体现3:2:1),
  或需求没说清算法/次数/权重 → 标 underdetermined=true 并说明缺什么,不要硬凑。

只输出JSON,不要解释:
{"algo":"rr|wrr|other","n_pools":N,"weights":[...]|null,"n_requests":N,
 "underdetermined":false,"reason":"",
 "expected":[{"pool":1,"hits":H1},...]}"""


def oracle(need, model):
    data, raw = _ask(model, _ORACLE_SYS, f"测试需求:\n{need}")
    return data, raw


def selfcheck(d):
    """零LLM确定性自检:守恒律。返回(ok, msg)。"""
    if d.get("underdetermined"):
        return True, "underdetermined(已诚实标注,不硬凑)"
    exp = d.get("expected") or []
    if not exp:
        return False, "无expected分布"
    total = sum(int(e.get("hits", 0)) for e in exp)
    nreq = d.get("n_requests")
    if nreq is None:
        return False, "缺n_requests无法核守恒"
    if total != nreq:
        return False, f"守恒破坏:命中和{total}≠请求数{nreq}"
    if any(int(e.get("hits", 0)) < 0 for e in exp):
        return False, "负命中次数"
    return True, f"守恒通过:命中和={total}=请求数={nreq}"


def main():
    aids = json.load(open(ROOT / "runtime/logs/dyn_aids.json"))
    if len(sys.argv) > 1:
        aids = sys.argv[1:]
    needs = A.need_map()
    model = _model()
    mode = "a" if len(sys.argv) > 1 else "w"
    out = open(ROOT / "runtime/logs/oracle_dist.jsonl", mode)
    n_ok = n_under = n_broke = 0
    for aid in aids:
        need = needs.get(aid, "")
        cps = A.cps_of(str(ROOT / f"workspace/outputs/{aid}/case.xlsx"))
        _, _, _, draft_hits, _ = A.classify(need, cps)
        try:
            d, raw = oracle(need, model)
        except Exception as e:
            print(f"[{aid}] oracle异常: {e}"); continue
        ok, msg = selfcheck(d)
        if d.get("underdetermined"): n_under += 1
        elif ok: n_ok += 1
        else: n_broke += 1
        exp = d.get("expected") or []
        exp_hits = [int(e.get("hits", 0)) for e in exp]
        rec = {"autoid": aid, "need": need, "oracle": d,
               "selfcheck_ok": ok, "selfcheck_msg": msg,
               "draft_hits": draft_hits, "oracle_hits": exp_hits}
        out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
        flag = "UNDER" if d.get("underdetermined") else ("OK" if ok else "BROKE")
        print(f"[{aid}] {flag:6} algo={d.get('algo')} req={d.get('n_requests')} "
              f"oracle期望={exp_hits} | draft填={draft_hits}")
        print(f"          自检: {msg}")
        if d.get("underdetermined"):
            print(f"          欠定原因: {d.get('reason','')[:70]}")
    out.close()
    print(f"\n=== 13动态case隔离专注现推结果 ===")
    print(f"  守恒通过(算出唯一解): {n_ok}")
    print(f"  诚实标欠定: {n_under}")
    print(f"  自检破守恒(LLM自己也算错): {n_broke}")
    print(f"  证据落: runtime/logs/oracle_dist.jsonl")


if __name__ == "__main__":
    main()
