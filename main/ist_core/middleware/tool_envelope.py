"""工具结果统一信封 middleware(2026-07-05,坑1 修复)。

问题:交互面 XML 化曾散在单个工具的返回值里手改(36 个工具只改了 3 个,fork 路径
零覆盖),且造出 4 种互不统一的临时标签——横切关注点没在横切层解决,新工具/漏改
工具/子代理全漏。

做法:``wrap_tool_call`` 在**工具结果边界**统一包一层稳定信封::

    <tool_result name="dev_probe" status="ok">
    …工具原始返回(工具自有的内层标签保留,成为嵌套节)…
    </tool_result>

- LLM 学到**一个**稳定外层结构:什么是数据、来自哪个工具、成败如何——数据与
  指令不再混排(工具返回里的祈使句默认是数据不是本轮指令;skill 正文例外,其
  内层 <skill_content> 已自标注为行为指令)。
- **机读契约零影响**:代码层解析走 `.func` 直调(digest 调 dev_run_batch.func、
  pipeline 收 fork 文本),不经 ToolNode,不会看到信封;信封只出现在给 LLM 的
  ToolMessage 里。
- status 由机读前缀判定(error:/ERROR: 开头 = error),LLM 一眼分成败。
- 幂等:已带信封的内容不重复包。

``IST_TOOL_ENVELOPE=0`` 关(默认开——严格的结构化改善,与 prune 同理)。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Awaitable, Callable

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return (os.environ.get("IST_TOOL_ENVELOPE") or "1").strip().lower() not in ("0", "false", "no")


def envelope_text(name: str, text: str) -> str:
    """给单条工具返回文本包信封(纯函数,便于测试与复用)。"""
    if text.lstrip().startswith("<tool_result"):
        return text   # 幂等
    status = "error" if text.lstrip().lower().startswith(("error:", "error ", "错误")) \
        or text.lstrip().startswith("ERROR:") else "ok"
    return f'<tool_result name="{name}" status="{status}">\n{text}\n</tool_result>'


_ENVELOPE_HEAD_RE = re.compile(r'<tool_result\s+name="([^"]*)"\s+status="([^"]*)"\s*>')
_ENVELOPE_CLOSE = "</tool_result>"


def parse_tool_result_envelope(text: str) -> tuple[str, str, str] | None:
    """解析 ``envelope_text`` 包出的信封,返回 ``(name, status, body)``;非信封返回 None。

    显示层用它把信封拆回内容,不再把 ``<tool_result …>`` 开标签原文当摘要泄漏。
    容忍两种残缺:缺闭标签(ToolResultPrune 剪过的旧消息)——body 取开标签后全部;
    嵌套信封——闭标签 rfind 取最后一个,内层嵌套节保留在 body。解析失败返回 None,
    调用方按原文使用。与 ``envelope_text`` 同文件对偶,格式契约单源。
    """
    if not isinstance(text, str):
        return None
    stripped = text.lstrip()
    if not stripped.startswith("<tool_result"):
        return None
    m = _ENVELOPE_HEAD_RE.match(stripped)
    if not m:
        return None
    body = stripped[m.end():]
    close_idx = body.rfind(_ENVELOPE_CLOSE)
    if close_idx >= 0:
        body = body[:close_idx]
    # envelope_text 是 >\n{text}\n</tool_result> —— 剥恰好一层首尾换行,精确往返
    if body.startswith("\n"):
        body = body[1:]
    if body.endswith("\n"):
        body = body[:-1]
    return m.group(1), m.group(2), body


def _wrap(request, result):
    if not _enabled():
        return result
    try:
        if not isinstance(result, ToolMessage):
            return result   # Command / 其他控制流不动
        content = result.content
        name = ""
        try:
            name = str((request.tool_call or {}).get("name") or "")
        except Exception:  # noqa: BLE001
            name = str(getattr(result, "name", "") or "")
        if isinstance(content, str) and content.strip():
            return result.model_copy(update={"content": envelope_text(name or "tool", content)})
        if isinstance(content, list):
            # 多块内容:只包文本块,结构块(图像等)不动
            new_blocks = []
            changed = False
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text" and str(b.get("text", "")).strip():
                    new_blocks.append({**b, "text": envelope_text(name or "tool", str(b["text"]))})
                    changed = True
                else:
                    new_blocks.append(b)
            if changed:
                return result.model_copy(update={"content": new_blocks})
        return result
    except Exception:  # noqa: BLE001 — 信封绝不挂工具执行
        logger.debug("tool envelope 包装失败(原样返回)", exc_info=True)
        return result


class ToolEnvelopeMiddleware(AgentMiddleware):
    """所有工具返回统一 <tool_result> 信封——数据面 XML 在横切层一次解决。"""

    def wrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Any],
    ) -> Any:
        return _wrap(request, handler(request))

    async def awrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        return _wrap(request, await handler(request))
