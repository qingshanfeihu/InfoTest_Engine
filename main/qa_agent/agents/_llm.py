"""Agent 层 LLM 工厂。

优先级：
1. ``QA_AGENT_FALLBACK_MODEL`` 显式覆盖：
   - ``anthropic:<model>`` → 走百炼 Anthropic 兼容（激活 deepagents 的 Anthropic-first middleware）
   - ``openai:<model>`` → 走 DashScope OpenAI 兼容端点
   - ``init_chat_model:<spec>`` → 顶层 langchain init_chat_model（需 pip install langchain）
2. 默认走 ChatTongyi(qwen-plus)（DashScope 原生 SDK）

deepagents 0.5.7 是 Anthropic-first 设计：AnthropicPromptCachingMiddleware /
SubAgentMiddleware / PatchToolCallsMiddleware 在非 Anthropic client 上会 noop。
生产推荐 ``anthropic:qwen-plus`` + 百炼 base_url 让这些 middleware 真激活。
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# 百炼 Anthropic 兼容端点（北京区默认）。用户可在 environment 里用
# BAILIAN_ANTHROPIC_BASE_URL / ANTHROPIC_BASE_URL 覆盖（如切新加坡 / 美国区）。
DEFAULT_BAILIAN_ANTHROPIC_BASE_URL = "https://dashscope.aliyuncs.com/apps/anthropic"
DEFAULT_QA_AGENT_MODEL = "qwen-plus"


def _build_anthropic_compat(model_name: str, **kwargs: Any):
    """走 Anthropic 兼容端点（阿里云百炼提供 Qwen 系 Anthropic 协议适配）。

    需要 ``BAILIAN_API_KEY`` / ``DASHSCOPE_API_KEY`` / ``ANTHROPIC_API_KEY`` 之一；
    base_url 用 ``BAILIAN_ANTHROPIC_BASE_URL`` / ``ANTHROPIC_BASE_URL`` 覆盖默认。
    """
    try:
        from langchain_anthropic import ChatAnthropic  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "QA_AGENT_FALLBACK_MODEL=anthropic:* 需要 `pip install langchain-anthropic`"
        ) from exc

    # base_url 解析优先级：
    # 1. BAILIAN_ANTHROPIC_BASE_URL（显式百炼）
    # 2. ANTHROPIC_BASE_URL（仅当不是本地代理，防 cc switch 127.0.0.1 劫持）
    # 3. DEFAULT_BAILIAN_ANTHROPIC_BASE_URL（百炼默认）
    # 详见 memory/feedback_production_llm_endpoint_no_cc_switch.md
    explicit_anthropic_env = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
    is_local_proxy = (
        "127.0.0.1" in explicit_anthropic_env
        or "localhost" in explicit_anthropic_env
        or "0.0.0.0" in explicit_anthropic_env
    )
    base_url = (
        os.environ.get("BAILIAN_ANTHROPIC_BASE_URL")
        or (explicit_anthropic_env if explicit_anthropic_env and not is_local_proxy else "")
        or DEFAULT_BAILIAN_ANTHROPIC_BASE_URL
    ).strip()
    if is_local_proxy and not os.environ.get("BAILIAN_ANTHROPIC_BASE_URL"):
        logger.warning(
            "检测到 ANTHROPIC_BASE_URL=%r 是本地代理（cc switch），忽略并使用百炼默认 %s",
            explicit_anthropic_env, DEFAULT_BAILIAN_ANTHROPIC_BASE_URL,
        )
    api_key = (
        os.environ.get("BAILIAN_API_KEY")
        or os.environ.get("DASHSCOPE_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or ""
    ).strip()

    # 主动覆盖 ANTHROPIC_* env 让 anthropic SDK 内部 fallback / retry 路径都看到百炼 URL
    # （ChatAnthropic(base_url=...) 显式覆盖在某些 SDK 内部路径会被绕过）
    bailian_url_for_sdk = base_url
    if bailian_url_for_sdk and "dashscope" in bailian_url_for_sdk:
        os.environ["ANTHROPIC_BASE_URL"] = bailian_url_for_sdk
        os.environ["ANTHROPIC_API_URL"] = bailian_url_for_sdk
        # 干净化代理变量（cc switch 可能设了 ANTHROPIC_AUTH_TOKEN=PROXY_MANAGED 等）
        for proxy_var in ("ANTHROPIC_PROXY", "ANTHROPIC_AUTH_TOKEN"):
            if proxy_var in os.environ and "127.0.0.1" in os.environ.get(proxy_var, ""):
                logger.warning(
                    "检测到本地代理 %s=%s，主动 unset 避免劫持百炼请求",
                    proxy_var, os.environ[proxy_var],
                )
                os.environ.pop(proxy_var, None)
    if not api_key:
        raise RuntimeError(
            "anthropic 兼容模式需要 BAILIAN_API_KEY / DASHSCOPE_API_KEY / ANTHROPIC_API_KEY 之一"
        )

    kwargs.setdefault("temperature", 0.0)
    kwargs.setdefault("top_p", 0.5)
    # streaming=False：langchain-anthropic streaming 路径假设 context_management
    # 是 Pydantic 对象，但百炼返回纯 dict → AttributeError
    kwargs.setdefault("streaming", False)
    kwargs.setdefault("max_tokens", 8192)
    # max_retries=5 给百炼 503 / 上游算力不足足够的指数退避重试
    kwargs.setdefault("max_retries", 5)
    logger.info("使用 Anthropic 兼容端点: model=%s base_url=%s", model_name, base_url)
    # alias base_url = anthropic_api_url，传 alias 更稳（SDK 版本间字段名不变）
    return ChatAnthropic(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        **kwargs,
    )


def _build_openai_compat(model_name: str, **kwargs: Any):
    """走 OpenAI 兼容端点（DashScope 提供）。

    需要 ``DASHSCOPE_API_KEY`` 或 ``OPENAI_API_KEY``；自动 fallback ``DASHSCOPE_BASE_URL``。
    """
    try:
        from langchain_openai import ChatOpenAI  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "QA_AGENT_FALLBACK_MODEL=openai:* 需要 `pip install langchain-openai`"
        ) from exc

    base_url = (
        os.environ.get("DASHSCOPE_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or DEFAULT_DASHSCOPE_BASE_URL
    ).strip()
    api_key = (
        os.environ.get("DASHSCOPE_API_KEY")
        or os.environ.get("BAILIAN_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()
    if not api_key:
        raise RuntimeError(
            "openai 兼容模式需要 DASHSCOPE_API_KEY / BAILIAN_API_KEY / OPENAI_API_KEY 之一"
        )

    kwargs.setdefault("temperature", 0.0)
    kwargs.setdefault("top_p", 0.5)
    kwargs.setdefault("streaming", True)
    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        **kwargs,
    )


def build_agent_chat_model(**kwargs: Any):
    """按 ``QA_AGENT_FALLBACK_MODEL`` 决定底层 LLM client。"""
    fallback = (os.environ.get("QA_AGENT_FALLBACK_MODEL") or "").strip()
    model_name = (
        kwargs.pop("model", None) or os.environ.get("QA_AGENT_MODEL") or DEFAULT_QA_AGENT_MODEL
    ).strip()

    if fallback:
        try:
            if fallback.lower().startswith("anthropic:"):
                target_model = fallback.split(":", 1)[1].strip() or model_name
                logger.info("使用 Anthropic 兼容端点: model=%s", target_model)
                return _build_anthropic_compat(target_model, **kwargs)

            if fallback.lower().startswith("openai:"):
                target_model = fallback.split(":", 1)[1].strip() or model_name
                logger.info("使用 OpenAI 兼容端点: model=%s", target_model)
                return _build_openai_compat(target_model, **kwargs)

            if fallback.lower().startswith("init_chat_model:"):
                target = fallback.split(":", 1)[1].strip()
                from langchain.chat_models import init_chat_model  # type: ignore[import-not-found]

                logger.info("使用 init_chat_model: %s", target)
                return init_chat_model(target, **kwargs)

            # 裸名（如 ``gpt-4o-mini``）等价于 openai:<name>
            logger.info("视 %r 为 openai:%s（默认走 DashScope 兼容）", fallback, fallback)
            return _build_openai_compat(fallback, **kwargs)
        except Exception as exc:  # noqa: BLE001
            # fallback 不可用 → 自动降级回 ChatTongyi（避免 Reviewer 整个挂掉）
            logger.warning(
                "QA_AGENT_FALLBACK_MODEL=%r 不可用 (%s)；自动降级到 ChatTongyi(%s)",
                fallback, exc, model_name,
            )

    from langchain_community.chat_models.tongyi import ChatTongyi

    kwargs.setdefault("streaming", False)
    return ChatTongyi(model=model_name, **kwargs)


def qa_agent_default_model() -> str:
    """Return the platform default model configured by environment."""
    return (
        os.environ.get("QA_AGENT_REVIEW_MODEL")
        or os.environ.get("QA_AGENT_MODEL")
        or os.environ.get("DASHSCOPE_MODEL")
        or DEFAULT_QA_AGENT_MODEL
    ).strip()


# ---------------------------------------------------------------------------
# 3-tier model selection
# ---------------------------------------------------------------------------

#: 3 tier env vars。每 tier 对应不同复杂度任务：
#:   - opus: 最强（评审、深度分析、重要决策）
#:   - sonnet: 中等（一般 QA、文档问答）
#:   - haiku: 最弱（简单查询、命令补全）
TIER_ENV_VARS = {
    "opus": "QA_AGENT_OPUS_MODEL",
    "sonnet": "QA_AGENT_SONNET_MODEL",
    "haiku": "QA_AGENT_HAIKU_MODEL",
}


def qa_agent_tier_model(tier: str) -> str:
    """Return the configured model for ``tier``（opus / sonnet / haiku）.

    Falls back to ``qa_agent_default_model()`` if the tier-specific env var is
    not set. Examples (with our DashScope-backed deployment)::

        QA_AGENT_OPUS_MODEL=qwen3.6-plus    # 高复杂度任务（评审、推理）
        QA_AGENT_SONNET_MODEL=qwen-plus     # 中等任务（QA / 文档问答）
        QA_AGENT_HAIKU_MODEL=qwen-turbo     # 简单任务（补全 / 路由）
    """
    env_var = TIER_ENV_VARS.get(tier.lower(), "")
    if not env_var:
        return qa_agent_default_model()
    return (os.environ.get(env_var) or qa_agent_default_model()).strip()


def qa_agent_select_model_for_task(task_complexity: str) -> str:
    """根据任务复杂度自动选 tier 模型.

    ``task_complexity``:
      - "high" / "review" → opus tier（深度评审）
      - "medium" / "qa" → sonnet tier（一般问答）
      - "low" / "completion" → haiku tier（简单查询）
    """
    tier_map = {
        "high": "opus", "review": "opus",
        "medium": "sonnet", "qa": "sonnet",
        "low": "haiku", "completion": "haiku",
    }
    tier = tier_map.get(task_complexity.lower(), "sonnet")
    return qa_agent_tier_model(tier)


def qa_agent_allowed_models() -> list[str]:
    """Return allowed reviewer models from environment.

    ``QA_AGENT_ALLOWED_MODELS`` is a comma-separated deployment policy.  When
    unset, the current default model is the only allowed explicit selection.
    """
    raw = (os.environ.get("QA_AGENT_ALLOWED_MODELS") or "").strip()
    if raw:
        models = [item.strip() for item in raw.split(",") if item.strip()]
    else:
        models = [qa_agent_default_model()]
    return list(dict.fromkeys(models))


def validate_review_model(model_name: str | None) -> str:
    """Return an environment-allowed reviewer model name or raise."""
    model = (model_name or qa_agent_default_model()).strip()
    allowed = qa_agent_allowed_models()
    if model not in allowed:
        raise ValueError(
            f"unsupported review model {model!r}; configure QA_AGENT_ALLOWED_MODELS; allowed={allowed}"
        )
    return model


@contextmanager
def qa_agent_model_override(model_name: str | None):
    """Temporarily route all QA reviewer model factories to a concrete model.

    Existing fallback providers are preserved.  For example, an environment
    value of ``openai:<old>`` becomes ``openai:<model>`` for the context, while
    the no-fallback ChatTongyi path receives ``QA_AGENT_MODEL``.
    """
    model = validate_review_model(model_name)
    keys = (
        "QA_AGENT_MODEL",
        "DASHSCOPE_DEFAULT_SYNTHESIS_MODEL",
        "QA_AGENT_ACTIVE_MODEL",
        "QA_AGENT_FALLBACK_MODEL",
    )
    old = {key: os.environ.get(key) for key in keys}
    fallback = (old.get("QA_AGENT_FALLBACK_MODEL") or "").strip()
    os.environ["QA_AGENT_MODEL"] = model
    os.environ["DASHSCOPE_DEFAULT_SYNTHESIS_MODEL"] = model
    os.environ["QA_AGENT_ACTIVE_MODEL"] = model
    if fallback:
        lower = fallback.lower()
        if lower.startswith("openai:"):
            os.environ["QA_AGENT_FALLBACK_MODEL"] = f"openai:{model}"
        elif lower.startswith("anthropic:"):
            os.environ["QA_AGENT_FALLBACK_MODEL"] = f"anthropic:{model}"
    try:
        yield model
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def build_synthesis_model(**kwargs: Any):
    """综合推理模型（coordinator / single_reviewer）。

    读 DASHSCOPE_DEFAULT_SYNTHESIS_MODEL，默认 fallback 到 DASHSCOPE_MODEL → qwen-plus。
    """
    model_name = (
        os.environ.get("DASHSCOPE_DEFAULT_SYNTHESIS_MODEL")
        or os.environ.get("DASHSCOPE_MODEL")
        or os.environ.get("QA_AGENT_MODEL")
        or DEFAULT_QA_AGENT_MODEL
    ).strip()
    return build_agent_chat_model(model=model_name, **kwargs)


def build_max_model(**kwargs: Any):
    """旗舰推理模型（复杂任务）。

    读 DASHSCOPE_DEFAULT_MAX_MODEL，默认 fallback 到 qwen3.6-max-preview。
    """
    model_name = (
        os.environ.get("DASHSCOPE_DEFAULT_MAX_MODEL")
        or "qwen3.6-max-preview"
    ).strip()
    return build_agent_chat_model(model=model_name, **kwargs)
