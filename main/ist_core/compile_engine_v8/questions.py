"""欠定问题组织(孔②):机械模板为主路,LLM 润色可选、后校验兜底。

台账(needs_decision.json)是锚——问题文本由代码从台账拼装,autoid 全名、
三选项、ordering_sensitive 的「顺序语义保留/放弃」显式句都由代码保证;
`IST_ENGINE_ASKQ_LLM=1` 时允许 LLM 润色散文,润色后仍过 `validate_questions`
(不过则回落模板)。每次 ask ≤4 题(ask_user 工具硬限),超出分批。
"""

from __future__ import annotations

import json
from pathlib import Path

# 决策选项(与 compile_user_decision 的 decision 枚举一致)
DECISIONS = ("改过程", "改预期", "改描述")

# claim_kind → 建议断言形态(机械映射;最终形态以用户答案落盘为准)
FORM_BY_KIND = {
    "distribution": "dist", "weight_ratio": "dist",
    "new_member_last": "member", "absolute_position": "member", "rotation_order": "member",
    "new_member_participates": "member",
    "relation_same": "captured_relation", "relation_diff": "captured_relation",
}


def load_ledgers(outputs_root: Path, autoids: list[str]) -> dict[str, dict]:
    """读各 case 的 needs_decision.json 台账原件(缺失的跳过,不猜)。"""
    out: dict[str, dict] = {}
    for aid in autoids:
        p = outputs_root / aid / "needs_decision.json"
        if p.is_file():
            try:
                out[aid] = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
    return out


def build_questions(ledgers: dict[str, dict]) -> list[dict]:
    """台账 → ask_user questions(机械模板)。每 case 一题(≤4 题一批由调用方切)。"""
    questions = []
    for aid, nd in sorted(ledgers.items()):
        claims = [c for c in (nd.get("claims") or []) if isinstance(c, dict)]
        if not claims:
            continue
        ordering = any(c.get("ordering_sensitive") for c in claims)
        reasons = "；".join(str(c.get("reason", ""))[:120] for c in claims[:3])
        mins = [int(c.get("min_requests") or 0) for c in claims]
        min_req = max(mins) if any(m > 0 for m in mins) else 0
        kinds = [str(c.get("claim_kind", "")) for c in claims]
        form = next((FORM_BY_KIND[k] for k in kinds if k in FORM_BY_KIND), "dist")

        if all(k == "command_existence" for k in kinds):
            # S6 存在性呈报(V8.5 片1):题面带检索证明,选项语义按「换形态/挂起」而非可验性
            cmds = "、".join(f"『{c.get('command', '')}』" for c in claims[:3])
            q_text = (f"用例 {aid}(尾号 {aid[-6:]})使用的命令在被测版本专属 CLI 手册"
                      f"命令集中查无记载:{reasons}。")
            opt_process = {"label": "改过程",
                           "description": f"换用版本内存在的等价命令/形态重写 {cmds}(引擎继续编写)。"}
            opt_expect = {"label": "改预期",
                          "description": "保留过程,改用版本内可观测的替代验证形态。"}
            opt_desc = {"label": "改描述",
                        "description": ("确认该功能不属本版本/记载互斥(fulldns 先例)——"
                                        "本轮不产出,挂起待适用版本;文档不一致如实写报告。")}
            questions.append({"question": q_text, "header": f"存在性·{aid[-6:]}",
                              "options": [opt_process, opt_expect, opt_desc],
                              "multiSelect": False, "_autoid": aid,
                              "_ordering": False, "_form": form})
            continue

        q_text = (f"用例 {aid}(尾号 {aid[-6:]})按原始写法验证不出目标行为:{reasons}。"
                  + (f"最小可验请求数 {min_req} 次。" if min_req else "")
                  + "你希望怎么改?")
        opt_process = {
            "label": "改过程",
            "description": (f"加请求/观测次数到可验水平" + (f"(≥{min_req} 次)" if min_req else "")
                            + (";顺序语义**保留**(产物须能证明顺序)" if ordering else "")
                            + f"。断言形态按 {form}。")}
        opt_expect = {
            "label": "改预期",
            "description": ("把不可证伪的绝对预期改成可验形态(关系/归属)"
                            + (";⚠ 顺序语义将**放弃**——选这项即显式批准放弃「按序命中」的覆盖"
                               if ordering else "") + "。")}
        opt_desc = {"label": "改描述", "description": "用例描述本身有歧义/与设备行为矛盾,待人工厘清(本轮不产出)。"}
        questions.append({
            "question": q_text,
            "header": f"欠定·{aid[-6:]}",
            "options": [opt_process, opt_expect, opt_desc],
            "multiSelect": False,
            "_autoid": aid,           # 内部路由用(发给 ask_user 前剥离)
            "_ordering": ordering,
            "_form": form,
        })
    return questions


def validate_questions(questions: list[dict], ledgers: dict[str, dict]) -> bool:
    """后校验(LLM 润色路径的门):每题含对应 autoid;ordering_sensitive 的题面
    必须显式出现「顺序语义」;选项 label 是固定枚举。"""
    if len(questions) != len(ledgers):
        return False
    for q in questions:
        aid = q.get("_autoid", "")
        if aid not in ledgers:
            return False
        text = str(q.get("question", ""))
        if aid not in text and aid[-6:] not in text:
            return False
        if q.get("_ordering") and "顺序语义" not in text + json.dumps(
                q.get("options", []), ensure_ascii=False):
            return False
        labels = [o.get("label") for o in q.get("options", [])]
        if not set(labels) <= set(DECISIONS):
            return False
    return True
