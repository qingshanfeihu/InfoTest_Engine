"""v4 置信函数 f():判 xlsx check_point 行"配不配得上它所测的配置行为"。

不替代上机 verdict,是第二判据(快筛+abstain)。终判仍上机。

**设计红线(goal:不许硬代码)**:本模块**不写任何"某模式该用某断言形态"的规则、不派魔数分、
不做关键词意图匹配**。那些是 _CAPS 式硬编码。判分交给 LLM 看真实证据(招牌菜先例+手册+原始需求)
现场判——few-shot 锚点,不训练、不写规则。

本模块只做**纯客观事实**的两件事(它们是框架契约/数据,不是判断):
1. link_assertion_to_config:按框架派发契约,把每个 check_point 串到它所测的配置步骤。
2. build_judge_evidence:组装"待判断言 + 所测配置 + 同类招牌菜先例 + 原始需求"成证据包,交给 LLM 判分。

判分(score_case)= 调 LLM,喂证据包,让它输出每行 0-1 置信 + 理由。无 LLM 时返回 abstain
(不退化成硬规则猜分——那违背"只看事实")。
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field


# ── 唯一的"事实"部分:串联(框架派发契约,客观,非判断)──────────────────
def link_assertion_to_config(rows: list[dict]) -> list[dict]:
    """把每个 check_point 行,关联到它前面最近的"产出输出的非 check_point 步骤"。

    框架契约(事实):check_point 校验上一个非 check_point 步骤的输出(dig/show)。
    config_context = 截至该产出步骤为止所有 APV 配置命令。这是框架行为,不是我的判断。

    rows: [{"E","F","G"}...] 数据区顺序行。
    返回 [{"cp", "tested_step", "config_context":[...]}]
    """
    links = []
    last_output_step = None
    config_so_far: list[str] = []
    for row in rows:
        e = (row.get("E") or "").strip()
        g = (row.get("G") or "").strip()
        if e == "check_point":
            links.append({"cp": row, "tested_step": last_output_step,
                          "config_context": list(config_so_far)})
        else:
            if e.startswith("APV") and g:
                for line in g.split("\n"):
                    if line.strip():
                        config_so_far.append(line.strip())
            if g and re.search(r"\b(dig|show|curl|nslookup|ping)\b", g, re.I):
                last_output_step = row
    return links


@dataclass
class RowScore:
    cp_g: str
    score: float           # 0-1,LLM 给的
    notes: list[str] = field(default_factory=list)


# ── 证据组装(客观:把三份真实料拼成给 LLM 的证据,不含任何判断逻辑)──────
def build_judge_evidence(rows: list[dict], need_intent: str,
                         anchor_examples: str = "", manual_facts: str = "") -> str:
    """组装判分证据包(纯拼装,无判断)。anchor_examples=招牌菜先例文本(qa_lookup_pattern 给),
    manual_facts=手册相关行为(agent grep 给)。这些是真实料,不是我编的规则。"""
    links = link_assertion_to_config(rows)
    parts = [f"原始需求(作者意图): {need_intent or '(未提供)'}", "", "待判的 check_point(每个含它所测的配置):"]
    for i, lk in enumerate(links):
        cp_g = (lk["cp"].get("G") or "").strip()
        cp_f = (lk["cp"].get("F") or "").strip()
        tested = (lk["tested_step"].get("G") if lk["tested_step"] else "") or "(无前序输出步骤)"
        cfg = "; ".join(lk["config_context"][-8:]) or "(无)"
        parts.append(f"  [{i}] 断言: {cp_f}({cp_g})")
        parts.append(f"      它校验的输出来自: {tested}")
        parts.append(f"      截至此处的配置: {cfg}")
    if anchor_examples:
        parts += ["", "同类招牌菜先例(已验证跑通的认证断言形态,供参考):", anchor_examples]
    if manual_facts:
        parts += ["", "手册相关行为(配置该产生什么可观测特征):", manual_facts]
    return "\n".join(parts)


_JUDGE_SYS = """你是测试评审专家(厨师长)。判断每个 check_point 断言"配不配得上它所测的配置行为"——
即这个断言有没有真的测到原始需求要测的行为,还是只是写了个能 pass 但没咬住行为的弱断言。

判据(只据给你的真实证据,不靠通用常识硬套):
- 看"原始需求要测什么" vs "这个断言实际在校验什么"——对得上才算测到。
- 对照"同类招牌菜先例"的断言形态:先例怎么验这类行为的,待判断言是不是也咬住了同样的可观测特征。
- 对照"手册行为":配置该产生的可观测特征,断言有没有针对它。
- 若断言只是 found 一个跟需求行为无关的字面量(域名/IP),而需求要测的是动态行为(分布/计数/时序),
  且先例用的是统计/计数类断言——则该断言弱,低分。

对每个 check_point 输出 0.0-1.0 置信(1=完全咬住需求行为,0=完全没测到)+ 一句理由。
只看证据下结论,证据不足就给中间分并说明。严格输出 JSON:
{"rows":[{"idx":0,"score":0.0,"reason":"..."}]}"""


def score_case(rows: list[dict], need_intent: str = "",
               anchor_examples: str = "", manual_facts: str = "",
               model=None, judge_timeout_s: int = 120) -> dict:
    """LLM 判分(无硬规则)。喂证据包让 LLM 给每行置信。最弱行拖垮全局。

    model: LangChain chat model;None 时尝试默认构建。构建失败 → abstain(不猜分)。
    返回 {overall, abstain, rows:[RowScore], evidence}。
    """
    links = link_assertion_to_config(rows)
    if not links:
        return {"overall": 0.0, "abstain": True, "rows": [], "reason": "无check_point"}

    evidence = build_judge_evidence(rows, need_intent, anchor_examples, manual_facts)

    if model is None:
        try:
            from main.ist_core.agents._llm import build_agent_chat_model
            model = build_agent_chat_model()
        except Exception as exc:  # noqa: BLE001
            return {"overall": 0.0, "abstain": True, "rows": [],
                    "reason": f"无LLM判分器(不退化成硬规则猜分): {exc}", "evidence": evidence}

    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        import concurrent.futures as _cf
        # LLM 判分加超时保护:hang 住不能卡死整轮(实测过 model.invoke 无超时会 hang 死拖垮 batch)。
        # 超时则返回 abstain(不退化成硬规则猜分),由上机 verdict 兜底。
        msgs = [SystemMessage(content=_JUDGE_SYS), HumanMessage(content=evidence)]
        with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
            resp = _ex.submit(model.invoke, msgs).result(timeout=judge_timeout_s)
        txt = str(resp.content)
        m = re.search(r"\{.*\}", txt, re.S)
        data = json.loads(m.group(0)) if m else {"rows": []}
    except _cf.TimeoutError:
        return {"overall": 0.0, "abstain": True, "rows": [],
                "reason": f"判分 LLM 调用超时(>{judge_timeout_s}s),abstain 不卡死流程;由上机 verdict 兜底",
                "evidence": evidence}
    except Exception as exc:  # noqa: BLE001
        return {"overall": 0.0, "abstain": True, "rows": [],
                "reason": f"判分调用/解析失败: {exc}", "evidence": evidence}

    by_idx = {r.get("idx"): r for r in data.get("rows", [])}
    scores = []
    for i, lk in enumerate(links):
        cp_g = (lk["cp"].get("G") or "").strip()
        r = by_idx.get(i, {})
        sc = float(r.get("score", 0.0)) if isinstance(r.get("score"), (int, float)) else 0.0
        scores.append(RowScore(cp_g=cp_g, score=sc, notes=[r.get("reason", "")]))

    overall = min(s.score for s in scores) if scores else 0.0   # 最弱行拖垮(这是规则但是结构性的,非领域硬编码)
    return {"overall": overall, "abstain": overall < 0.5, "rows": scores, "evidence": evidence}
