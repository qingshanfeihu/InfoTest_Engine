"""Agent 层 LLM 工厂.

统一走 OpenAI 兼容端点（``OPENAI_BASE_URL`` / ``OPENAI_API_KEY``）——任何 OpenAI
协议端点皆可：小米 MiMo / DeepSeek 原生口 / DashScope 兼容口 / 自建网关。不再做
provider 分支：要换厂商只改 ``OPENAI_BASE_URL`` + key + ``IST_MODEL``。
共享 ``ChatOpenAIWithReasoning`` 子类，处理 ``reasoning_content`` 双向 patch
（思考模式 multi-turn tool_call 要求回填历史 reasoning_content）。
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
DEFAULT_IST_MODEL = "mimo-v2.5-pro"
DEFAULT_HAIKU_MODEL = "mimo-v2.5"

# 默认请求超时 / 重试。streaming 模式下端点中途 stall 时，没有 timeout
# 会无限挂（TUI 永远转圈、无报错）。可用 env 覆盖。
DEFAULT_REQUEST_TIMEOUT = 120.0
DEFAULT_MAX_RETRIES = 2


def _resolve_timeout_retries() -> tuple[float, int]:
    """从 env 解析 (request_timeout 秒, max_retries)；非法值回退默认。"""
    try:
        timeout = float(os.environ.get("IST_LLM_TIMEOUT") or DEFAULT_REQUEST_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_REQUEST_TIMEOUT
    try:
        retries = int(os.environ.get("IST_LLM_MAX_RETRIES") or DEFAULT_MAX_RETRIES)
    except (TypeError, ValueError):
        retries = DEFAULT_MAX_RETRIES
    return timeout, retries


def _resolve_streaming() -> bool:
    """是否用流式请求。默认 True（TUI astream_events 需要）；``IST_LLM_STREAMING=0`` 关。

    关流式用于**不稳定端点**的批量 agent 跑（如 print 模式跑编译流水线）：某些 OpenAI 兼容
    网关流式会周期性发空 chunk、令 httpx 每 chunk 重置读超时 → 整体响应永不完成也永不超时
    （观测到 0% CPU 死挂）。非流式是单次请求 + 干净的整体 request_timeout，遇 stall 会按时
    超时重试，不会无限挂。
    """
    return (os.environ.get("IST_LLM_STREAMING") or "1").strip().lower() not in (
        "0", "false", "off", "no",
    )


def resolve_llm_base_url() -> str:
    """OpenAI 兼容 API 根；留空走默认 MiMo CN 集群。"""
    return (os.environ.get("OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE_URL).strip()


def resolve_llm_api_key() -> str:
    """OpenAI 兼容 API key（``OPENAI_API_KEY``）。"""
    return (os.environ.get("OPENAI_API_KEY") or "").strip()


def _resolve_endpoint() -> tuple[str, str]:
    """解析 ``(base_url, api_key)``；无 key 时 raise。单一事实源。"""
    base_url = resolve_llm_base_url()
    api_key = resolve_llm_api_key()
    if not api_key:
        raise RuntimeError("需要 OPENAI_API_KEY（OpenAI 兼容端点）")
    return base_url, api_key


def _build_chat_model(model_name: str, **kwargs: Any):
    """统一的 ChatOpenAI 工厂（OpenAI 兼容端点）。"""
    try:
        from langchain_openai import ChatOpenAI  # noqa: F401  type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("LLM 工厂需要 `pip install langchain-openai`") from exc

    extra_body = dict(kwargs.pop("extra_body", None) or {})
    base_url, api_key = _resolve_endpoint()

    # 深度思考显式锁定(不再靠端点默认,防默认变更)。MiMo 与 DeepSeek 同用 thinking.type=enabled/disabled
    # (extra_body 传)。IST_THINKING=on|off 控制;默认 on。**v4-pro 默认思考开→慢;agentic loop 应 off**
    # (用 pro 的能力 + chat 的速度)。已显式传 extra_body.thinking 的不覆盖;不支持该参数的端点不注入。
    if "thinking" not in extra_body:
        _think = (os.environ.get("IST_THINKING") or "on").strip().lower()
        _bl = base_url.lower()
        _supports_thinking = any(k in _bl for k in ("mimo", "xiaomi", "deepseek"))
        if _supports_thinking:
            if _think in ("on", "1", "true", "enabled"):
                extra_body["thinking"] = {"type": "enabled"}
            elif _think in ("off", "0", "false", "disabled"):
                extra_body["thinking"] = {"type": "disabled"}

    kwargs.setdefault("temperature", 0.0)
    kwargs.setdefault("top_p", 0.5)
    _stream = _resolve_streaming()
    kwargs.setdefault("streaming", _stream)
    kwargs.setdefault("stream_usage", _stream)
    timeout, retries = _resolve_timeout_retries()
    kwargs.setdefault("request_timeout", timeout)
    kwargs.setdefault("max_retries", retries)
    kwargs["extra_body"] = extra_body

    cls = _get_chat_openai_with_reasoning()
    logger.info(
        "LLM: model=%s base_url=%s timeout=%ss retries=%s",
        model_name, base_url, timeout, retries,
    )
    return cls(model=model_name, base_url=base_url, api_key=api_key, **kwargs)


def build_agent_chat_model(**kwargs: Any):
    """主 LLM 工厂。模型取 ``IST_MODEL``。"""
    model_name = (
        kwargs.pop("model", None)
        or os.environ.get("IST_MODEL")
        or DEFAULT_IST_MODEL
    ).strip()
    return _build_chat_model(model_name, **kwargs)


def build_explore_model(**kwargs: Any):
    """Explore sub-agent：haiku tier 模型，快速低成本检索。

    走 OpenAI 兼容端点；模型取 ``IST_HAIKU_MODEL``。
    """
    model_name = (os.environ.get("IST_HAIKU_MODEL") or DEFAULT_HAIKU_MODEL).strip()
    base_url, api_key = _resolve_endpoint()

    kwargs.setdefault("temperature", 0.0)
    kwargs.setdefault("top_p", 0.5)
    _stream = _resolve_streaming()
    kwargs.setdefault("streaming", _stream)
    kwargs.setdefault("stream_usage", _stream)
    timeout, retries = _resolve_timeout_retries()
    kwargs.setdefault("request_timeout", timeout)
    kwargs.setdefault("max_retries", retries)
    extra_body = dict(kwargs.pop("extra_body", None) or {})
    # 思考模式锁定(同 _build_chat_model):IST_THINKING=off 时对 MiMo/DeepSeek 关思考(快)。
    if "thinking" not in extra_body:
        _think = (os.environ.get("IST_THINKING") or "on").strip().lower()
        if any(k in base_url.lower() for k in ("mimo", "xiaomi", "deepseek")):
            if _think in ("on", "1", "true", "enabled"):
                extra_body["thinking"] = {"type": "enabled"}
            elif _think in ("off", "0", "false", "disabled"):
                extra_body["thinking"] = {"type": "disabled"}
    kwargs["extra_body"] = extra_body

    cls = _get_chat_openai_with_reasoning()
    logger.info(
        "Explore model: model=%s base_url=%s timeout=%ss retries=%s",
        model_name, base_url, timeout, retries,
    )
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
