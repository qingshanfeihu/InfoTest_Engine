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

    # D9 注入措辞去事实化(2026-07-16,777976 洗白链取证驱动):上轮归因以无假设框
    # 形态注入,worker 逐字采信错误归因把 Hit:0 顺成"步序问题"——标 hypothesis 削盲从;
    # 措辞是 re-verify 不是 distrust(正确归因的定向价值保留)。IST_BRIEF_HYPOTHESIS_MARKUP=0 回退。
    hyp_markup = sh.env_flag("IST_BRIEF_HYPOTHESIS_MARKUP")
    is_retry = rounds_used >= 1
    if is_retry:
        # 载荷按引用(X8 效率债):只有最新失败轮的回显全文内联;更早轮给归因结论行
        # +引用路径(需要时 fs_read 现查)——旧版全轮内联 6000 字符/轮随轮数线性膨胀
        evs = _round_evidence(fs, aid)
        docs = []
        for i, e in enumerate(evs):
            sig = "/".join(x for x in (e["layer"], e["disposition"]) if x)
            _att_attr = (f' attribution="{sig}" status="hypothesis"' if hyp_markup
                         else f' attribution="{sig}"')
            _fix_open = (('<fix_direction confidence="hypothesis" note="prior-round '
                          'attribution — a hypothesis to re-verify against this round\'s '
                          'echo, not established fact">') if hyp_markup
                         else "<fix_direction>")
            head = (f'<document label="on-device run {e["run_id"]}" ctx="{e["ctx"]}"'
                    + (_att_attr if sig else "") + ">\n"
                    + (f"{_fix_open}{e['fix_direction'][:800]}</fix_direction>\n"
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

    # cap 纠正注入(接线包 2g,2026-07-16;样板=panel 的 <user_adjudication>):
    # cap 题面 Other 纠正(token=correct)此前无消费者——granted_rounds 已计其授权,
    # 这里把纠正原文随重编 brief 下发(用户意图最高权威)。panel 裁决已注入时不重复
    # (panel 是更结构化的同权威源,双块并列会稀释)。
    cap_corrections = [d for d in mine if d.get("ev") == "decision"
                       and str(d.get("token")) == "correct"
                       and str(d.get("question_id", "")).startswith("cap:")
                       and str(d.get("answer") or "").strip()]
    if cap_corrections and not (pf and any(
            str(d.get("question_id")) == f"panel:{aid}:{int(pf[-1].get('round') or 0)}"
            for d in mine if d.get("ev") == "decision")):
        parts.append(
            "<user_adjudication>\n"
            "At the retry-budget checkpoint the user gave a correction instead of a "
            "plain continue:\n"
            f"Ruling: {str(cap_corrections[-1].get('answer'))[:500]}\n"
            "(The user answered this batch.)\n"
            "The ruling text above is the highest authority on intent — compile per it.\n"
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
        # D9 意图侧成对措辞(前提洗白链的另一半;设计对抗 §四 D9 裁决):
        # ①expected 是作者预期非设备已证事实(须落地前 ground);②预期仍是断言期望值的
        # **唯一来源**——与实机矛盾走呈报,不得以观察值替换(防 observe-then-assert 滑坡,
        # 「预期以实机为准」是 user 专属裁决)。两句必须成对,单标"未证实"会滑向自决改预期。
        _note = (("this case's intent; the desc lines are the requirement; each `expected:` "
                  "is the author's anticipated outcome, not device-verified fact — ground it "
                  "(manual/precedent/probe) before encoding it as an assertion, and the "
                  "intent stays the sole source of assertion expectations: if device behavior "
                  "contradicts it, file the discrepancy (verifiability/panel) — never "
                  "silently replace the expectation with the observed value; full text at "
                  "manifest_path") if hyp_markup
                 else "this case's intent; full text at manifest_path")
        parts.append(f"<intent note=\"{_note}\">\n" + intent + "\n</intent>")
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
    # §18.13 撤退第一步:意图侧禁令机制**盖章不再进 brief**(旧 <forbidden_mechanism>
    # 块把词表正则命中喂给 worker 当提示,违反「判断用结构化事实,别退化成关键字白名单」
    # 红线——用户判据「不能靠正则匹配」)。worker 改靠 test-point-first prompt 语义自主
    # 判断意图可行性+主动三元组呈报;盖章仍落 intent.json(telemetry)+ emit 门仍读它做
    # 安全 backstop(未主动报→写卷被门拦+三元组引导,不投毒)。第二步:对照轮自主呈报率
    # 达标后删词表+门。
    return "\n".join(parts + tail)
