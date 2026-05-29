"""Agent 层 LLM 工厂.

按 ``IST_LLM_PROVIDER`` 选 dashscope / deepseek，统一通过 ChatOpenAI 兼容端点调用。
两个 provider 主要差异：
- base_url / api_key 来源
- extra_body：dashscope 启用 ``enable_thinking``；deepseek 用 ``reasoning_effort=max``
- 共享 ``ChatOpenAIWithReasoning`` 子类，处理 ``reasoning_content`` 双向 patch
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_IST_MODEL = "qwen-plus"


def resolve_llm_provider() -> str:
    """统一的 LLM 供应商标识符（dashscope / deepseek）.

    按 ``IST_LLM_PROVIDER`` env 决定；缺省 / 未识别值 → ``dashscope``.
    """
    return (os.environ.get("IST_LLM_PROVIDER") or "dashscope").strip().lower()


def resolve_llm_api_key() -> str:
    """按 ``IST_LLM_PROVIDER`` 决定查哪个 API key.

    - ``deepseek`` → ``DEEPSEEK_API_KEY``
    - 其他（含 ``dashscope`` / 缺省）→ ``DASHSCOPE_API_KEY`` / ``BAILIAN_API_KEY``
    """
    if resolve_llm_provider() == "deepseek":
        return (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    return (
        os.environ.get("DASHSCOPE_API_KEY")
        or os.environ.get("BAILIAN_API_KEY")
        or ""
    ).strip()


def _build_chat_model(provider: str, model_name: str, **kwargs: Any):
    """统一的 ChatOpenAI 工厂，按 provider 决定 base_url / api_key / extra_body。"""
    try:
        from langchain_openai import ChatOpenAI  # noqa: F401  type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("LLM 工厂需要 `pip install langchain-openai`") from exc

    extra_body = dict(kwargs.pop("extra_body", None) or {})

    if provider == "deepseek":
        base_url = (os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).strip()
        api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("provider=deepseek 需要 DEEPSEEK_API_KEY")
        
        
        
        extra_body.setdefault("reasoning_effort", "max")
    else:
        
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
                "provider=dashscope 需要 DASHSCOPE_API_KEY / BAILIAN_API_KEY / OPENAI_API_KEY 之一"
            )
        
        
        
        extra_body.setdefault("enable_thinking", True)

    kwargs.setdefault("temperature", 0.0)
    kwargs.setdefault("top_p", 0.5)
    kwargs.setdefault("streaming", True)
    
    
    
    kwargs.setdefault("stream_usage", True)
    kwargs["extra_body"] = extra_body

    cls = _get_chat_openai_with_reasoning()
    logger.info("使用 %s 兼容端点: model=%s base_url=%s", provider, model_name, base_url)
    return cls(model=model_name, base_url=base_url, api_key=api_key, **kwargs)


def build_agent_chat_model(**kwargs: Any):
    """主 LLM 工厂。按 ``IST_LLM_PROVIDER`` + ``IST_MODEL`` 路由。"""
    provider = resolve_llm_provider()
    model_name = (
        kwargs.pop("model", None)
        or os.environ.get("IST_MODEL")
        or DEFAULT_IST_MODEL
    ).strip()
    return _build_chat_model(provider, model_name, **kwargs)


def build_explore_model(**kwargs: Any):
    """Explore sub-agent：deepseek-v4-flash, thinking=disabled, 快速低成本检索。"""
    model_name = os.environ.get("IST_HAIKU_MODEL", "deepseek-v4-flash").strip()
    base_url = (os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).strip()
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("Explore model 需要 DEEPSEEK_API_KEY")

    kwargs.setdefault("temperature", 0.0)
    kwargs.setdefault("top_p", 0.5)
    kwargs.setdefault("streaming", True)
    kwargs.setdefault("stream_usage", True)
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
        """ChatOpenAI 子类，双向支持 reasoning_content（DeepSeek 多轮 + qwen 流式）.

        入方向（响应）：override ``_convert_chunk_to_generation_chunk`` 把
        ``delta.reasoning_content`` 拷到 ``message.additional_kwargs``。
        参考 langchain-ai/langchain issue #33672。

        出方向（请求）：override ``_get_request_payload`` 把上一轮 AIMessage
        的 ``additional_kwargs["reasoning_content"]`` 注入回 assistant payload
        dict 的同名 sibling 字段——DeepSeek thinking 模式下 multi-turn
        tool_call 要求这个字段必须保留，否则 400 "reasoning_content must be
        passed back"。BaseChatOpenAI 的 ``_convert_message_to_dict`` 默认会
        丢非标准 additional_kwargs，langchain issue #37178 仍 Open，无官方
        修复，所以在子类层面打补丁。
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

                originals = input_ if isinstance(input_, list) else []
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
                if os.environ.get("IST_DEBUG_PAYLOAD") == "1":
                    import json as _json  # noqa: PLC0415
                    payload_size = len(_json.dumps(payload, ensure_ascii=False))
                    msg_count = len(payload.get("messages", []))
                    logger.warning(
                        "[deepseek payload] msgs=%d size=%dKB rc_injected=%d rc_chars=%d",
                        msg_count, payload_size // 1024, injected, rc_total_chars,
                    )
            except Exception as exc:  # noqa: BLE001
                if os.environ.get("IST_DEBUG_PAYLOAD") == "1":
                    logger.warning("[deepseek payload patch err] %s", exc)
            return payload

    _CHAT_OPENAI_REASONING_CLS = ChatOpenAIWithReasoning
    return ChatOpenAIWithReasoning


def ist_core_default_model() -> str:
    """Return the platform default model configured by environment."""
    return (
        os.environ.get("IST_REVIEW_MODEL")
        or os.environ.get("IST_MODEL")
        or DEFAULT_IST_MODEL
    ).strip()








TIER_ENV_VARS = {
    "opus": "IST_OPUS_MODEL",
    "sonnet": "IST_SONNET_MODEL",
    "haiku": "IST_HAIKU_MODEL",
}


def ist_core_tier_model(tier: str) -> str:
    """Return the configured model for ``tier``（opus / sonnet / haiku）."""
    env_var = TIER_ENV_VARS.get(tier.lower(), "")
    if not env_var:
        return ist_core_default_model()
    return (os.environ.get(env_var) or ist_core_default_model()).strip()


def ist_core_select_model_for_task(task_complexity: str) -> str:
    """根据任务复杂度自动选 tier 模型.

    ``task_complexity``:
      - "high" / "review" → opus tier
      - "medium" / "qa" → sonnet tier
      - "low" / "completion" → haiku tier
    """
    tier_map = {
        "high": "opus", "review": "opus",
        "medium": "sonnet", "qa": "sonnet",
        "low": "haiku", "completion": "haiku",
    }
    tier = tier_map.get(task_complexity.lower(), "sonnet")
    return ist_core_tier_model(tier)


def ist_core_allowed_models() -> list[str]:
    """Return allowed reviewer models from ``IST_ALLOWED_MODELS``.

    Comma-separated whitelist for the ``/model`` slash command. When unset,
    only the current default model is selectable.
    """
    raw = (os.environ.get("IST_ALLOWED_MODELS") or "").strip()
    if raw:
        models = [item.strip() for item in raw.split(",") if item.strip()]
    else:
        models = [ist_core_default_model()]
    return list(dict.fromkeys(models))


def validate_review_model(model_name: str | None) -> str:
    """Return an environment-allowed reviewer model name or raise."""
    model = (model_name or ist_core_default_model()).strip()
    allowed = ist_core_allowed_models()
    if model not in allowed:
        raise ValueError(
            f"unsupported review model {model!r}; configure IST_ALLOWED_MODELS; allowed={allowed}"
        )
    return model


@contextmanager
def ist_core_model_override(model_name: str | None):
    """Temporarily route all QA reviewer model factories to a concrete model."""
    model = validate_review_model(model_name)
    old = os.environ.get("IST_MODEL")
    os.environ["IST_MODEL"] = model
    try:
        yield model
    finally:
        if old is None:
            os.environ.pop("IST_MODEL", None)
        else:
            os.environ["IST_MODEL"] = old
