"""工具结果剪枝 middleware(2026-07-05,MiMo-Code session/compaction prune 移植)。

问题:长会话里旧工具结果(设备日志/grep 输出/digest 明细)随轮堆积,直到摘要
中间件一把全总结——摘要是有损的,细节全靠 LLM 转述。MiMo-Code 的做法:在摘要
**之前**用零成本的确定性剪枝先释放上下文——从后往前保护最近 N token 的工具输出,
更旧的抹除。

本移植的改良:不整段抹除,**保留头部 160 字符**(工具结果的文件指针/落盘路径/
结论行通常在开头——offload 路径、last_run.json 指针都能幸存)+ 剪枝标记与恢复
指引(重新调用工具/fs_read 落盘文件)。被剪的信息三条恢复路:头部指针、摘要
中间件的撤出历史文件、重新调用。

实现约束(与 loop_guard 同款纪律):
- wrap_model_call 只改**本次调用的消息副本**,不写回 state——原始对话史完整保留
  (deepagents 摘要也是非破坏式,两者叠加安全:摘要先压缩了视图,剪枝在其后
  看到的是已压缩视图,预算不超即整体 no-op)。
- 剪枝判定是纯函数(同一历史 → 同一结果):历史只追加,已被剪的消息在更长历史
  下仍会被剪(预算从尾部算)——前缀单调,prompt cache 只在剪枝推进时失效一次。

``IST_PRUNE_TOOL_OUTPUTS=0`` 关;``IST_PRUNE_PROTECT_CHARS`` 调预算(默认 15 万
字符≈5 万 token:比模型上限小得多、比单轮工具产出大得多——只在真正的长会话
里生效)。
"""

from __future__ import annotations

import logging
import os
from typing import Awaitable, Callable

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)

logger = logging.getLogger(__name__)

# 保护预算:从最新往回数,这么多字符内的工具结果原样保留。
_DEFAULT_PROTECT_CHARS = 150_000
# 小结果豁免:低于此长度的工具结果不剪(剪它省不了几个 token,还丢上下文)。
_MIN_PRUNE_CHARS = 2_000
# 头部保留:被剪结果保留开头这么多字符(文件指针/结论行在头部)。
_HEAD_KEEP_CHARS = 160
# 最近 K 个用户轮完全不碰(当前任务的工作集)。
_KEEP_RECENT_TURNS = 2
# 起剪门槛:可剪总量低于此不动手(MiMo PRUNE_MINIMUM 同款)——剪几 KB 不值得
# 破一次 prompt cache 前缀。
_PRUNE_MINIMUM_CHARS = 20_000
# 这些工具的结果永不剪:skill 正文是行为指令(MiMo 同款保护)、ask_user 是用户决策。
_PROTECTED_TOOLS = frozenset({"invoke_skill", "ask_user"})


def _enabled() -> bool:
    return (os.environ.get("IST_PRUNE_TOOL_OUTPUTS") or "1").strip().lower() not in ("0", "false", "no")


def _protect_budget() -> int:
    try:
        return int(os.environ.get("IST_PRUNE_PROTECT_CHARS") or _DEFAULT_PROTECT_CHARS)
    except (TypeError, ValueError):
        return _DEFAULT_PROTECT_CHARS


def _content_str(m) -> str:
    c = getattr(m, "content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in c)
    return str(c or "")


def prune_messages(messages: list) -> list:
    """返回剪枝后的消息列表(新列表;被剪消息是**副本**,原对象不动)。

    从尾往头:①最近 _KEEP_RECENT_TURNS 个用户轮内全保;②其后累计 ToolMessage
    内容长度,超 _protect_budget() 的开始剪(保护工具/小结果豁免)。
    无可剪时原列表原样返回(is 同一对象,零开销路径)。
    """
    budget = _protect_budget()
    turns = 0
    acc = 0
    prune_idx: list[int] = []
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        mtype = getattr(m, "type", "")
        if mtype == "human":
            turns += 1
            continue
        if turns < _KEEP_RECENT_TURNS:
            continue
        if mtype != "tool":
            continue
        name = getattr(m, "name", "") or ""
        if name in _PROTECTED_TOOLS:
            continue
        text = _content_str(m)
        if len(text) < _MIN_PRUNE_CHARS:
            continue
        acc += len(text)
        if acc > budget:
            prune_idx.append(i)
    if not prune_idx:
        return messages
    prunable = sum(len(_content_str(messages[i])) for i in prune_idx)
    if prunable < _PRUNE_MINIMUM_CHARS:
        return messages

    out = list(messages)
    for i in prune_idx:
        m = out[i]
        text = _content_str(m)
        head = text[:_HEAD_KEEP_CHARS]
        stub = (f"{head}\n…[工具结果已剪枝以释放上下文:原 {len(text)} 字符。"
                "头部保留了指针/结论;需要完整原文时重新调用该工具,"
                "或 fs_read 其落盘文件(路径通常在头部)。]")
        # 标签平衡(2026-07-05 中间件交互修复):ToolEnvelope 已在头部放 <tool_result>
        # 开标签,剪掉尾部会带走 </tool_result> 闭标签 → LLM 见不平衡 XML。头部有未闭合
        # 的 <tool_result> 就补回闭标签,信封仍完整。
        import re as _re
        if _re.match(r"\s*<tool_result\b", head) and "</tool_result>" not in stub:
            stub += "\n</tool_result>"
        try:
            m2 = m.model_copy(update={"content": stub})
        except Exception:  # noqa: BLE001 — 非 pydantic 消息对象,跳过该条
            continue
        out[i] = m2
    logger.info("tool_result_prune: 剪枝 %d 条旧工具结果(预算 %d 字符)", len(prune_idx), budget)
    return out


class ToolResultPruneMiddleware(AgentMiddleware):
    """确定性剪枝旧工具结果——摘要之前的零成本上下文释放。"""

    def _pruned(self, request: ModelRequest) -> ModelRequest:
        if not _enabled():
            return request
        try:
            msgs = list(getattr(request, "messages", None) or [])
            out = prune_messages(msgs)
            if out is msgs:
                return request
            return request.override(messages=out)
        except Exception:  # noqa: BLE001 — 剪枝绝不挂主流程
            logger.debug("tool_result_prune 失败(放行原文)", exc_info=True)
            return request

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._pruned(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._pruned(request))
