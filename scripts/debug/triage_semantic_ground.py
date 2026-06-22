"""未测杠杆:语义 grounding 臂。

已证伪 = 喂 CLI 文法(语法/参数位): 37%→12%(scripts/debug/triage_grounded_arm.py)。
本臂换的唯一变量 = 喂一段【对所有 rr/wrr 族通用的选池/清零语义规则】,
看能否把 LLM 离线推动态点的对率从基线抬上 0.7 线。

红线: SEM_BLOCK 是产品级通用语义(rr 按池序轮转/wrr 按权重展开/重设 method 清零
统计/A·AAAA 按记录类型分流),对所有同类 case 成立——不是 per-case 答案,
不是正则规则机(armd 那种)。LLM 仍自己读配置、自己算。代码零产品 if 分支。
"""
import json
import sys
from pathlib import Path

ROOT = Path("/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine")
CORPUS = Path("/tmp/real_cases")
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(str(ROOT / "environment"), override=False)
# 复用基线臂的抽取/匹配/提示词,保证唯一变量是"是否注入语义 grounding"
from scripts.debug.triage_crossfamily import extract, _match, _SYS  # noqa: E402

# ── 唯一新增变量:产品级通用选池语义(非 per-case,非正则引擎) ──
SEM_BLOCK = """【APV sdns 选池/统计的通用语义规则(对所有 rr/wrr 用例成立,帮你离线推算)】
1. 选池算法(group/host method):
   - rr(轮询): 在该 host 下、含本次查询记录类型的池中,按【配置出现顺序】依次轮转,
     第 k 次该类型查询(0 基)命中第 (k mod N) 个池。
   - wrr(加权轮询): 把每个池按其 weight 重复展开成序列(p1 出现 w1 次...),再按位置轮转;
     N 次请求且 N 为总权重整数倍时,池 i 命中 = N*wi/Σw(唯一守恒解);否则欠定。
2. A / AAAA 分流: 查询只在"含对应记录类型 service"的池间轮转,A 与 AAAA 各自独立计数。
3. 统计清零: 重设该 host 的 method、重建池(no pool 后重配)、带数字重设池权重 → 该 host
   相关池的累计 Hit 归零,轮转位置重置;仅新增 service/ip 不清零。
4. 累计语义: show statistics 的 Hit 是【从上次清零至此刻】该池被选中查询命中的累加次数。
依据以上规则结合配置顺序推算;请求次数不足以唯一确定分布时,归 underdetermined,不要硬猜。"""


def ask(model, steps, grounded: bool, timeout=180):
    from langchain_core.messages import SystemMessage, HumanMessage
    import concurrent.futures as cf
    import re
    head = (SEM_BLOCK + "\n\n") if grounded else ""
    user = (head + "【用例配置+请求序列】\n" + "\n".join(steps)
            + "\n\n按要求对每个断言点输出 JSON。")
    with cf.ThreadPoolExecutor(max_workers=1) as ex:
        resp = ex.submit(model.invoke,
                         [SystemMessage(content=_SYS), HumanMessage(content=user)]).result(timeout=timeout)
    m = re.search(r"\{.*\}", str(resp.content), re.S)
    return json.loads(m.group(0)) if m else {"slots": []}


def score(d, golds):
    """统计该臂在能算族断言上的: 判能算数 / 推对数。"""
    slots = {s["slot"]: s for s in d.get("slots", []) if "slot" in s}
    cc = co = 0
    for i, gold in enumerate(golds):
        s = slots.get(i, {})
        if s.get("source") in ("algorithm", "config_intent"):
            cc += 1
            if _match(s.get("predicted"), gold):
                co += 1
    return cc, co


def main():
    from main.ist_core.agents._llm import build_agent_chat_model
    model = build_agent_chat_model()
    # 挑有动态算法点的族(分诊里 algorithm 类聚集处),配对对照
    fams = sys.argv[1:] or [
        "smoke_test/sdns/sdns_method/sdns_method.xlsx",
        "smoke_test/sdns/sdns_pool/sdns_pool.xlsx",
        "smoke_test/sdns/cname_pool_ipo/cname_pool_ipo.xlsx",
        "smoke_test/sdns/sdns_lastresort_pool/sdns_lastresort_pool.xlsx",
        "smoke_test/sdns/sdns_health_check_dns/dns_link_dst_addr.xlsx",
    ]
    out = open(ROOT / "runtime/logs/triage_semantic.jsonl", "w")
    b_c = b_o = g_c = g_o = 0
    for rel in fams:
        xp = CORPUS / rel
        if not xp.exists():
            print(f"skip {rel}"); continue
        fam = rel.split("/")[-2]
        steps, golds = extract(xp)
        if not golds:
            print(f"[{fam}] 无断言点"); continue
        try:
            base = ask(model, steps[:60], grounded=False)
            sem = ask(model, steps[:60], grounded=True)
        except Exception as e:  # noqa: BLE001
            print(f"[{fam}] 异常 {str(e)[:50]}"); continue
        bc, bo = score(base, golds)
        gc, go = score(sem, golds)
        b_c += bc; b_o += bo; g_c += gc; g_o += go
        arrow = "↑" if go > bo else ("↓" if go < bo else "=")
        print(f"  [{fam[:24]:24}] 断言{len(golds):2} | 基线{bo:2}/{bc:2} → 语义ground{go:2}/{gc:2} {arrow}")
        out.write(json.dumps({"family": fam, "n_gold": len(golds),
                              "base_comp": bc, "base_ok": bo,
                              "sem_comp": gc, "sem_ok": go}, ensure_ascii=False) + "\n")
        out.flush()
    out.close()
    print(f"\n=== 语义 grounding 配对对照 (唯一变量=SEM_BLOCK) ===")
    print(f"  基线(零grounding) 能算推对: {b_o}/{b_c} = {100*b_o//max(b_c,1)}%")
    print(f"  +通用选池语义规则:        {g_o}/{g_c} = {100*g_o//max(g_c,1)}%")
    print(f"  判决线 0.7;对照 CLI文法臂=12%(已证伪)")
    print(f"  证据: runtime/logs/triage_semantic.jsonl")


if __name__ == "__main__":
    main()
