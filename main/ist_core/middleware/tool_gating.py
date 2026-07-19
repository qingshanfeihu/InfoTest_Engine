"""工具渐进披露 middleware(C2,2026-07-05,docs/AUDIT_skill_standard_alignment.md)。

问题:主 agent 31 个工具的 schema(docstring+参数)每次 LLM 调用全量常驻
(实测 27 个即 52k+ 字符)——纯评审/问答会话也扛着 13 个 compile_* 和 7 个 dev_*
的完整说明。skill 侧早有渐进披露(listing 预算/body 触发加载),工具侧一直没有。

做法(官方 L1/L2 渐进披露的工具版):按能力域把工具分组,``wrap_model_call``
时只保留「基础组 + 本会话已激活的组」。激活信号全部是**可见历史里的机械事实**,
不做关键字猜测(强字典误杀教训):

1. ``invoke_skill(skill=X)`` 出现过 → 激活 X 映射的组(skill 是能力域的正门,
   skills-first 每轮 reminder 都在推它——被隐藏的组经"调 skill"一步自愈);
2. 某 gated 工具的 tool_call/ToolMessage 出现过 → 激活其组(粘性:续聊/恢复线程
   里模型已经在用的工具绝不消失);
3. 未知 skill 名 → 全量放行(fail-open:宁多勿断)。

compact 后若激活证据被摘要抹掉:summarization 保留近段消息(近期 tool_call 大
概率幸存);全被抹掉时组隐藏,skills-first 驱动重新 invoke_skill → 下一轮恢复。

默认开(dongkl 对照轮实测后翻默认:欠定问询/修复轮/交付确认零 gating 异常)。``IST_TOOL_GATING_ENABLED=0`` 关;历史上按「新参数默认关」约定起步,``=1``
开启;34-case 对照轮验证不劣化后再翻默认。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)

logger = logging.getLogger(__name__)

# 能力域分组:按命名空间前缀(2026-06-23 工具命名收口的红利——前缀即能力域)。
# 不在任何 gated 前缀里的工具都是基础组(fs_*/run_*/kb_*/裸名核心),永远可见。
_GATED_PREFIX_GROUPS: dict[str, str] = {
    "compile_": "compile",
    "submit_": "compile",
    "dev_": "device",
    # 精确名条目(startswith 对自身恒真):kb_ 前缀本属基础组,但意图检索只服务
    # 编译链的 ask 前置(§11.11 构件二"随 compile 激活"),常驻会顶破基础模式
    # schema 预算(35k 门)
    "kb_intent_search": "compile",
}

# skill → 激活组。映射对象是"main 编排该 skill 时自己要用的工具域",宁多勿断
# (多给只是 schema 重量,少给才可能断工作流)。未列出的 skill 视为未知 → 全量放行。
_SKILL_GROUPS: dict[str, set[str]] = {
    "ist-compile-engine": {"compile", "device"},
    "compile-attributor": {"compile", "device"},
    "compile-worker": {"compile", "device"},
    "ist-verify": {"compile", "device"},
    "device-verify": {"device"},
    "config-automation": set(),   # config_generator 程序化管线退役(#45 ③A):SKILL.md 现只用 fs_* 基础组做 IP 替换,不再需 device 组
    "config-answer": {"device"},
    "config-answer-draft": {"device"},
    "config-answer-verifier": {"device"},
    # 纯分析/评审:基础组足够
    "test-list-review": set(),
    "review-verifier": set(),
    "escalate-when-stuck": set(),
    # 文档/报告生成(origin/main 2026-07-16 并入):用 wx_*/report_to_doc/fs_*,
    # 均不在门控前缀内=基础组常驻,无需激活 compile/device
    "doc-authoring": set(),
    "report-gen": set(),
    # 旧下划线名(B1 连字符化前的历史对话/续聊线程里仍会出现,与新名同义)
    "ist_compile_engine": {"compile", "device"},
    "compile_worker": {"compile", "device"},
    "compile_attributor": {"compile", "device"},
    "ist_verify": {"compile", "device"},
}

_ALL_GROUPS = frozenset(_GATED_PREFIX_GROUPS.values())


def _enabled() -> bool:
    # 默认开(2026-07-05 翻默认:34-case 对照轮全程 gating=1 验收通过——七波派发/
    # 欠定问询/修复轮/交付确认零 gating 相关异常)。IST_TOOL_GATING_ENABLED=0 关。
    return (os.environ.get("IST_TOOL_GATING_ENABLED") or "1").strip().lower() in ("1", "true", "yes")


def _group_of(tool_name: str) -> str | None:
    """工具属哪个 gated 组;基础组返回 None。"""
    for prefix, group in _GATED_PREFIX_GROUPS.items():
        if tool_name.startswith(prefix):
            return group
    return None


def _iter_tool_call_names_and_skills(messages: list) -> tuple[set[str], set[str], bool]:
    """扫可见历史,返回 (出现过的工具名集合, invoke_skill 的 skill 名集合, 是否有解析失败)。

    只认机械事实:AIMessage.tool_calls 与 ToolMessage.name——不 grep 正文关键字。
    """
    tool_names: set[str] = set()
    skills: set[str] = set()
    parse_uncertain = False
    for m in messages or []:
        mtype = getattr(m, "type", "")
        if mtype == "ai":
            for tc in (getattr(m, "tool_calls", None) or []):
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                if not name:
                    continue
                tool_names.add(str(name))
                if name == "invoke_skill":
                    args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)
                    if isinstance(args, dict) and args.get("skill"):
                        skills.add(str(args["skill"]).strip())
                    else:
                        # invoke_skill 但拿不到 skill 名(截断/异形参数)→ 保守全开
                        parse_uncertain = True
        elif mtype == "tool":
            name = getattr(m, "name", "") or ""
            if name:
                tool_names.add(str(name))
    return tool_names, skills, parse_uncertain


def _active_groups(messages: list) -> frozenset[str] | None:
    """算本轮应激活的 gated 组;None 表示全量放行(fail-open)。

    ⚠ 缓存不变量:激活信号全部**单调递增**(历史只追加,组只增不减)——整会话
    工具 schema 至多变 2 次(base→+compile→+device),prompt cache 各失效一次可
    摊销。别加"组回收/超时退场"逻辑:工具表抖动=每轮破缓存(MiMo-Code PR #1207
    同款结论:宁用权限 deny 也不动工具表)。"""
    tool_names, skills, uncertain = _iter_tool_call_names_and_skills(messages)
    if uncertain:
        return None
    active: set[str] = set()
    # 信号2:历史里用过的 gated 工具 → 组粘性激活
    for name in tool_names:
        g = _group_of(name)
        if g:
            active.add(g)
    # 信号1:invoke_skill 的 skill 映射
    for sk in skills:
        if sk not in _SKILL_GROUPS:
            return None   # 未知 skill(动态生成/新上架)→ 全量放行
        active |= _SKILL_GROUPS[sk]
    return frozenset(active)


class ToolGatingMiddleware(AgentMiddleware):
    """按会话上下文过滤 request.tools——基础组常驻,能力域组按激活给。"""

    def _filtered(self, request: ModelRequest) -> ModelRequest:
        if not _enabled():
            return request
        try:
            active = _active_groups(list(getattr(request, "messages", None) or []))
            if active is None or active >= _ALL_GROUPS:
                return request
            kept: list[Any] = []
            dropped = 0
            for t in (request.tools or []):
                # dict 型工具(provider 内建/deepagents 注入)不动,只筛 BaseTool 且命中 gated 前缀的
                name = "" if isinstance(t, dict) else str(getattr(t, "name", "") or "")
                g = _group_of(name) if name else None
                if g is not None and g not in active:
                    dropped += 1
                    continue
                kept.append(t)
            if not dropped:
                return request
            if not kept:
                return request   # 兜底:绝不发空工具表
            logger.info("tool_gating: 激活组=%s 隐藏 %d 个工具(可见 %d)",
                        sorted(active) or ["<base>"], dropped, len(kept))
            return request.override(tools=kept)
        except Exception:  # noqa: BLE001 —— 观测性过滤绝不挂主流程
            logger.debug("tool_gating 过滤失败(放行全量)", exc_info=True)
            return request

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._filtered(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._filtered(request))
