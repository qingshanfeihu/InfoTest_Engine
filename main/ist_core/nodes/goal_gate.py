"""goal_gate 节点：`/goal` 自治循环的核心闸（Claude Code prompt-based Stop hook 的图内等价）。

机制对齐 Claude Code `/goal`：agent 自以为干完了（review_gate → passed）→ goal_gate 用 haiku
评判「目标达成了吗」。没达成 → 注入反馈 `HumanMessage` + 回 `qa_node` 继续；retry 上限
`IST_GOAL_MAX_ROUNDS`（默认 8）。结构与 `review_gate` 同构。

**opt-in、零行为改变**：state 没 `goal_text`（没传 `--goal`/未来 `/goal`）或 `IST_GOAL_ENABLED=0`
→ 返回 `inactive` 透传到 finalize，现有单轮行为完全不变。

**评判只认证据**：prompt 强约束「依据工具/上机真实返回（如 `dev_run_batch` 的逐 case verdict）判，
绝不接受 agent 仅口头声称完成」。评判器出错 / 输出解析不确定 → **保守判未达成**（让其回流多跑
一轮，受 `IST_GOAL_MAX_ROUNDS` 上限兜底不困死）——绝不在唯一危险方向（误判达成、提前收手）fail-open。
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ROUNDS = 8


def _max_rounds() -> int:
    try:
        return max(1, int(os.environ.get("IST_GOAL_MAX_ROUNDS") or _DEFAULT_MAX_ROUNDS))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_ROUNDS


def _enabled() -> bool:
    """总开关（kill switch）：默认开（honor goal_text）；置 0/false/off/no 强制关。"""
    return (os.environ.get("IST_GOAL_ENABLED") or "1").strip().lower() not in (
        "0", "false", "off", "no",
    )


def goal_gate(state: dict[str, Any]) -> dict[str, Any]:
    """目标自治闸：没目标→透传；达成→停；未达成→注入反馈回 qa_node；超上限→如实停。"""
    goal = (state.get("goal_text") or "").strip()
    if not goal or not _enabled():
        return {"goal_status": "inactive"}

    verdict = _evaluate_goal(goal, state.get("messages") or [])
    if verdict.get("met"):
        logger.info("[goal] 目标达成，停止。")
        return {"goal_status": "met"}

    cap = _max_rounds()
    retry = (state.get("goal_retry_count") or 0) + 1
    reason = (verdict.get("reason") or "目标尚未达成").strip()

    if retry > cap:
        msg = (
            f"[goal] 目标经 {cap} 轮仍未达成，如实停止（不假装完成）。\n"
            f"最后一次评估的差距：{reason}"
        )
        logger.warning("[goal] 超上限 %d 轮，停止。", cap)
        return {"goal_status": "exhausted", "final_answer": msg}

    inject = (
        f"[goal] 目标尚未达成：{reason}\n"
        f"继续干——必须基于工具/上机的真实返回（如 dev_run_batch 的逐 case verdict、文件产出）改进，"
        f"不要只声称完成而不验证；完成后会再次自动核验。(第 {retry}/{cap} 轮)"
    )
    logger.info("[goal] 未达成，回流继续 (第 %d/%d 轮): %s", retry, cap, reason[:80])
    return {
        "goal_status": "unmet",
        "goal_retry_count": retry,
        "messages": [HumanMessage(content=inject)],
    }


# ── 评判器（纯 LLM + 强证据 prompt）───────────────────────────────────────────

_SYS = (
    "你是「目标达成评判器」。给你一个目标 + 最近对话（含工具返回）。判断目标是否**已经达成**。\n"
    "**判定铁律（严格执行）：**\n"
    "1. 判『达成』的唯一依据 = 最近的**工具返回**（如 dev_run_batch 的逐 case verdict、文件产出明细）里有**支持达成的硬数据**。\n"
    "2. agent 的 AI 文字声称（无论多肯定：『已修好』『全部通过』『PASS』）**一律不算证据**；看不到对应工具返回 → 判未达成。\n"
    "3. **默认未达成**：除非工具返回里有明确达成证据，否则一律判 false（宁可多跑一轮，绝不轻信声称）。\n"
    "4. 判『达成』时 reason **必须引用具体工具返回数据**（哪次 dev_run_batch、verdict 数字如『44/44 pass 0 fail』）；引用不出具体数据 = 改判未达成。\n"
    "5. 目标说『全部通过』就要**全部** pass；只过一部分 = 未达成。\n"
    '只输出 JSON：{"met": true 或 false, "reason": "未达成则说还差什么+下一步；达成则引用具体工具返回数据为证"}'
)


def _summarize_tool_verdicts(content: str) -> str | None:
    """若 ToolMessage 内容是 dev_run_batch 风格的逐 case JSON（每条含 verdict），产出
    **永不截断**的紧凑裁决摘要——保证『是否全部 pass』这一裁判最关键信号不被 per_msg 截没
    （N 个 case 的数组远超单条 per_msg，fail 又常排在数组后段）。解析不出则返回 None。"""
    try:
        data = json.loads(content)
    except Exception:  # noqa: BLE001
        return None
    records: list | None = None
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        for k in ("results", "cases", "details", "items", "verdicts"):
            if isinstance(data.get(k), list):
                records = data[k]
                break
    if not records or not all(isinstance(r, dict) for r in records):
        return None
    if not any("verdict" in r for r in records):
        return None
    counts: dict[str, int] = {}
    non_pass: list[str] = []
    for r in records:
        v = str(r.get("verdict") or "?").lower()
        counts[v] = counts.get(v, 0) + 1
        if v != "pass":
            aid = r.get("autoid") or r.get("id") or r.get("task_id") or "?"
            non_pass.append(f"{aid}({v})")
    tally = " / ".join(f"{v}:{n}" for v, n in sorted(counts.items()))
    out = f"逐case裁决 共{len(records)}: {tally}"
    if non_pass:
        shown, extra = non_pass[:60], max(0, len(non_pass) - 60)
        out += f"；非pass[{len(non_pass)}]: " + ", ".join(shown)
        if extra:
            out += f" …(+{extra} 省略)"
    return out


def _render_tail(
    messages: list, *, limit: int = 16, per_msg: int = 600, tool_per_msg: int = 4000
) -> str:
    """把最近若干条消息渲染成紧凑文本，保留工具调用名 + 工具返回内容（证据所在）。

    工具返回是裁判的硬证据，给更大的 ``tool_per_msg`` 额度；且对 dev_run_batch 风格的逐 case
    裁决额外附一条**永不截断**的摘要，防止 fail 排在数组后段被截没导致裁判误判『全过』。
    """
    lines: list[str] = []
    for m in (messages or [])[-limit:]:
        if isinstance(m, AIMessage):
            tcs = m.tool_calls or []
            if tcs:
                names = ", ".join(
                    f"{t.get('name')}({json.dumps(t.get('args', {}), ensure_ascii=False)[:120]})"
                    for t in tcs
                )
                lines.append(f"[AI 调用工具] {names}")
            c = m.content if isinstance(m.content, str) else str(m.content)
            if c.strip():
                lines.append(f"[AI] {c[:per_msg]}")
        elif isinstance(m, ToolMessage):
            c = m.content if isinstance(m.content, str) else str(m.content)
            digest = _summarize_tool_verdicts(c)
            if digest:
                lines.append(f"[工具返回·裁决摘要] {digest}")
            lines.append(f"[工具返回] {c[:tool_per_msg]}")
        elif isinstance(m, HumanMessage):
            c = m.content if isinstance(m.content, str) else str(m.content)
            lines.append(f"[用户/反馈] {c[:per_msg]}")
    return "\n".join(lines)


def _evaluate_goal(goal: str, messages: list) -> dict[str, Any]:
    """调 haiku 评判目标是否达成。异常→保守判未达成（met=False），受 retry 上限兜底不困住 agent。"""
    try:
        from langchain_core.messages import SystemMessage

        from main.ist_core.agents._llm import build_explore_model

        model = build_explore_model()
        tail = _render_tail(messages)
        user = (
            f"目标：\n{goal}\n\n"
            f"最近对话（含工具真实返回）：\n{tail or '(空)'}\n\n"
            "判定目标是否达成，只输出 JSON。"
        )
        resp = model.invoke([SystemMessage(content=_SYS), HumanMessage(content=user)])
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
        verdict = _parse_verdict(raw)
        # 守护(防轻信 agent 口头声称)：判『达成』必须近况里有**工具返回**(ToolMessage)作硬证据；
        # 只有 AI 文字声称、最近没有任何工具返回 → 改判未达成,逼它真去工具验证再下结论。
        if verdict.get("met"):
            has_tool = any(isinstance(m, ToolMessage) for m in (messages or [])[-16:])
            if not has_tool:
                logger.info("[goal] 评判判达成但近况无工具返回证据 → 改判未达成(防轻信声称)")
                return {"met": False,
                        "reason": "声称达成但最近对话无任何工具返回(如 dev_run_batch 的真实 verdict)佐证 → "
                                  "判未达成。请真正用工具/上机验证拿到结果后再下结论,不要只口头声称完成。"}
        return verdict
    except Exception as exc:  # noqa: BLE001
        # 保守判未达成（不在唯一危险方向「误判达成提前收手」fail-open）：让其回流多跑一轮，
        # 受 IST_GOAL_MAX_ROUNDS 上限兜底不会困死 agent。
        logger.warning("[goal] 评判器异常，保守判未达成（受 max_rounds 兜底）：%s", exc)
        return {"met": False, "reason": f"评判器异常，保守判未达成（受 max_rounds 兜底，不困死）：{exc}"}


def _parse_verdict(raw: str) -> dict[str, Any]:
    """从模型输出抽 ``{met, reason}``。

    **证据纪律（对应裁判唯一危险失败方向：误判达成）**：只认**含 ``met`` 字段的合法 JSON**；
    抽不到就一律**默认未达成**（``met=False``），让其回流多跑一轮（受 retry 上限兜底，不困死）——
    绝不用脆弱子串去『抢救』一个 ``true``（旧实现 ``'"met": true' in low`` 会被复述目标、截断
    JSON、举例块误命中；旧贪婪 ``\\{.*\\}`` 又会跨多块匹配致解析失败）。
    """
    s = (raw or "").strip()

    def _coerce(d: Any) -> dict[str, Any] | None:
        if isinstance(d, dict) and "met" in d:
            return {"met": bool(d.get("met")), "reason": str(d.get("reason") or "")}
        return None

    # 1) 整串就是干净 JSON
    try:
        hit = _coerce(json.loads(s))
        if hit is not None:
            return hit
    except Exception:  # noqa: BLE001
        pass

    # 2) 文本里逐块（非贪婪）抽 {...}，取**最后一个**含 met 的合法 JSON 对象（结论块通常在末尾）
    last: dict[str, Any] | None = None
    for mt in re.finditer(r"\{[^{}]*\}", s, re.DOTALL):
        try:
            hit = _coerce(json.loads(mt.group(0)))
        except Exception:  # noqa: BLE001
            continue
        if hit is not None:
            last = hit
    if last is not None:
        return last

    # 3) 抽不到含 met 的合法 JSON → 保守判未达成（绝不子串抢救 true）
    logger.info("[goal] 评判输出无法解析出含 met 的 JSON → 保守判未达成。raw=%s", s[:200])
    return {"met": False, "reason": (s[:300] or "评判输出无法解析，保守判未达成")}
