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

AttrLayer = Literal["G", "E", "V", "transient"]

# 瞬态信号：与编译质量无关的环境/网络抖动（§5.4 第四类，不回流）。
_TRANSIENT_MARKERS = (
    "ssh", "timed out", "timeout", "connection refused", "connection reset",
    "no route to host", "broken pipe", "nxdomain", "servfail", "network is unreachable",
    "temporarily unavailable", "eof occurred",
)
# E 错信号：IP/可达性层面（dig 没解析到、后端不通）。
_E_MARKERS = (
    "no answer", "not resolved", "无解析", "dig", "unreachable backend",
    "0 servers", "no such host", "address not found",
)
# G 错信号：命令骨架/配置层面（命令没被接受、配置未生效）。
# 命令/参数层新措辞与共享 device_errors 同义（勿加裸 "not found"，会与
# _E_MARKERS 的 "address not found" 抢且过宽）。
_G_MARKERS = (
    "invalid command", "syntax error", "unknown command", "incomplete command",
    "command not found", "configuration failed", "not configured", "未生效",
    "% error", "ambiguous",
    "failed to execute", "not support", "% invalid input", "query type not found",
)


@dataclass
class AttributionResult:
    """一个 fail 的四层归因 + 是否回流 + 回流目标层。"""
    layer: AttrLayer
    reason: str
    reflow: bool          # 是否回流重编译（瞬态=False）
    target_layer: str     # 回流给 draft 改哪层（G/E/V；瞬态为空）

    def render(self) -> str:
        flow = f"回流→{self.target_layer}层" if self.reflow else "不回流(瞬态)"
        return f"[{self.layer}] {self.reason} | {flow}"


def _matches(text: str, markers) -> str | None:
    low = (text or "").lower()
    for m in markers:
        if m in low:
            return m
    return None


def attribute_fail(verdict_detail: str, *, failing_assertion_layer: str = "",
                   failing_assertion_source_kind: str = "") -> AttributionResult:
    """把一个 fail 归到 G/E/V/瞬态。

    判定优先级（确定性，§5.4）：
    1. 瞬态信号（SSH/超时/NXDOMAIN）最高优先——环境抖动，不回流。
    2. E 错信号（dig 无解析/后端不通）→ E 层。
    3. G 错信号（命令非法/配置未生效）→ G 层。
    4. 都没命中 → 默认 V 错（有回显但断言不命中），回流给断言所在层；
       若 provenance 给了 failing_assertion_layer，优先用它定回流目标。

    verdict_detail: 框架真实裁决明细（逐 check_point 报错原文 / dig 输出 / SSH 异常）。
    failing_assertion_layer: 失败断言在 provenance 里的 layer（G/E/V），辅助定回流目标。
    failing_assertion_source_kind: 失败断言来源 kind（辅助判断）。
    """
    # 1. 瞬态最高优先
    hit = _matches(verdict_detail, _TRANSIENT_MARKERS)
    if hit:
        return AttributionResult("transient", f"环境瞬态信号({hit})", reflow=False, target_layer="")

    # 2. E 错
    hit = _matches(verdict_detail, _E_MARKERS)
    if hit:
        return AttributionResult("E", f"E段可达性失败({hit})", reflow=True, target_layer="E")

    # 3. G 错
    hit = _matches(verdict_detail, _G_MARKERS)
    if hit:
        return AttributionResult("G", f"G段命令/配置失败({hit})", reflow=True, target_layer="G")

    # 4. 默认 V 错：有回显但断言不命中。回流目标优先用 provenance 标的层。
    tgt = failing_assertion_layer if failing_assertion_layer in ("G", "E", "V") else "V"
    return AttributionResult("V", "断言期望值不命中(有回显)", reflow=True, target_layer=tgt)


@tool(parse_docstring=True)
def compile_attribute(verdict_detail: str, failing_assertion_layer: str = "",
                      failing_assertion_source_kind: str = "") -> str:
    """把一个上机 fail 的 check_point 四层归因（V3 步骤5，论文 §5.4：G错/E错/V错/瞬态）。

    确定性初分（瞬态>E>G>默认V），供 verify 子流程对每个 fail 先归类、再人工核对语义。
    瞬态（SSH/超时/NXDOMAIN）与编译质量无关、**不回流**；G/E/V 错带回流目标层反馈给 draft。

    Args:
        verdict_detail: 框架真实裁决明细（该 check_point 的报错原文 / dig 输出 / SSH 异常）。
        failing_assertion_layer: 失败断言在 provenance 里的 layer（G/E/V，可空），辅助定回流目标。
        failing_assertion_source_kind: 失败断言来源 kind（可空，辅助判断）。

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

