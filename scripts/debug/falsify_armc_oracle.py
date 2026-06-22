"""Arm C：外置账本 + 确定性 oracle 做轮转分配。LLM 只做 grounding——
全程不让 LLM 心算 rr/wrr 轮转(那是 Arm B 系统性少算的根因)。

分工(红线)：
- LLM(每 case 一次): 从配置文本提取 {algo, pools[name,ip,weight], 复位命令}。纯 grounding。
- LLM(每 REQ 一次, 二值): 这次操作是否是一次"会命中池组的选择查询"(yes/no)。不判命中哪池。
- 确定性引擎: 维护轮转计数器, 第 k 次选择查询 → oracle 按 rr(k%N)/wrr(加权) 定命中哪池,
  账本 +1; 复位命令归零; SHOW 比对 账本[pool] vs 真人 Hit。

对照 Arm A(39% 一把梭) / Arm B(23% LLM 逐事件判命中池)。
判决: C 准确率若跳上去 → 实锤失败根因是"让 LLM 算轮转", oracle 是解;
若仍低 → 真有一批是 script_runtime/路由 定不了的。
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path("/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine")
sys.path.insert(0, str(ROOT))
from scripts.debug.falsify_statemachine import parse_events, CORPUS  # noqa: E402


def _model():
    from dotenv import load_dotenv
    load_dotenv(str(ROOT / "environment"), override=False)
    from main.ist_core.agents._llm import build_agent_chat_model
    return build_agent_chat_model()


def _ask(model, sysp, user, timeout=120):
    from langchain_core.messages import SystemMessage, HumanMessage
    import concurrent.futures as cf
    msgs = [SystemMessage(content=sysp), HumanMessage(content=user)]
    with cf.ThreadPoolExecutor(max_workers=1) as ex:
        resp = ex.submit(model.invoke, msgs).result(timeout=timeout)
    txt = str(resp.content)
    m = re.search(r"\{.*\}", txt, re.S)
    return (json.loads(m.group(0)) if m else {}), txt


# ── LLM grounding #1: 从整条配置提取静态结构(每 case 一次) ──
_GROUND_SYS = """你从一条 APV sdns 测试用例的【配置命令全文】里抽取选池的静态结构。
不要你算任何命中、不要推序列——只如实抽配置写了什么。

输出 JSON:
{"algo": "rr|wrr|unknown",          // group method,看不出填 unknown
 "pools": [{"name": "p1", "weight": 1}, ...],  // 按【配置出现顺序】列出参与选池的 pool,wrr 才有意义的 weight,rr 一律填 1
 "reset_rows": []                    // 哪些行号的命令会把统计清零(重设method/重建池),没有填[]
}
只输出 JSON,不解释。抽不到就 algo=unknown、pools=[]。"""


# ── LLM grounding #2: 每个 REQ 是否一次命中池组的选择查询(二值) ──
_REQ_SYS = """判断 APV sdns 设备上【这一次操作】是否是一次会被 sdns 池组应答、从而使某池命中数+1
的"选择查询"(典型: dig/DNS 解析请求)。
- 是真实 DNS 查询且会触发选池 → hit_query=true
- 环境准备(ip addr add/del)、与选池无关 → hit_query=false
只输出 JSON: {"hit_query": true/false}。不要判命中哪个池——那不归你。"""


def ground_config(model, events):
    cfg_lines = [f"r{e['row']}: {e['cmd']}" for e in events if e["kind"] == "CFG"]
    user = "【配置命令全文(带行号)】\n" + "\n".join(cfg_lines)
    d, _ = _ask(model, _GROUND_SYS, user)
    return d


def is_hit_query(model, ev, cache):
    key = ev["cmd"].strip()
    if key in cache:
        return cache[key]
    try:
        d, _ = _ask(model, _REQ_SYS, f"【这一次操作】{ev.get('who','')}: {ev['cmd']}")
        v = bool(d.get("hit_query"))
    except Exception:  # noqa: BLE001
        v = False
    cache[key] = v
    return v


def oracle_pick(algo, pools, k):
    """确定性轮转:第 k 次(0基)选择查询命中哪个池名。零 LLM。"""
    N = len(pools)
    if N == 0:
        return None
    if algo == "wrr":
        # 展开加权序列:p1 重复 w1 次... 再按位置轮转
        seq = []
        for p in pools:
            seq += [p["name"]] * max(1, int(p.get("weight", 1)))
        return seq[k % len(seq)]
    # rr / unknown 默认按配置顺序轮转
    return pools[k % N]["name"]


def run_arm_c(model, events, out, fname):
    ground = ground_config(model, events)
    algo = (ground.get("algo") or "unknown").lower()
    pools = ground.get("pools") or []
    reset_rows = set(ground.get("reset_rows") or [])
    pool_names = [p["name"] for p in pools]
    ledger = {n: 0 for n in pool_names}
    k = 0  # 全局选择查询计数器(轮转下标)
    req_cache = {}
    buckets = {"correct": 0, "wrong": 0}
    for e in events:
        if e["kind"] == "CFG":
            if e["row"] in reset_rows:
                ledger = {n: 0 for n in pool_names}
                k = 0
        elif e["kind"] == "REQ":
            if pool_names and is_hit_query(model, e, req_cache):
                pick = oracle_pick(algo, pools, k)
                k += 1
                if pick in ledger:
                    ledger[pick] += 1
        elif e["kind"] == "SHOW":
            hv = e["human_hit"]
            if hv is None:
                continue
            pred = ledger.get(e["pool"], 0)
            bucket = "correct" if pred == hv else "wrong"
            buckets[bucket] += 1
            rec = {"file": fname, "row": e["row"], "pool": e["pool"],
                   "human_hit": hv, "pred": pred, "bucket": bucket,
                   "algo": algo, "pools": pool_names, "ledger": dict(ledger)}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
            flag = "✓" if bucket == "correct" else "✗错"
            print(f"  [{flag}] row{e['row']} pool {e['pool']} 真人={hv} oracle={pred} "
                  f"(algo={algo} pools={pool_names})")
    return buckets


def main():
    model = _model()
    out = open(ROOT / "runtime/logs/falsify_armc.jsonl", "w")
    tot = {"correct": 0, "wrong": 0}
    for fn in ["sdns_method/sdns_method.xlsx", "sdns_DynamicDomain_MX/mx_record.xlsx"]:
        print(f"\n=== Arm C 重放 {fn} (oracle做轮转,LLM只grounding) ===")
        ev = parse_events(CORPUS / fn)
        b = run_arm_c(model, ev, out, fn.split("/")[-1])
        print(f"  小计: {b}")
        for key in tot:
            tot[key] += b[key]
    out.close()
    n = tot["correct"] + tot["wrong"]
    acc = tot["correct"] / n if n else 0
    print(f"\n=== Arm C (oracle轮转+LLM只grounding) {n}个SHOW点 ===")
    print(f"  ✓ 对真人: {tot['correct']}   ✗ 错: {tot['wrong']}   准确率: {acc:.0%}")
    print(f"  对照: Arm A 39%(一把梭) / Arm B 23%(LLM逐事件判命中池)")
    print(f"  证据: runtime/logs/falsify_armc.jsonl")


if __name__ == "__main__":
    main()
