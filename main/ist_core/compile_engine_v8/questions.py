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

def _first_clause(s: str, cap: int = 150) -> str:
    """按中文标点截首句(§18.14 D2:替代裸 `[:N]` 词中断路——668059 曾被截在
    '已检索:knowledge/data/markdo';机读检索证明尾部本就不该进用户题面)。"""
    s = str(s or "").strip()
    for i, ch in enumerate(s):
        if ch in "。;；" and i >= 10:
            return s[:i]      # 不含末标点——外层 join 用「；」连,避免双标点
    return s if len(s) <= cap else s[:cap].rstrip() + "…"


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
        reasons = "；".join(_first_clause(c.get("reason", "")) for c in claims[:3])
        mins = [int(c.get("min_requests") or 0) for c in claims]
        min_req = max(mins) if any(m > 0 for m in mins) else 0
        kinds = [str(c.get("claim_kind", "")) for c in claims]
        form = next((FORM_BY_KIND[k] for k in kinds if k in FORM_BY_KIND), "dist")

        if all(k == "missing_teardown" for k in kinds):
            # G1 配对恢复呈报(V8.5 片5):写是被测行为本身 vs 该补恢复步
            c0 = claims[0]
            tau = "；".join(str(t) for t in (c0.get("suggested_tau") or [])[:3])
            q_text = (f"用例 {aid}(尾号 {aid[-6:]})的配置写会在测试床留下框架清理"
                      f"够不着的网络层残留(同类残留曾一批内六次弄坏共享床):{reasons}。")
            opt_process = {"label": "改过程",
                           "description": f"案尾追加恢复步(建议:{tau or '逆序 no 回放'}),断言之后执行——推荐。"}
            opt_expect = {"label": "改预期",
                          "description": "该写是被测行为本身、必须保留残留——按此意图重编(残留将由批末床态收敛处理,交付报告声明)。"}
            opt_desc = {"label": "改描述",
                        "description": "用例意图待人工厘清,本轮不产出(挂起)。"}
            questions.append({"question": q_text, "header": f"清理·{aid[-6:]}",
                              "options": [opt_process, opt_expect, opt_desc],
                              "multiSelect": False, "_autoid": aid,
                              "_ordering": False, "_form": form})
            continue

        if all(c.get("test_point") for c in claims):
            # §18.13 三元组投影(逐字渲染,零模板文案):面板=worker 报告本身。
            # 真实路径 claim_kind=verification_path_absent 但带三元组字段→走这里
            # (旧版掉进 generic「加请求/观测次数」模板=run22 病理)。
            c0 = claims[0]
            tp = str(c0.get("test_point") or "")
            obs = str(c0.get("obstacle") or "")
            equiv = c0.get("equivalent") or None
            proc = str((equiv or {}).get("procedure") or "") if equiv else ""
            preserves = str((equiv or {}).get("preserves") or "") if equiv else ""
            no_eq = str(c0.get("no_equivalent_reason") or "")
            q_text = (f"用例 {aid[-6:]} 要验证:{tp}。\n问题:{obs}。"
                      + (f"\n等价方法:{proc}" + (f"({preserves})" if preserves else "") + "。"
                         if proc else ""))
            opts, tok = [], {}
            if proc:
                lbl = f"采纳「{proc[:60]}」"
                opts.append({"label": lbl,
                             "description": "采纳此等价验证重编(引擎按它编写;差异声明随交付报告)。"})
                tok[lbl] = "改过程"
            lbl_other = "我给别的等价方案"
            opts.append({"label": lbl_other,
                         "description": "在自定义输入里给出你的等价方案,原文随裁决下发 worker。"})
            tok[lbl_other] = "改预期"
            lbl_susp = "挂起,如实报告"
            opts.append({"label": lbl_susp,
                         "description": f"{no_eq or obs}。本轮不产出,待可执行环境。"})
            tok[lbl_susp] = "改描述"
            questions.append({"question": q_text, "header": f"欠定·{aid[-6:]}",
                              "options": opts, "multiSelect": False, "_autoid": aid,
                              "_ordering": ordering, "_form": form,
                              "_token_by_label": tok})   # P3:label→token 显式映射
            continue

        if all(k == "forbidden_mechanism" for k in kinds):
            # F6 禁令机制呈报(§18.11 五稿):山穷水尽=有能力完成设计验证就实现——
            # 题面主推 worker 按配置面模型推导的等价实现(模型条件,差异已声明),
            # 投降选项必须携穷举论证语义;误报(字面命中非机制)一答放行。
            c0 = claims[0]
            prop = str(c0.get("proposed_equivalent") or c0.get("suggested_fix") or "")[:200]
            q_text = (f"用例 {aid}(尾号 {aid[-6:]})的意图要求测试床禁止的机制:{reasons}。"
                      + (f"worker 按配置面模型推导的等价实现:{prop}。" if prop else "")
                      + "等价性为模型条件(启动通道等差异已在报告声明),如何处置?")
            opt_process = {"label": "改过程",
                           "description": ("采纳等价实现重编(推荐;差异声明随交付报告)。"
                                           "若命中词并非本案执行机制(如计数/字段名),同选此项"
                                           "并注明,照常编写。")}
            opt_expect = {"label": "改预期",
                          "description": "等价实现方向不对——在自定义输入里给出你的等价方案,原文将随裁决下发 worker。"}
            opt_desc = {"label": "改描述",
                        "description": "确认无有效替代/必须真机制——本轮不产出,挂起待可执行环境(如实报告)。"}
            questions.append({"question": q_text, "header": f"禁令·{aid[-6:]}",
                              "options": [opt_process, opt_expect, opt_desc],
                              "multiSelect": False, "_autoid": aid,
                              "_ordering": False, "_form": form})
            continue

        if all(k == "command_existence" for k in kinds):
            # S6 存在性呈报(§18.14 S3:题面人话对象——用干净 cmds,机读检索证明
            # (签名数/覆盖率/检索路径)留台账 _evidence 不进用户面)。
            cmds = "、".join(f"『{c.get('command', '')}』" for c in claims[:3])
            q_text = (f"用例 {aid[-6:]} 用到的命令 {cmds} 在被测版本的 CLI 手册里"
                      f"查不到(可能这版没有此功能,或命令改了名)。")
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
