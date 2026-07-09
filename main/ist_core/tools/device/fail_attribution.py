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
     "found_times 框架 xlsx 流不支持（check_point 分派只传 2 参、缺 times）→ TypeError 崩整份文件、"
     "后续 case 全不跑。正解：**重编**把该 case 的 found_times 改 found(出现即可)/abs_found(字面)——"
     "'恰好 N 次'语义本框架表达不了；这是编译缺陷，非框架 bug、无需改框架。"),
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
            flow = (f"回流目标候选:{self.target_layer}层(provenance)" if self.target_layer
                    else "回流与否待归因后定")
        else:
            flow = f"回流→{self.target_layer}层" if self.reflow else "不回流"
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
    """上机 fail 的机械预判（V3 步骤5）：只认设备语法拒绝 ``^``，其余交你归因。

    - 返回 layer="G"：device_context 里有设备 ``^`` 拒绝标记（协议级确定事实）——
      配置/命令未被设备接受，先修它；同 case 后续解析/断言失败多为下游后果。
    - 返回 layer="undetermined"：**没有做任何猜测**。你直接读 verdict_detail /
      last_run.json 里该 case 的 device_context 原文，自行判 E(可达性/环境)、
      V(断言期望值)、瞬态(换时间重跑即消失;连续两轮同签名 fail 不是瞬态)或产品缺陷。

    Args:
        verdict_detail: 框架真实裁决明细（该 check_point 的报错原文 / dig 输出 / SSH 异常）。
        failing_assertion_layer: 失败断言在 provenance 里的 layer（G/E/V，可空），
            undetermined 时作为回流目标候选提示。
        failing_assertion_source_kind: 失败断言来源 kind（可空，保留参数）。

    Returns:
        JSON 字符串 {"layer","reason","reflow","target_layer","render"}。
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
    """把你对某个 fail case 的归因**结论**落盘进 last_run.json(归因判断本身仍由你读原文做)。

    **何时用**:读完设备证据原文、判层结论已成型时——落盘成功才算归因完成,散文结论引擎不读。
    **何时不用**:证据不足以判层时别硬填一个层凑数——照常落盘,但 disposition=reflow 且
    fix_direction 写"证据不足,需补充观测 X"(诚实的欠定比错误的确定有用)。

    为什么要落盘:结论只留在会话文本里会断链——下一轮 digest 的「上轮归瞬态本轮复现=误归」
    护栏读的是落盘字段(不落盘该护栏是 dead code);「冻结同法重编」的"同法"判定也需要
    上一轮的修法记录;缺陷候选不落盘则多轮验证后无法汇总成缺陷清单。

    evidence 形态(门校验):必须是该 case device_context/causality 的**原文子串**——从你
    摘引的原文里逐字复制一条,不转述不改写(多行片段易被参数转义失真,抄单行最稳)。

    Args:
        xlsx_path: 本轮上机那份 case.xlsx 路径(工具据此定位同目录 last_run.json)。
        autoid: 被归因 case 的完整 autoid(须在 last_run.json 中)。
        layer: 归因层,五选一——G(设备语法拒绝)、E(环境/IP)、V(断言与行为不符)、
            transient(瞬态,不可复现的偶发)、product_defect(疑似产品缺陷)。
            拿不准就别调本工具(undetermined 是默认态,不用提交)。
        disposition: 处置,五选一——reflow(带反馈重编)、frozen(冻结同法换方向)、
            env_blocked(环境阻塞跑完为先)、defect_candidate(走缺陷候选单)、fixed(已修复待复跑)。
        evidence: 支撑该结论的 device_context/causality **原文子串**(直接复制,勿转述)——
            工具校验它确在该 case 的落盘原文里,防转述失真(曾实证独行 ^ 被转述丢失致误归)。
        fix_direction: 修法方向(自由文本;reflow/frozen 时写清应改什么,下一轮判"同法"靠它)。
        defect_candidate: disposition=defect_candidate 时的结构化候选单,含 repro(复现步骤)、
            expected_with_source(期望+手册出处)、actual(实际+设备证据)、version,可含 ticket_id。

    Returns:
        确认(写入路径+字段回显);autoid 不在 last_run/evidence 对不上原文时 error。
    """
    from pathlib import Path

    _LAYERS = ("G", "E", "V", "transient", "product_defect")
    _DISPS = ("reflow", "frozen", "env_blocked", "defect_candidate", "fixed")
    layer = (layer or "").strip()
    disposition = (disposition or "").strip()
    if layer not in _LAYERS:
        return f"error: layer 必须是 {'/'.join(_LAYERS)},收到 {layer!r}"
    if disposition not in _DISPS:
        return f"error: disposition 必须是 {'/'.join(_DISPS)},收到 {disposition!r}"
    ev = (evidence or "").strip()
    if not ev:
        return "error: evidence 必填——从 device_context/causality 原文直接复制支撑片段"

    try:
        from main.ist_core.tools.deepagent.file_tools import _resolve_inside_root
        xp = _resolve_inside_root(xlsx_path, must_exist=True)
    except Exception:  # noqa: BLE001
        xp = None
    p = Path(xp) if xp else Path(xlsx_path)
    lr = p.parent / "last_run.json"
    if not lr.is_file():
        return f"error: last_run.json 不存在: {lr}(先跑 dev_run_batch_digest)"
    try:
        records = json.loads(lr.read_text(encoding="utf-8"))
        assert isinstance(records, list)
    except Exception as e:  # noqa: BLE001
        return f"error: last_run.json 读取失败: {e}"

    aid = (autoid or "").strip()
    rec = next((r for r in records if isinstance(r, dict) and str(r.get("autoid")) == aid), None)
    if rec is None:
        have = [str(r.get("autoid")) for r in records if isinstance(r, dict)][:8]
        return f"error: autoid {aid} 不在 last_run.json(有: {', '.join(have)}…)"

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
        return ("error: evidence 不是该 case 落盘原文的子串——从 last_run.json 里该 autoid 的 "
                "device_context/causality 原文**直接复制**,不要转述/改写(转述曾丢失独行 ^ 致误归)。"
                "多行片段容易被参数转义搞失真:改抄**单行内**的关键片段即可(已做空白归一化,"
                "跨行不必逐字节对齐)。")

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
            return f"error: defect_candidate 缺必填字段: {', '.join(missing)}"
        entry["defect_candidate"] = dc
    rec["_attribution"] = entry
    try:
        lr.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"error: 写盘失败: {e}"
    return (f"归因已落盘 {lr}\nautoid={aid} layer={layer} disposition={disposition}"
            + (f" fix_direction={entry['fix_direction'][:60]}" if entry["fix_direction"] else ""))
