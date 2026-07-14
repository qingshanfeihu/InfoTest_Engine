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
    """逐轮失败证据:verdict(fail) 事实 + 其 evidence_ref 指向的 last_run 里该案原文。
    非末轮的 device_context 由调用方降级为 ref 引用(载荷按引用,X8)。"""
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
        anom = list(rec.get("anomaly_lines") or [])[:5] if ref else []
        docs.append({"run_id": f.get("run_id"), "ctx": f.get("ctx"), "ref": ref,
                     "device_context": ctxt, "anomaly": anom,
                     "layer": att.get("layer", ""), "disposition": att.get("disposition", ""),
                     "fix_direction": att.get("fix_direction", "")})
    return docs


def build_brief(aid: str, state: dict, fs: list[dict]) -> str:
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
        # 载荷按引用(X8 效率债):只有最新失败轮的回显全文内联;更早轮给归因结论行
        # +引用路径(需要时 fs_read 现查)——旧版全轮内联 6000 字符/轮随轮数线性膨胀
        evs = _round_evidence(fs, aid)
        docs = []
        for i, e in enumerate(evs):
            sig = "/".join(x for x in (e["layer"], e["disposition"]) if x)
            head = (f'<document label="on-device run {e["run_id"]}" ctx="{e["ctx"]}"'
                    + (f' attribution="{sig}"' if sig else "") + ">\n"
                    + (f"<fix_direction>{e['fix_direction'][:800]}</fix_direction>\n"
                       if e["fix_direction"] else ""))
            # 执行失败行显式高亮(echo-grounding 编译侧对偶,2026-07-13):device_context
            # 里的失败机理行(如 write all 撞文件的 Failed to execute)埋在长回显里易被
            # worker 忽略——独立提到最前,让重编时先看到「上一版是自身执行失败」
            anom_block = (f"<execution_failures note=\"YOUR previous sequence hit these on "
                          f"device — fix the sequence, not the bed\">\n"
                          + "\n".join(str(a) for a in e["anomaly"])
                          + "\n</execution_failures>\n") if e.get("anomaly") else ""
            if i == len(evs) - 1:
                docs.append(head + anom_block + f"<device_context>\n{e['device_context']}\n"
                            "</device_context>\n</document>")
            else:
                docs.append(head + anom_block + f"<device_context ref=\"{e['ref']}\" note=\"earlier "
                            "round; fs_read the ref if the latest echo is not enough\"/>\n"
                            "</document>")
        if docs:
            parts.append("<device_evidence>\n" + "\n".join(docs) + "\n</device_evidence>")
        hist_dir = sh.outputs_root() / aid / "history"
        prev = sorted(hist_dir.glob("case.r*.xlsx")) if hist_dir.is_dir() else []
        if prev:
            parts.append("<prior_config_rolls note=\"previous config sheets; fs_read and diff them\">\n"
                         + "\n".join(f"- {p.relative_to(sh.project_root())}" for p in prev)
                         + "\n</prior_config_rolls>")
        # 矛盾案(单跑过/连跑挂)明示对照——归因定向的重编不许无差别改卷
        n_contra = F.contradictions(mine, aid)
        contra = ("\nThis case passed in isolation but failed in the full-volume run — "
                  "suspect cross-case interference via persistent state (saved files / peer "
                  "sync / segments) before rewriting anything; prefer making the case "
                  "self-contained (own artifact names, head/tail cleanup of its own channel)."
                  if n_contra else "")
        # 自身执行失败引导(污点二落地,2026-07-13):上一版回显有执行失败行时,失败在
        # 本案自己的命令序列(交互确认吃掉下条命令/加载全配置冲突/保存撞已存在文件),
        # 不是床污染——引导 worker 查序列本身(C 层指方向,不写具体命令)
        exec_fail = ("\nThe previous run has execution-failure lines (see <execution_failures>): "
                     "the fault is in THIS case's own command sequence, not the testbed. Common "
                     "sequence faults: a command that triggers an interactive confirmation (e.g. "
                     "overwrite/Type-YES) with no confirmation step after it, so the next command "
                     "is consumed as the answer and the stream desyncs; loading whole-config that "
                     "conflicts with the running interface state; a save colliding with an existing "
                     "file. Retrieve a precedent of the SAME intent that ran clean and match its "
                     "command forms; do not treat this as bed cleanup."
                     if any(e.get("anomaly") for e in evs) else "")
        tail.append(
            f"<round_task>\nRecompile round (previous on-device runs failed; thinking depth is max"
            + ("; FINAL attempt" if rounds_used >= max_rounds - 1 else "") + ")."
            + contra + exec_fail + "\n"
            "Before adopting any prior attribution, answer independently against each round's "
            "device echo: did the config realize the intent (is the observed form the kind the "
            "intent asks for)? A wrong form with a right-looking assertion usually means config "
            "structure (missing object / dangling reference / wrong binding), not syntax polish."
            "\n</round_task>")

    # ought-裁决注入(§11.11):panel 呈报获用户答案后,重编 brief 携带差异原文+
    # 引擎理解+用户裁决——confirm=按理解 Z 编;correct=用户纠正原文是最高权威;
    # adopted=同键历史判例背书(引擎机械采信,免问),裁决正文同样下发。
    pf = [f for f in mine if f.get("ev") == "ask_panel"]
    if pf:
        prnd = int(pf[-1].get("round") or 0)
        dec = next((d for d in reversed(mine) if d.get("ev") == "decision"
                    and str(d.get("question_id")) == f"panel:{aid}:{prnd}"), None)
        adopt = next((d for d in reversed(mine) if d.get("ev") == "adopted"
                      and int(d.get("round") or 0) == prnd), None)
        ruling = None
        if dec and str(dec.get("token")) in ("confirm", "correct"):
            ruling = (str(dec.get("token")), str(dec.get("answer") or "")[:500],
                      "The user answered this batch.")
        elif adopt:
            ruling = (str(adopt.get("token")), str(adopt.get("ruling") or "")[:500],
                      f"Adopted from a prior same-key user adjudication "
                      f"({adopt.get('slug')}) — device behavior still matches its record.")
        if ruling:
            panel = sh.read_json(sh.project_root() / str(pf[-1].get("ref") or ""), {}) or {}
            side_lines = "\n".join(
                f"- [{s.get('source_ref')}] {str(s.get('quote'))[:300]}"
                for s in (panel.get("sides") or [])[:4])
            tok, answer, provenance = ruling
            adj = {"confirm": "The ruling CONFIRMS the hypothesis below — compile per it.",
                   "correct": "The ruling CORRECTS the hypothesis — the ruling text below "
                              "overrides it and is the highest authority on intent."}
            parts.append(
                "<user_adjudication>\n"
                f"A discrepancy was reported ({panel.get('conflict_shape')}):\n{side_lines}\n"
                f"Engine hypothesis: {str(panel.get('hypothesis') or '')[:500]}\n"
                f"Ruling: {answer}\n({provenance})\n"
                f"{adj.get(tok, adj['confirm'])}\n"
                "</user_adjudication>")

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
    # F8a 兄弟上下文(§18.11):脑图组是语义单元——同组 siblings 的 title 一行式内联
    # (manifest 原文=事实性证据,机械注入;X8:check/期望值**不内联**只按引用,防
    # precedent-then-assert 近亲锚定,评审 D14/D15)。worker 据此先陈述组共享 claim
    # 与本案变体轴(F7 组感知措辞),变体撞车在编写期即可见(668030≡668000 型)。
    m = sh.manifest(state)
    me = next((c for c in (m.get("cases") or [])
               if str(c.get("autoid")) == aid), None)
    gp = tuple((me or {}).get("group_path") or ())
    if gp:
        sibs = [c for c in (m.get("cases") or []) if c is not me
                and tuple(c.get("group_path") or ()) == gp]
        if sibs:
            lines = "\n".join(
                f"- …{str(c.get('autoid'))[-6:]}: "
                + str(c.get("title") or "").splitlines()[0][:80]
                for c in sibs[:12])
            more = f"\n(+{len(sibs) - 12} more in this group)" if len(sibs) > 12 else ""
            parts.append(
                "<siblings note=\"same mindmap group = one shared claim with per-case "
                "variant axes. State the group claim and THIS case's variant axis before "
                "writing steps; do NOT copy siblings' expectations (their full text lives "
                "at manifest_path if needed)\">\n" + lines + more + "\n</siblings>")
    # F6(§18.11):意图侧禁令机制标记随 brief 下发——worker 走要点先行(等价推导+
    # compile_report_underdetermined 呈报),emit 硬门在 user_decision.json 落盘前拒落卷。
    fm = (sh.read_json(sh.outputs_root() / aid / "intent.json", {}) or {}).get(
        "forbidden_mechanism")
    if fm and not (sh.outputs_root() / aid / "user_decision.json").is_file():
        toks = ", ".join(sorted({str(h.get("matched")) for h in fm if isinstance(h, dict)}))
        tail.append(
            "<forbidden_mechanism matched=\"" + toks + "\">\n"
            "The intent names a bed-forbidden mechanism. Do NOT author steps yet: follow "
            "'State the test point first' — derive the closest equivalent under the "
            "config-plane model and report it via compile_report_underdetermined "
            "(claim_kind=forbidden_mechanism, reason = intent mechanism + proposed "
            "equivalent + declared differences). The emit gate refuses to land this case "
            "until the user's ruling is on disk. If the matched word is not actually an "
            "execution mechanism of this case (e.g. a counter/statistic name), say so in "
            "the report — the user clears it in one answer.\n"
            "</forbidden_mechanism>")
    return "\n".join(parts + tail)
