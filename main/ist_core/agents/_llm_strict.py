"""per-tool strict 名单与转换(DESIGN §11.11 构件一的绑定通道)。

独立小模块:_llm.py 的 bind_tools 每次绑定都会查名单,放这里避免把工具名
硬编码进 500 行的 LLM 封装;新增 strict 工具=改这一个集合。
"""

from __future__ import annotations

PER_TOOL_STRICT = frozenset({"submit_ask_panel"})


def to_strict_tool(t):
    """BaseTool → OpenAI function dict(strict=True)。

    langchain 的 convert_to_openai_tool(strict=True) 负责 additionalProperties:false
    与 required 全量化;转换失败时原样返回(fail-open:宁可非 strict 也不断工具)。
    """
    if isinstance(t, dict):
        fn = dict(t.get("function") or {})
        fn["strict"] = True
        return {**t, "function": fn}
    try:
        from langchain_core.utils.function_calling import convert_to_openai_tool
        return convert_to_openai_tool(t, strict=True)
    except Exception:  # noqa: BLE001
        return t
