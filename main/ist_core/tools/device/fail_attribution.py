"""四层归因（V3 步骤5，论文 §5.4：fail 四分 G错/E错/V错/瞬态，各层独立 §4.7+§3.10 正交）。

把一个上机 fail 的 check_point 归到 G/E/V/瞬态四层之一，并按层路由回流：
- G错：命令骨架不全/非法（配置没生效、命令报错）→ 回 draft 重编 G 段。
- E错：IP 不可达/配错（dig 无解析、连接失败）→ 回 draft 重绑 E 段。
- V错：断言语义值错（有回显但断言期望值不对）→ 回 draft 重写 V 段断言。
- 瞬态：SSH 中断/dig 超时/NXDOMAIN/网络抖动 → **不回流**（与编译质量无关，§5.4 第四类）。

设计：归因优先用 provenance（断言步的 layer/source）+ 框架真实裁决明细的确定性信号
（瞬态关键词、dig 解析失败、配置报错）。无 provenance 时退化到只看裁决明细。
这是**确定性分类器**，不替代 verify agent 的语义判断——agent 用它做初分，再人工核对。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from langchain_core.tools import tool

# G/E/V/transient 是归因体系的层；attribute_fail 机械预判只产出 G(^ 拒绝) 或
# undetermined(待 LLM 归因)——E/V/transient 由 LLM 基于 device_context 原文判。
AttrLayer = Literal["G", "E", "V", "transient", "undetermined"]

# 归因机械预判只认**一个协议级事实**：设备语法拒绝标记 ``^``（独行，空格对齐指向
# 上一行出错 token）——设备明确说"这条命令我不认"，确定无疑、上下文无关。
#
# 曾经这里有三张 marker 关键字表（瞬态/E/G）做预归因，已删——那是强字典猜语义
# （B/C 层伪装成 A 层），实证两类误归都发生了（2026-07-02 E2E）：
# - 裸 "dig" 把「context 里出现过 dig 命令」当 E 可达性失败，抢掉共存的
#   "failed to execute"（994928 配置被拒却归 E）；
# - "timed out" 把配置错引发的 dig 超时归瞬态不回流（5 个"瞬态"下一轮 100% 复现）。
# 设备真实回显直接交给 LLM，它看得明白；错误的预归因反而带偏（错误预标签
# 会显著拉低 LLM 归因准确率）。


# 文件级崩溃签名：某断言让框架 test_xlsx 分派崩 → 整份文件后续 case 全不跑（unknown 级联）。
# 这类是**编译缺陷**（emit 产出了框架 xlsx 流不支持的断言），**不是框架 bug**、也不是各 case
# 各自失败——修在**编译侧**（重编移除/替换该断言），不是"改框架"、更不是"逐 case 排查"。
# 知识源同 structural_gate._check_no_found_times（emit 侧本有拒绝门，但 opt-in 漏网时靠这里兜底）。
_CRASH_SIGNATURES = [
    # (traceback 子串小写, 断言名, 崩因 + 正解)
    ("found_times() missing", "found_times",
     "found_times is unsupported by the framework xlsx flow (check_point dispatch passes only "
     "2 args, no times) → TypeError crashes the whole file, later cases never run. Correct fix: "
     "**recompile** these cases' found_times into found (presence) / abs_found (literal) — "
     "'exactly N times' cannot be expressed in this framework; a compilation defect, not a "
     "framework bug, no framework change needed."),
]


def attribute_file_crash(framework_traceback: str):
    """从 framework_traceback 认已知**文件级崩溃**签名（编译产出了框架不支持的断言）。

    返回 (断言名, 崩因+正解) 或 None（未识别的崩溃——泛型"文件级崩溃，定位崩溃断言重编"）。
    这类崩溃使整份 pytest 中断 → 崩溃点之后所有 case 显 unknown（级联，非各自失败）。
    """
    tb = (framework_traceback or "").lower()
    for sig, name, guide in _CRASH_SIGNATURES:
        if sig in tb:
            return name, guide
    return None


@dataclass
class AttributionResult:
    """一个 fail 的机械预判结果（G=设备语法拒绝确定 / undetermined=待 LLM 归因）。"""
    layer: AttrLayer
    reason: str
    reflow: bool          # 是否回流重编译（undetermined 默认 True，最终由 LLM 归因定）
    target_layer: str     # 回流给 draft 改哪层（G/E/V；未定为空）

    def render(self) -> str:
        if self.layer == "undetermined":
            flow = (f"reflow target candidate: layer {self.target_layer} (provenance)" if self.target_layer
                    else "reflow decision pending attribution")
        else:
            flow = f"reflow → layer {self.target_layer}" if self.reflow else "no reflow"
        return f"[{self.layer}] {self.reason} | {flow}"


def has_device_syntax_caret(text: str) -> bool:
    """设备语法拒绝标记：一行只有空白 + 单个 ``^``（对齐指向上一行出错 token）。"""
    return any(ln.strip() == "^" for ln in (text or "").splitlines())


def caret_rejected_commands(text: str, limit: int = 3) -> list[str]:
    """抽出被 ``^`` 拒绝的命令原文（^ 独行的上一非空行），供摘要给证据切片。"""
    out: list[str] = []
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == "^":
            for j in range(i - 1, -1, -1):
                prev = lines[j].strip()
                if prev:
                    out.append(prev[:120])
                    break
            if len(out) >= limit:
                break
    return out


def attribute_fail(verdict_detail: str, *, failing_assertion_layer: str = "",
                   failing_assertion_source_kind: str = "") -> AttributionResult:
    """fail 的机械预判——**只认一个协议级事实，其余不猜**。

    - device_context 里有设备语法拒绝标记 ``^``（独行对齐）→ **G**：配置/命令未被设备
      接受，确定无疑；且它是上游根因——同 case 后续 dig 无解析、断言不中、超时多为
      下游后果，先修 G。
    - 没有 ``^`` → **undetermined**：不做关键字猜测，把 device_context 原文交给 LLM
      归因（设备会话原文 / dig 输出 / 框架 traceback，LLM 看得明白）。曾经的
      瞬态/E/G marker 关键字表已删——错误预归因实证会带偏（见文件头注释）。

    verdict_detail: 框架真实裁决明细（逐 check_point 报错原文 / dig 输出 / SSH 异常）。
    failing_assertion_layer: 失败断言在 provenance 里的 layer（G/E/V），undetermined
        时作为回流目标**候选**提示（非结论）。
    failing_assertion_source_kind: 失败断言来源 kind（保留参数，当前不参与判定）。
    """
    if has_device_syntax_caret(verdict_detail):
        cmds = caret_rejected_commands(verdict_detail, limit=1)
        evid = f"rejected command: {cmds[0]}" if cmds else "see the ^-aligned line in device_context"
        return AttributionResult(
            "G",
            f"Device syntax rejection (^) — {evid}. The config was not accepted; later resolution/assertion failures in the same case are mostly downstream consequences — fix this first.",
            reflow=True, target_layer="G")
    tl = failing_assertion_layer if failing_assertion_layer in ("G", "E", "V") else ""
    return AttributionResult(
        "undetermined",
        "No pre-judgement — attribute from the raw device_context (device session / dig output / framework traceback). "
        "Transient criterion: disappears on a later re-run; same-signature fails in two consecutive rounds are never transient.",
        reflow=True, target_layer=tl)


@tool(parse_docstring=True)
def compile_attribute(verdict_detail: str, failing_assertion_layer: str = "",
                      failing_assertion_source_kind: str = "") -> str:
    """Mechanical pre-judgement of an on-device fail: only the device syntax rejection ``^`` is trusted; everything else is yours to attribute.

    - Returns layer="G": the device_context carries the device ``^`` rejection marker
      (protocol-level deterministic fact) — the config/command was not accepted; fix it
      first, since later parse/assertion failures in the same case are usually downstream
      consequences.
    - Returns layer="undetermined": **no guessing was done**. Read verdict_detail / that
      case's device_context verbatim in last_run.json and judge E (reachability/environment),
      V (assertion expectations), transient (vanishes on a later rerun; same-signature fails
      two rounds in a row are NOT transient), or a product defect yourself.

    Args:
        verdict_detail: the framework's real ruling detail (that check_point's error text /
            dig output / SSH exception).
        failing_assertion_layer: the failing assertion's provenance layer (G/E/V, optional);
            on undetermined it is surfaced as a reflow-target hint.
        failing_assertion_source_kind: the failing assertion's source kind (optional, reserved).

    Returns:
        JSON string {"layer","reason","reflow","target_layer","render"}.
    """
    r = attribute_fail(verdict_detail,
                       failing_assertion_layer=failing_assertion_layer,
                       failing_assertion_source_kind=failing_assertion_source_kind)
    return json.dumps({
        "layer": r.layer, "reason": r.reason, "reflow": r.reflow,
        "target_layer": r.target_layer, "render": r.render(),
    }, ensure_ascii=False)



@tool(parse_docstring=True)
def submit_attribution(xlsx_path: str, autoid: str, layer: str,
                       disposition: str, evidence: str,
                       fix_direction: str = "",
                       defect_candidate: dict | None = None) -> str:
    """Land your attribution **conclusion** for one failed case into last_run.json (the judgement itself is still yours, made from the raw evidence).

    **When to use**: the raw device evidence has been read and the layer verdict has formed —
    attribution only counts once landed; the engine does not read prose conclusions.
    **When not to use**: if evidence is insufficient to pick a layer, do not force one — land
    it anyway with disposition=reflow and fix_direction saying "insufficient evidence, need
    observation X" (an honest underdetermination beats a wrong certainty).

    Why land it: conclusions living only in session text break the chain — the next round's
    digest guard "attributed transient last round, recurred this round = misattribution"
    reads the landed fields (without them that guard is dead code); the frozen-same-approach
    check needs last round's fix record; defect candidates that never land cannot be rolled
    up into a defect list after multi-round verification.

    evidence shape (gate-checked): must be a **verbatim substring** of that case's
    device_context/causality — copy one piece character-for-character, no retelling or
    rewriting (multi-line snippets get mangled by parameter escaping; a single line is safest).

    Args:
        xlsx_path: the case.xlsx run this round (locates the sibling last_run.json).
        autoid: the attributed case's full autoid (must exist in last_run.json).
        layer: one of five — G (device syntax rejection), E (environment/IP), V (assertion vs
            behavior mismatch), transient (non-reproducible), product_defect (suspected).
            If unsure, do not call this tool (undetermined is the default state, no submission needed).
        disposition: one of five — reflow (recompile with feedback), frozen (freeze the
            approach, change direction), env_blocked (environment blocked, finish the run
            first), defect_candidate (defect-candidate form), fixed (fixed, pending rerun).
        evidence: the **verbatim substring** of device_context/causality supporting the
            conclusion (copy, never retell) — validated against the case's landed raw text
            (a standalone ^ line was measurably lost in retelling, causing misattribution).
        fix_direction: fix direction (free text; for reflow/frozen state clearly what should
            change — next round's "same approach?" check relies on it).
        defect_candidate: structured candidate form when disposition=defect_candidate, with
            repro (reproduction steps), expected_with_source (expectation + manual source),
            actual (actual + device evidence), version, optionally ticket_id.

    Returns:
        Confirmation (path written + field echo); error when the autoid is absent from
        last_run or the evidence does not match the raw text.
    """
    from pathlib import Path

    _LAYERS = ("G", "E", "V", "transient", "product_defect")
    _DISPS = ("reflow", "frozen", "env_blocked", "defect_candidate", "fixed")
    layer = (layer or "").strip()
    disposition = (disposition or "").strip()
    if layer not in _LAYERS:
        return f"error: layer must be one of {'/'.join(_LAYERS)}, got {layer!r}"
    if disposition not in _DISPS:
        return f"error: disposition must be one of {'/'.join(_DISPS)}, got {disposition!r}"
    ev = (evidence or "").strip()
    if not ev:
        return "error: evidence is required — copy a supporting snippet verbatim from device_context/causality"

    try:
        from main.ist_core.tools.deepagent.file_tools import _resolve_inside_root
        xp = _resolve_inside_root(xlsx_path, must_exist=True)
    except Exception:  # noqa: BLE001
        xp = None
    p = Path(xp) if xp else Path(xlsx_path)
    lr = p.parent / "last_run.json"
    if not lr.is_file():
        return f"error: last_run.json does not exist: {lr} (run dev_run_batch_digest first)"
    try:
        records = json.loads(lr.read_text(encoding="utf-8"))
        assert isinstance(records, list)
    except Exception as e:  # noqa: BLE001
        return f"error: failed to read last_run.json: {e}"

    aid = (autoid or "").strip()
    rec = next((r for r in records if isinstance(r, dict) and str(r.get("autoid")) == aid), None)
    if rec is None:
        have = [str(r.get("autoid")) for r in records if isinstance(r, dict)][:8]
        return f"error: autoid {aid} not in last_run.json (present: {', '.join(have)}…)"

    corpus = "\n".join(str(rec.get(k) or "") for k in
                       ("device_context", "causality", "detail_tail", "framework_traceback"))

    # 归一化比对(2026-07-05 v12 实证):evidence 经 tool-arg 通道传输,控制字符必失真
    # ——设备原文含真实 \r\n,LLM 复制到参数里成了字面 "\\r\\n" 转义(连拒 4 次同一形态)。
    # 门的目的在防**编造/转述**,不在字节级保真:两侧都做「字面转义还原 + 空白折叠」后
    # 再查子串,防伪性不变(编的内容归一化后照样对不上),序列化失真不再误拒。
    def _norm(s: str) -> str:
        s = s.replace("\\r", " ").replace("\\n", " ").replace("\\t", " ")
        s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        return " ".join(s.split())

    if ev not in corpus and _norm(ev) not in _norm(corpus):
        return ("error: evidence is not a substring of this case's landed raw text — **copy it "
                "directly** from that autoid's device_context/causality in last_run.json, never "
                "retell or rewrite (retelling measurably lost a standalone ^ line and caused "
                "misattribution). Multi-line snippets get mangled by parameter escaping: quote a "
                "key fragment **within a single line** instead (whitespace is normalized, no "
                "byte-exact cross-line alignment needed).")

    import time as _time
    entry = {
        "layer": layer,
        "disposition": disposition,
        "evidence": ev[:2000],
        "fix_direction": (fix_direction or "").strip(),
        "ts": _time.time(),
        "round": rec.get("_round"),
    }
    if disposition == "defect_candidate":
        dc = defect_candidate if isinstance(defect_candidate, dict) else {}
        missing = [k for k in ("repro", "expected_with_source", "actual") if not str(dc.get(k, "")).strip()]
        if missing:
            return f"error: defect_candidate missing required fields: {', '.join(missing)}"
        entry["defect_candidate"] = dc
    rec["_attribution"] = entry
    try:
        lr.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"error: write failed: {e}"
    return (f"attribution landed at {lr}\nautoid={aid} layer={layer} disposition={disposition}"
            + (f" fix_direction={entry['fix_direction'][:60]}" if entry["fix_direction"] else ""))
