"""意图族聚类（V3 步骤3，论文 §3.7 定理3.10：同族 H_G 可共享）。

把一批待编译 case 按意图相似度聚成族。每族共享骨架（G 段），族首编译一次骨架，
族内 case 只做 E+V 绑定——把 H_G 从"×case 数"降到"×族数"。

复用 precedent_tools 的 _intent_tokens（中英 bigram 词袋），不上向量库（§五 YAGNI）。
纯确定性聚类（贪心连通分量），不做语义判断——骨架选择仍是 draft（族首）的 LLM 决策，
聚类只决定"哪些 case 共享一次骨架推导"，不替代骨架内容。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from langchain_core.tools import tool

from main.ist_core.tools.device.precedent_tools import _intent_tokens


def _pair_similarity(a: str, b: str) -> float:
    """两条 case 意图文本的 Jaccard 词重叠相似度（对称，用于 case↔case 聚类）。"""
    ta, tb = _intent_tokens(a), _intent_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass
class IntentFamily:
    """一个意图族：成员 case key 列表 + 代表性意图文本（族首，骨架由它编译）。"""
    family_id: str
    member_keys: list[str] = field(default_factory=list)
    head_key: str = ""
    head_intent: str = ""

    def size(self) -> int:
        return len(self.member_keys)


def cluster_by_intent(cases: list[dict], threshold: float = 0.5) -> list[IntentFamily]:
    """把 cases 按意图相似度贪心聚成族（连通分量：sim≥threshold 即同族）。

    cases: [{"key": <autoid>, "intent": <需求文本>}, ...]（顺序决定族首与 family_id 序）。
    threshold: 相似度阈值，初版 0.5（可调）。低于阈值的 case 自成单元素族。

    返回族列表，每族 head_key=族内第一个出现的 case（其意图代表全族骨架）。
    确定性：同输入同输出，不调 LLM、不读环境。
    """
    n = len(cases)
    assigned = [False] * n
    families: list[IntentFamily] = []

    for i in range(n):
        if assigned[i]:
            continue
        # 以 i 为族首，吸纳所有与族首 sim≥threshold 的未分配 case
        head = cases[i]
        fam = IntentFamily(
            family_id=f"fam_{len(families)}",
            member_keys=[str(head.get("key", i))],
            head_key=str(head.get("key", i)),
            head_intent=str(head.get("intent", "")),
        )
        assigned[i] = True
        for j in range(i + 1, n):
            if assigned[j]:
                continue
            sim = _pair_similarity(head.get("intent", ""), cases[j].get("intent", ""))
            if sim >= threshold:
                fam.member_keys.append(str(cases[j].get("key", j)))
                assigned[j] = True
        families.append(fam)

    return families


def summarize_families(families: list[IntentFamily]) -> str:
    """给编排器/日志的一行式摘要：族数、最大族、单元素族数、H_G 摊销比。"""
    if not families:
        return "意图族: 0"
    total = sum(f.size() for f in families)
    singletons = sum(1 for f in families if f.size() == 1)
    biggest = max(families, key=lambda f: f.size())
    # H_G 摊销：原本付 total 次骨架推导，现付 len(families) 次
    amort = f"{total}→{len(families)}" if total else "0"
    return (f"意图族: {len(families)} 族 / {total} case（骨架推导 {amort}，"
            f"最大族 {biggest.size()}（{biggest.head_key}），单元素族 {singletons}）")


@tool(parse_docstring=True)
def qa_cluster_intents(cases_json: str, threshold: float = 0.5) -> str:
    """把一批待编译 case 按**意图相似度**聚成族（V3 步骤3，H_G 摊销）。

    论文定理3.10：H=H_G+H_V'，同族 case 的骨架熵 H_G 可共享。编排器据此**每族只编一次
    族骨架**，族内 case 复用骨架只做 E+V 绑定，把骨架推导从"×case 数"降到"×族数"。

    纯确定性聚类（中英 bigram 词袋 Jaccard + 贪心连通分量），不调 LLM、不读环境、零命令——
    只决定"哪些 case 共享一次骨架推导"，骨架内容仍由 draft（族首）的 LLM 决策。

    Args:
        cases_json: JSON 数组字符串，每项 {"key": "<autoid>", "intent": "<需求文本:脑图step+expected>"}。
            顺序决定族首（族内第一个出现的 case）与 family_id 序。
        threshold: 相似度阈值（Jaccard 词重叠），默认 0.5。低于阈值的 case 自成单元素族。

    Returns:
        JSON 字符串 {"summary": "<一行摘要>", "families": [{"family_id","head_key","head_intent","member_keys":[...]}]}。
        编排器据此：对每个 head_key 先编族骨架，再把族骨架塞进同族 member_keys 的 draft brief。
    """
    try:
        cases = json.loads(cases_json) if isinstance(cases_json, str) else cases_json
        if not isinstance(cases, list):
            return "error: cases_json 必须是数组"
    except Exception as e:  # noqa: BLE001
        return f"error: cases_json 解析失败: {e}"
    if not cases:
        return json.dumps({"summary": "意图族: 0", "families": []}, ensure_ascii=False)

    fams = cluster_by_intent(cases, threshold=threshold)
    out = {
        "summary": summarize_families(fams),
        "families": [
            {"family_id": f.family_id, "head_key": f.head_key,
             "head_intent": f.head_intent, "member_keys": f.member_keys}
            for f in fams
        ],
    }
    return json.dumps(out, ensure_ascii=False)

