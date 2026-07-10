"""用户面渲染层(DESIGN §11:一切叙事 = 事实流的确定性投影;渲染时刻零 LLM)。

三条纪律:
1. 与 engine_report 同一 fold(数字可被视图重算复核,INV-1 扩展到人话报告);
2. LLM 产的人话只取归因事实的 user_note 字段(判断时刻落账),渲染不生成;
3. 零术语泄漏:状态/语境/层/处置走人话词表,英文枚举与指纹哈希不出用户面。

修法段是判定式(§11.7):由 remedies.derive_queue 导出,唯一导出即陈述不设选项;
已排除方向列「已排除及理由」;止损只作为用户已做裁决的如实记录出现。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

# ── 人话词表(用户面模板内容,语言分层的既定例外;机器枚举 → 中文) ────────────────

STATUS_CN = {
    "deliverable": "验证通过",
    "subset_verified": "单独验证通过(待整卷复验)",
    "authored": "已编写(未上机)",
    "failed": "上机未通过",
    "contradicted": "单独能过、整卷复验会挂(用例间相互干扰)",
    "failed_terminal": "按裁决收尾(未通过卷)",
    "escalated": "引擎无法继续(需人工)",
    "awaiting_user": "等待你的决定",
    "suspended": "挂起(下批继续)",
    "pending": "未开始",
}
CTX_CN = {"delivery": "整卷连跑复验", "subset": "单独验证"}
LAYER_CN = {"G": "设备拒绝了命令(语法/能力)", "E": "环境/测试床问题",
            "V": "设备真实行为与断言不符", "transient": "偶发波动(重跑消失)",
            "product_defect": "疑似产品缺陷"}
DISP_CN = {"reflow": "带反馈重新编写", "frozen": "原方法已证无效,换法重编",
           "env_blocked": "按环境阻塞收尾", "defect_candidate": "缺陷候选(需换形态坐实)",
           "fixed": "已修复待复跑", "rerun_isolated": "卷面无嫌疑,隔离复跑对照"}
ACTION_CN = {
    "self_cleanup": "让这个用例结束时清理自己留下的持久产物",
    "recompile_directed": "按已找到的方向重新编写",
    "rerun_isolated": "不改卷面,单独复跑对照确认",
    "vary_form": "换一种配置形态实现同一意图(坐实/排除产品缺陷)",
}
CHANNEL_CN = {"local_disk": "本机保存的配置文件/快照", "peer_node": "同步到对端设备的配置",
              "segment_fs": "分区配置文件残留", "ha_sync_state_x_config_reload": "HA同步与配置装载互斥"}

_TS_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} +[\d.]+ +- +")


def clean_device_echo(text: str, limit: int = 0) -> str:
    """设备回显给人看的清理(仅展示层;喂 LLM 的原文一字不动——V6 契约原样继承)。"""
    lines, blank = [], False
    for ln in str(text or "").splitlines():
        ln = _TS_PREFIX.sub("", ln).rstrip()
        if not ln:
            if blank:
                continue
            blank = True
        else:
            blank = False
        lines.append(ln)
    out = "\n".join(lines).strip()
    return out[:limit] if limit > 0 else out


# ── 时间线:verdict/authored/decision 事实 → 人话(机械翻译,零判断) ──────────────


def case_timeline(mine: list[dict]) -> list[str]:
    out: list[str] = []
    for f in mine:
        ev = f.get("ev")
        if ev == "authored":
            r = int(f.get("round") or 0)
            out.append(f"第 {r} 次编写完成" + ("(重新编写)" if r > 1 else ""))
        elif ev == "verdict":
            ctx = CTX_CN.get(str(f.get("ctx")), str(f.get("ctx")))
            out.append(f"{ctx}:{'通过' if f.get('result') == 'pass' else '未通过'}")
        elif ev == "rollback":
            out.append("此前的通过结论被复验推翻,已从先例知识库撤销")
        elif ev == "decision" and f.get("answer"):
            out.append(f"你的裁决:{f.get('answer')}")
        elif ev == "suspended":
            out.append("挂起,留待下批继续")
    return out


def _latest_attribution(mine: list[dict]) -> dict:
    atts = [f for f in mine if f.get("ev") == "attribution"]
    return atts[-1] if atts else {}


def diagnosis_text(mine: list[dict]) -> str:
    """怎么判断的:优先 user_note(归因时刻落账的中文);缺则词表+引文对照兜底。"""
    att = _latest_attribution(mine)
    if not att:
        return "本轮收口前未能完成原因分析(证据在案,可续跑补齐)。"
    note = str(att.get("user_note") or "").strip()
    parts = []
    if note:
        parts.append(note)
    else:
        cn = LAYER_CN.get(str(att.get("layer") or ""), "")
        if cn:
            parts.append(f"判断:{cn}。")
    dq, vq = str(att.get("doc_quote") or "").strip(), str(att.get("device_quote") or "").strip()
    if dq or vq:
        pair = []
        if dq:
            pair.append(f"资料记载:「{dq[:200]}」")
        if vq:
            pair.append(f"实机表现:「{clean_device_echo(vq, 200)}」")
        parts.append(";".join(pair) + "。")
    elif att.get("evidence"):
        parts.append(f"关键证据:「{clean_device_echo(str(att.get('evidence')), 200)}」。")
    return " ".join(parts) or "(证据在案,见事实台账)"


def remedy_text(queue: list[dict], mine: list[dict]) -> str:
    """修复方案段(判定式):队列头=唯一导出修法,陈述句;队列空=如实说明所处终局。"""
    if queue:
        head = queue[0]
        act = ACTION_CN.get(str(head.get("action")), str(head.get("action")))
        line = f"**修复方案**:{act}"
        if head.get("channel"):
            line += f"(涉及:{CHANNEL_CN.get(str(head['channel']), head['channel'])})"
        refs = head.get("refs") or []
        if refs:
            line += f"。依据:{';'.join(str(r) for r in refs[:2])}"
        if head.get("direction"):
            line += f"。方向:{str(head['direction'])[:160]}"
        rest = [ACTION_CN.get(str(q.get("action")), "") for q in queue[1:]]
        if any(rest):
            line += f"。若仍未通过,后续依次:{'、'.join(r for r in rest if r)}"
        return line + "。"
    att = _latest_attribution(mine)
    disp = str(att.get("disposition") or "")
    if disp == "defect_candidate":
        return "**结论**:多种形态下复现,按产品缺陷跟进(缺陷候选单已列)。"
    if disp == "env_blocked":
        dec = [f for f in mine if f.get("ev") == "decision" and f.get("answer")]
        who = f"(依据你的裁决「{dec[-1].get('answer')}」)" if dec else ""
        return f"**结论**:按环境/取舍收尾{who},该用例记入未通过卷,下批可继续。"
    return "**状态**:引擎侧修法已试尽,已在问询/挂起流程中,等待你的输入。"


# ── 报告生成 ─────────────────────────────────────────────────────────────────


def _case_section(aid: str, c: dict, mine: list[dict], mcase: dict,
                  queue: list[dict]) -> list[str]:
    title = str(mcase.get("title") or "")
    out = [f"## {title or ('用例 …' + aid[-6:])}",
           f"- 编号 `{aid}` · 状态:{STATUS_CN.get(str(c.get('status')), c.get('status'))}"
           f" · 编写 {c.get('rounds')} 次"]
    tl = case_timeline(mine)
    if tl:
        out.append("\n**发生了什么**:" + "→ ".join(tl) + "。")
    out.append("\n**怎么判断的**:" + diagnosis_text(mine))
    out.append("\n" + remedy_text(queue, mine))
    return out


def render_delivery_report(report: dict, fs: list[dict], manifest: dict,
                           queues: dict[str, list[dict]]) -> str:
    """delivery_report.md 全文(判定式三段;数字与 engine_report 同源)。"""
    t = report.get("totals", {})
    ok = int(t.get("deliverable") or 0)
    total = int(t.get("cases") or 0)
    mcases = {str(c.get("autoid")): c for c in (manifest.get("cases") or [])}
    lines = [f"# 交付报告 — {manifest.get('source') or report.get('batch', '')}",
             f"> 生成 {time.strftime('%Y-%m-%d %H:%M', time.localtime())}",
             "",
             f"本批 {total} 个用例:**{ok} 个通过整卷复验,已入交付卷**"
             + (f";其余 {total - ok} 个的情况逐一说明如下。" if total > ok else "。"), ""]
    moved = report.get("moved_tail") or []
    if moved:
        names = [str((mcases.get(a) or {}).get("title") or ("…" + a[-6:])) for a in moved]
        lines.append(f"- 有 {len(moved)} 个用例会在设备上留下跨用例存活的配置(保存/同步类),"
                     f"已按规则排到卷尾执行:{'、'.join(names)}")
    if report.get("coexist_violations"):
        lines.append("- ⚠ 本卷存在官方标注互斥的操作组合,已在组卷时检查并声明(详见机读报告)")
    bad = {a: c for a, c in (report.get("cases") or {}).items()
           if c.get("status") != "deliverable"}
    if bad:
        lines.append("")
        for aid, c in sorted(bad.items()):
            mine = [f for f in fs if str(f.get("aid")) == aid]
            lines += _case_section(aid, c, mine, mcases.get(aid) or {},
                                   queues.get(aid) or [])
            lines.append("")
    lines.append("---")
    lines.append("交付物:`case.xlsx`(通过卷)"
                 + ("、`unsuccessful_cases.xlsx`+`unsuccessful_cases.md`(未通过卷与详报)" if bad else "")
                 + "、`engine_report.json`(机读)。全部过程事实在 `facts.jsonl`,可审计可续跑。")
    return "\n".join(lines) + "\n"


def render_unsuccessful_md(report: dict, fs: list[dict], manifest: dict,
                           queues: dict[str, list[dict]],
                           evidence: dict[str, str]) -> str:
    """未通过卷详报:每案三段式 + 脑图原文 + 关键设备回显(清理后)。"""
    mcases = {str(c.get("autoid")): c for c in (manifest.get("cases") or [])}
    bad = {a: c for a, c in (report.get("cases") or {}).items()
           if c.get("status") != "deliverable"}
    lines = [f"# 未通过用例详报 — {manifest.get('source') or ''}",
             f"> 生成 {time.strftime('%Y-%m-%d %H:%M', time.localtime())} · 共 {len(bad)} 个",
             ""]
    for aid, c in sorted(bad.items()):
        mine = [f for f in fs if str(f.get("aid")) == aid]
        mc = mcases.get(aid) or {}
        lines += _case_section(aid, c, mine, mc, queues.get(aid) or [])
        sis = mc.get("step_intents") or []
        if sis:
            lines.append("\n**脑图原始用例**:")
            for si in sis:
                d, e = str(si.get("desc") or ""), str(si.get("expected") or "")
                lines.append(f"- {d}" + (f" → 预期:{e}" if e else ""))
        ev = evidence.get(aid) or ""
        if ev:
            lines.append("\n**最后一次设备关键回显**(已剥时间戳,原文在事实台账):")
            lines.append("```\n" + clean_device_echo(ev, 1500) + "\n```")
        lines.append("")
    return "\n".join(lines) + "\n"


# ── 报告机械门:零术语泄漏(测试与 closing 断言共用) ───────────────────────────

_LEAK = re.compile(
    r"\b(deliverable|contradicted|failed_terminal|subset_verified|awaiting_user|escalated|"
    r"reflow|env_blocked|defect_candidate|rerun_isolated|delivery|subset)\b"
    r"|\b[0-9a-f]{16}\b")


def leak_scan(text: str) -> list[str]:
    """返回用户面文本中泄漏的内部术语/指纹(应为空;code fence 内的设备回显豁免)。"""
    out, in_fence = [], False
    for ln in str(text or "").splitlines():
        if ln.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or ln.strip().startswith("`") and ln.strip().endswith("`"):
            continue
        for m in _LEAK.finditer(re.sub(r"`[^`]*`", "", ln)):
            out.append(m.group(0))
    return out
