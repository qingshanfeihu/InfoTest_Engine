"""LLM endpoint detection helpers shared across the codebase.

Only depends on stdlib — no heavy imports.
"""

from __future__ import annotations

# Substrings that identify endpoints supporting the ``thinking`` parameter.
# DEPRECATED for agent 主链路：thinking 参数的 **schema 随模型族而非网关**（实证
# 2026-07-02：同一 tokensec 网关下 deepseek 认 enabled/disabled、minimax 只认
# adaptive/disabled——按 URL 判定必错）。主链路改用 thinking_param_for_model()；
# 本函数仅 function_llm(DashScope/kms) 兼容保留。
_THINKING_ENDPOINT_KEYWORDS: tuple[str, ...] = ("mimo", "xiaomi", "deepseek", "tokensec")


def supports_thinking_toggle(url: str) -> bool:
    """Return True if *url* points to an endpoint that accepts ``thinking``."""
    u = (url or "").lower()
    return any(k in u for k in _THINKING_ENDPOINT_KEYWORDS)


def thinking_param_for_model(model: str, on: bool) -> dict | None:
    """按**模型族**给出 ``extra_body.thinking`` 取值；未知族返回 None（不注入，走端点默认）。

    参数 schema 随模型族而非网关（聚合网关透传各家原生参数）：
    - mimo / deepseek：``{"type": "enabled"|"disabled"}``（官方深度思考开关）。
    - minimax：``{"type": "adaptive"|"disabled"}``（实测 enabled 报 400
      "invalid thinking.type: allowed: adaptive, disabled"）。
    - 其他/未知：None——宁可不注入（端点默认行为），绝不赌一个可能 400 的取值。
    """
    fam = (model or "").lower().rpartition("/")[-1]   # 剥 provider 前缀
    if fam.startswith(("mimo", "deepseek")):
        return {"type": "enabled" if on else "disabled"}
    if fam.startswith("minimax"):
        return {"type": "adaptive" if on else "disabled"}
    return None
