"""worker brief 构建(V8:历史从事实流取;布局与去劫持结构沿用——它们是现行数据驱动的)。

布局(官方长上下文实践+trace 取证,减法检验③通过):首行机读信封 → 数据区(逐轮设备回显
→ 前几轮卷 → 归因假设,响度降级) → 意图(紧邻指令=recency 高位) → 指令区(最末)。
"""

from __future__ import annotations

import json

from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.compile_engine_v8 import facts as F


def intent_summary(aid: str, state: dict) -> str:
    m = sh.manifest(state)
    c = next((x for x in (m.get("cases") or []) if str(x.get("autoid")) == aid), None)
    if not isinstance(c, dict):
        return ""
    lines = [f"title: {c.get('title', '')}  group: {' / '.join(c.get('group_path') or [])}"]
    for si in (c.get("step_intents") or [])[:8]:
        d, e = str(si.get("desc") or "").strip(), str(si.get("expected") or "").strip()
        if d or e:
            lines.append(f"- {d}" + (f" → expected: {e}" if e else ""))
    return "\n".join(lines)[:1200]


def _round_evidence(fs: list[dict], aid: str) -> list[dict]:
    """逐轮失败证据:verdict(fail) 事实 + 其 evidence_ref 指向的 last_run 里该案原文。"""
    docs = []
    for f in fs:
        if f.get("aid") != aid or f.get("ev") != "verdict" or f.get("result") != "fail":
            continue
        ref = str(f.get("evidence_ref") or "")
        ctxt = ""
        if ref:
            data = sh.read_json(sh.project_root() / ref, []) or []
            rec = next((r for r in data if str(r.get("autoid")) == aid), {})
            ctxt = str(rec.get("device_context") or rec.get("detail_tail") or "")[:6000]
        att = next((a for a in fs if a.get("aid") == aid and a.get("ev") == "attribution"
                    and a.get("run_id") == f.get("run_id")), {})
        docs.append({"run_id": f.get("run_id"), "ctx": f.get("ctx"),
                     "device_context": ctxt,
                     "layer": att.get("layer", ""), "disposition": att.get("disposition", ""),
                     "fix_direction": att.get("fix_direction", "")})
    return docs


def _linker_fact_note(aid: str) -> str:
    """上一轮成品卷的引用结构事实(V6 迁入):单看是常态形态,与设备回显合取才有诊断力
    (dig 返回 CNAME 串而非 IP + 成员未本地定义 = 解析链断头,035413 三轮 escalated 根因)。"""
    try:
        from main.ist_core.tools.device.compile_pipeline import _grade_extract_facts
        d = sh.outputs_root() / aid
        facts = _grade_extract_facts(d / "case.xlsx", d / "case.provenance.json") or {}
    except Exception:  # noqa: BLE001
        return ""
    notes = []
    for k in ("cname_member_not_local_host_suspect",):
        base = k[: -len("_suspect")]
        if facts.get(k) and str(facts.get(base + "_note") or "").strip():
            notes.append(str(facts[base + "_note"]).strip())
    return "\n".join(notes)


def build_brief(aid: str, state: dict, fs: list[dict], remedy: dict | None = None) -> str:
    mine = [f for f in fs if str(f.get("aid")) == aid]
    rounds_used = F.rounds_used(mine, aid)
    max_rounds = int(state.get("max_rounds") or 3)
    envelope = {
        "autoid": aid,
        "manifest_path": state.get("manifest_ref", ""),
        "product_version": state.get("product_version", ""),
        "device_build": state.get("device_build", ""),      # 床门自述值随 brief 下发
        "round": rounds_used + 1,
    }
    ud = sh.outputs_root() / aid / "user_decision.json"
    if ud.is_file():
        envelope["user_decision_path"] = str(ud.relative_to(sh.project_root()))
    parts = [json.dumps(envelope, ensure_ascii=False)]
    tail: list[str] = []

    is_retry = rounds_used >= 1
    if is_retry:
        docs = []
        for e in _round_evidence(fs, aid):
            sig = "/".join(x for x in (e["layer"], e["disposition"]) if x)
            docs.append(
                f'<document label="on-device run {e["run_id"]}" ctx="{e["ctx"]}"'
                + (f' attribution="{sig}"' if sig else "") + ">\n"
                + (f"<fix_direction>{e['fix_direction'][:800]}</fix_direction>\n" if e["fix_direction"] else "")
                + f"<device_context>\n{e['device_context']}\n</device_context>\n</document>")
        if docs:
            parts.append("<device_evidence>\n" + "\n".join(docs) + "\n</device_evidence>")
        hist_dir = sh.outputs_root() / aid / "history"
        prev = sorted(hist_dir.glob("case.r*.xlsx")) if hist_dir.is_dir() else []
        if prev:
            parts.append("<prior_config_rolls note=\"previous config sheets; fs_read and diff them\">\n"
                         + "\n".join(f"- {p.relative_to(sh.project_root())}" for p in prev)
                         + "\n</prior_config_rolls>")
        linker = _linker_fact_note(aid)
        if linker:
            parts.append("<sheet_reference_facts note=\"structural facts from the previous "
                         "sheet; individually normal, diagnostic only in conjunction with the "
                         "device echo\">\n" + linker + "\n</sheet_reference_facts>")
        # 矛盾案(单跑过/连跑挂)明示对照——归因定向的重编不许无差别改卷
        n_contra = F.contradictions(mine, aid)
        contra = ("\nThis case passed in isolation but failed in the full-volume run — "
                  "suspect cross-case interference via persistent state (saved files / peer "
                  "sync / segments) before rewriting anything; prefer making the case "
                  "self-contained (own artifact names, head/tail cleanup of its own channel)."
                  if n_contra else "")
        # 冻结注(V6 override 换法通道的 brief 面):同法已证伪,必须换法
        frozen_note = ("\nThe same-signature fix has FAILED twice on this sheet — that "
                       "approach is falsified. You must change the method (the emit gate "
                       "will require an override_frozen_reason declaring what changed)."
                       if F.frozen(mine, aid) else "")
        # 导出修法注入(§11.7:引擎导出,worker 按引用现查手册落地,零写死命令)
        remedy_note = ""
        if remedy:
            refs = "; ".join(str(r) for r in (remedy.get("refs") or [])[:2])
            remedy_note = ("\n<derived_remedy>\naction: " + str(remedy.get("action"))
                           + (f"\nchannel: {remedy.get('channel')}" if remedy.get("channel") else "")
                           + (f"\nobligation: {remedy.get('obligation')}" if remedy.get("obligation") else "")
                           + (f"\ndirection: {str(remedy.get('direction'))[:300]}" if remedy.get("direction") else "")
                           + (f"\nmanual_refs: {refs}" if refs else "")
                           + "\nThis remedy is derived from the persistence-channel grammar and "
                             "the attribution history — implement it this round (look up exact "
                             "command forms in the manual refs; do not invent them).\n</derived_remedy>")
        tail.append(
            f"<round_task>\nRecompile round (previous on-device runs failed; thinking depth is max"
            + ("; FINAL attempt" if rounds_used >= max_rounds - 1 else "") + ")."
            + contra + frozen_note + remedy_note + "\n"
            "Before adopting any prior attribution, answer independently against each round's "
            "device echo: did the config realize the intent (is the observed form the kind the "
            "intent asks for)? A wrong form with a right-looking assertion usually means config "
            "structure (missing object / dangling reference / wrong binding), not syntax polish."
            "\n</round_task>")

    atts = [f for f in mine if f.get("ev") == "attribution"]
    if atts and str(atts[-1].get("disposition")) == "defect_candidate":
        tail.append(
            "<round_task>\nLast round suspected a product defect, but one failure of one config "
            "form cannot establish a defect. This round: implement the same intent with a "
            "DIFFERENT config form (different mechanism/object structure — retrieve same-intent "
            "precedents first), then let on-device decide. Reproduction under a different form "
            "is what certifies the defect; a pass certifies it was a form problem.\n</round_task>")

    intent = intent_summary(aid, state)
    if intent:
        parts.append("<intent note=\"this case's intent; full text at manifest_path\">\n"
                     + intent + "\n</intent>")
    return "\n".join(parts + tail)
