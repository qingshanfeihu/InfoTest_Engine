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
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_QA_AGENT_MODEL = "qwen-plus"


def resolve_llm_provider() -> str:
    """统一的 LLM 供应商标识符（dashscope / deepseek）。

    按 ``QA_AGENT_LLM_PROVIDER`` env 决定；缺省 / 未识别值 → ``dashscope``
    （保持向后兼容，跟旧版本配置不冲突）。
    """
    return (os.environ.get("QA_AGENT_LLM_PROVIDER") or "dashscope").strip().lower()


def resolve_llm_api_key() -> str:
    """按 ``QA_AGENT_LLM_PROVIDER`` 决定查哪个 API key。

    - ``deepseek`` → ``DEEPSEEK_API_KEY``
    - 其他（含 ``dashscope`` / 缺省）→ ``DASHSCOPE_API_KEY`` / ``BAILIAN_API_KEY``

    供 runner / memory.dream 等其他模块统一用，避免硬编码 DashScope key。
    """
    if resolve_llm_provider() == "deepseek":
        return (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    return (
        os.environ.get("DASHSCOPE_API_KEY")
        or os.environ.get("BAILIAN_API_KEY")
        or ""
    ).strip()


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
    # Qwen3.6 在 tool-calling 模式下默认不输出陪伴 content；开启 thinking
    # 后模型会把推理过程放进 ``message.reasoning_content`` / 流式
    # ``delta.reasoning_content``，TUI 可以渲染成"思考"通道。
    # 参考：阿里云百炼 OpenAI 兼容端点文档（extra_body.enable_thinking）。
    extra_body = dict(kwargs.pop("extra_body", None) or {})
    extra_body.setdefault("enable_thinking", True)
    kwargs["extra_body"] = extra_body

    # langchain-openai 1.2.x 的已知缺陷：基类 ChatOpenAI 的
    # _convert_chunk_to_generation_chunk 不解析 delta.reasoning_content
    # （见 langchain-ai/langchain issue #33672 / #35059，2025 修复 PR 都未合
    # 入）。我们用一个轻量子类把 reasoning_content 从原始 dict 拷到
    # ``message.additional_kwargs["reasoning_content"]``，graph.py 的
    # _MainAgentProgressHandler 已经在那里读 thinking 块。
    cls = _get_chat_openai_with_reasoning()
    return cls(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        **kwargs,
    )


def _build_deepseek_compat(model_name: str, **kwargs: Any):
    """走 DeepSeek OpenAI 兼容端点。

    跟 ``_build_openai_compat`` 同样基于 ChatOpenAI，但关键差异：

    - ``base_url`` 默认 ``https://api.deepseek.com`` （DEEPSEEK_BASE_URL 覆盖）
    - ``api_key`` 必须用 ``DEEPSEEK_API_KEY``
    - **不开** ``extra_body={"enable_thinking": True}``——deepseek-v4-pro 是
      非思考模式（含 tool calling）；要思考请用 ``deepseek-reasoner``，但它
      不支持 function calling，跟我们的 ReAct agent 不兼容。
    - reasoning_content 字段名跟 qwen 完全一致，``_ChatOpenAIWithReasoning``
      子类直接复用（不需重写）。
    - DeepSeek **原生支持** ``tool_choice="required"``，跟 langchain 强制结构化
      输出（ToolStrategy）兼容；这是相对 qwen3.6-plus thinking 模式的优势。
    """
    try:
        from langchain_openai import ChatOpenAI  # noqa: F401  type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "QA_AGENT_FALLBACK_MODEL=deepseek:* 需要 `pip install langchain-openai`"
        ) from exc

    base_url = (
        os.environ.get("DEEPSEEK_BASE_URL")
        or DEFAULT_DEEPSEEK_BASE_URL
    ).strip()
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("deepseek 模式需要 DEEPSEEK_API_KEY")

    kwargs.setdefault("temperature", 0.0)
    kwargs.setdefault("top_p", 0.5)
    kwargs.setdefault("streaming", True)
    # DeepSeek v4-pro thinking 模式实测反而降低评审质量（18 条 thinking=disabled
    # vs 15 条 thinking=enabled），且 reasoning_effort=max 自动升档导致单次
    # invoke 186s 不可接受。直接关闭 thinking，让模型全部 token 预算用于 content。
    # 不设 max_tokens——让模型自由输出完整报告（评审场景需要 15-23 条建议）。
    extra_body = dict(kwargs.pop("extra_body", None) or {})
    extra_body.setdefault("reasoning_effort", "max")
    kwargs["extra_body"] = extra_body

    cls = _get_chat_openai_with_reasoning()
    return cls(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        **kwargs,
    )


def build_explore_model(**kwargs):
    """Explore sub-agent 用：deepseek-v4-flash, thinking=disabled, 快速低成本检索。"""
    model_name = os.environ.get("QA_AGENT_HAIKU_MODEL", "deepseek-v4-flash").strip()
    base_url = (os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).strip()
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Explore model 需要 DEEPSEEK_API_KEY")

    kwargs.setdefault("temperature", 0.0)
    kwargs.setdefault("top_p", 0.5)
    kwargs.setdefault("streaming", True)
    extra_body = dict(kwargs.pop("extra_body", None) or {})
    extra_body.setdefault("thinking", {"type": "disabled"})
    kwargs["extra_body"] = extra_body

    cls = _get_chat_openai_with_reasoning()
    return cls(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        **kwargs,
    )


def _patch_chunk_with_reasoning(chunk, raw_chunk_dict) -> None:
    """把 raw_chunk['choices'][0]['delta']['reasoning_content'] 拷到 chunk.message.additional_kwargs."""
    if chunk is None:
        return
    try:
        choices = raw_chunk_dict.get("choices") or raw_chunk_dict.get("chunk", {}).get("choices") or []
        if not choices:
            return
        delta = choices[0].get("delta") or {}
        rc = delta.get("reasoning_content") or delta.get("reasoning")
        if not rc:
            return
        msg = getattr(chunk, "message", None)
        if msg is None:
            return
        if not hasattr(msg, "additional_kwargs") or msg.additional_kwargs is None:
            msg.additional_kwargs = {}
        msg.additional_kwargs["reasoning_content"] = rc
    except Exception:  # noqa: BLE001
        pass


_CHAT_OPENAI_REASONING_CLS: Any = None


def _get_chat_openai_with_reasoning():
    """延迟构造的 ChatOpenAI 子类（首次调用时构造）。"""
    global _CHAT_OPENAI_REASONING_CLS
    if _CHAT_OPENAI_REASONING_CLS is not None:
        return _CHAT_OPENAI_REASONING_CLS

    from langchain_openai import ChatOpenAI  # type: ignore[import-not-found]

    class ChatOpenAIWithReasoning(ChatOpenAI):
        """ChatOpenAI 子类，双向支持 reasoning_content（DeepSeek 多轮 + qwen 流式）。

        入方向（响应）：override ``_convert_chunk_to_generation_chunk`` 把
        ``delta.reasoning_content`` 拷到 ``message.additional_kwargs``。
        参考 langchain-ai/langchain issue #33672。

        出方向（请求）：override ``_get_request_payload`` 把上一轮 AIMessage
        的 ``additional_kwargs["reasoning_content"]`` 注入回 assistant payload
        dict 的同名 sibling 字段——DeepSeek thinking 模式下 multi-turn
        tool_call 要求这个字段必须保留，否则 400 "reasoning_content must be
        passed back"。BaseChatOpenAI 的 ``_convert_message_to_dict`` 默认会
        丢非标准 additional_kwargs，langchain issue #37178 仍 Open，无官方修
        复，所以我们在子类层面打补丁。
        """

        def _convert_chunk_to_generation_chunk(
            self, chunk, default_chunk_class, base_generation_info
        ):
            gen_chunk = super()._convert_chunk_to_generation_chunk(
                chunk, default_chunk_class, base_generation_info
            )
            if isinstance(chunk, dict):
                _patch_chunk_with_reasoning(gen_chunk, chunk)
            return gen_chunk

        def _get_request_payload(self, input_, *, stop=None, **kwargs):
            payload = super()._get_request_payload(input_, stop=stop, **kwargs)
            try:
                from langchain_core.messages import AIMessage  # noqa: PLC0415

                # input_ 是原始 LanguageModelInput——通常是 list[BaseMessage]
                originals = input_ if isinstance(input_, list) else []
                # 顺序匹配：BaseChatOpenAI._convert_message_to_dict 是顺序映射，
                # 不会重排或插入；按 assistant role 顺序对齐 AIMessage 序列即可
                ai_iter = iter(
                    m for m in originals if isinstance(m, AIMessage)
                )
                injected = 0
                rc_total_chars = 0
                for msg_dict in payload.get("messages", []):
                    if msg_dict.get("role") != "assistant":
                        continue
                    src = next(ai_iter, None)
                    if src is None:
                        break
                    rc = (src.additional_kwargs or {}).get("reasoning_content")
                    if rc:
                        msg_dict["reasoning_content"] = rc
                        injected += 1
                        rc_total_chars += len(rc)
                # 诊断：payload 大小 + reasoning_content 注入数量
                if os.environ.get("QA_AGENT_DEBUG_PAYLOAD") == "1":
                    import json as _json  # noqa: PLC0415
                    payload_size = len(_json.dumps(payload, ensure_ascii=False))
                    msg_count = len(payload.get("messages", []))
                    logger.warning(
                        "[deepseek payload] msgs=%d size=%dKB rc_injected=%d rc_chars=%d",
                        msg_count, payload_size // 1024, injected, rc_total_chars,
                    )
            except Exception as exc:  # noqa: BLE001
                # 任何 patch 失败都 silent fallback——非 thinking 路径继续工作
                if os.environ.get("QA_AGENT_DEBUG_PAYLOAD") == "1":
                    logger.warning("[deepseek payload patch err] %s", exc)
            return payload

    _CHAT_OPENAI_REASONING_CLS = ChatOpenAIWithReasoning
    return ChatOpenAIWithReasoning


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

            if fallback.lower().startswith("deepseek:"):
                target_model = fallback.split(":", 1)[1].strip() or model_name
                logger.info("使用 DeepSeek 兼容端点: model=%s", target_model)
                return _build_deepseek_compat(target_model, **kwargs)

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
